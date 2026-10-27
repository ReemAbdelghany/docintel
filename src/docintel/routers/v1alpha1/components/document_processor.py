"""The document processing pipeline: parse, classify, extract, verify, decide.

This module implements the core background task that processes uploaded documents
through the full pipeline:

1. Parse: Convert PDF/image to per-page text using Docling (OCR for scans)
2. Classify: LLM determines document type (invoice, contract, other) + confidence
3. Extract: LLM extracts structured facts based on document type
4. Verify: Deterministic rules check evidence grounding, required facts, business rules
5. Decide: Outcome is accepted, rejected, or needs_review

The pipeline runs as a FastAPI background task after upload returns 202 Accepted.
All provider calls (LLM, parser, storage) use retry logic with exponential backoff.
Tracing spans are created via Logfire when enabled.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID

import structlog

from docintel.config import get_settings
from docintel.routers.v1alpha1.components import crud
from docintel.routers.v1alpha1.components.rules import (
    business_violations,
    derive_contract_values,
    ground_by_value,
    locate_evidence,
    missing_facts,
)
from docintel.routers.v1alpha1.schemas.document import (
    Classification,
    ContractFacts,
    FieldEvidence,
    Finding,
    InvoiceFacts,
)
from docintel.shared.document_types import DocumentStatus, DocumentType, ParsedPage
from docintel.shared.errors import ProcessingError
from docintel.utils.common.retry import with_retries
from docintel.utils.providers.llm_provider import get_classifier, get_extractor
from docintel.utils.providers.parser_provider import parse_document
from docintel.utils.providers.storage_provider import get_storage
from docintel.utils.providers.tracing_provider import document_span

logger = logging.getLogger(__name__)
log = structlog.get_logger()

Facts = InvoiceFacts | ContractFacts
Classify = Callable[[list[ParsedPage]], Awaitable[Classification]]
Extract = Callable[[DocumentType, list[ParsedPage]], Awaitable[Facts]]

# Only the first pages are needed to distinguish invoice from contract
CLASSIFY_CHARS = 6000


@dataclass
class Outcome:
    """Processing pipeline outcome.

    Encapsulates the final decision and all supporting data for a document.
    Used internally by the pipeline before persisting to the database.

    Attributes:
        status: Final document status (accepted/rejected/needs_review).
        reason: Human-readable reason for rejection or review (None if accepted).
        document_type: Classified type (invoice/contract/other).
        confidence: Classification confidence score (0.0-1.0).
        findings: List of findings (warnings, errors, derivations).
        facts: Extracted structured facts (InvoiceFacts or ContractFacts).
        evidence: Grounded evidence quotes with page numbers.
    """

    status: DocumentStatus
    reason: str | None = None
    document_type: DocumentType | None = None
    confidence: float | None = None
    findings: list[Finding] = field(default_factory=list)
    facts: Facts | None = None
    evidence: list[FieldEvidence] = field(default_factory=list)


def _text(pages: list[ParsedPage]) -> str:
    """Format parsed pages as a single string with page markers.

    Args:
        pages: List of parsed pages.

    Returns:
        str: Concatenated text with [page N] headers.
    """
    return "\n\n".join(f"[page {p.number}]\n{p.text}" for p in pages)


async def llm_classify(pages: list[ParsedPage]) -> Classification:
    """Classify document type using the LLM classifier agent.

    Sends the first CLASSIFY_CHARS characters of the document to the classifier
    agent with the CLASSIFY prompt. Uses retry logic for transient failures.

    Args:
        pages: Parsed document pages.

    Returns:
        Classification: Document type and confidence.

    Raises:
        ProcessingError: If classification fails after all retries.
    """
    prompt = f"<document>\n{_text(pages)[:CLASSIFY_CHARS]}\n</document>"
    agent = get_classifier()
    result = await with_retries(lambda: agent.run(prompt), get_settings().llm_max_attempts)
    log.info("llm_call", stage="classify", model=result.response.model_name)
    return result.output


async def llm_extract(doc_type: DocumentType, pages: list[ParsedPage]) -> Facts:
    """Extract structured facts using the appropriate LLM extractor agent.

    Sends the full document text to the invoice or contract extractor agent
    with the corresponding prompt. Uses retry logic for transient failures.

    Args:
        doc_type: Document type (INVOICE or CONTRACT).
        pages: Parsed document pages.

    Returns:
        InvoiceFacts | ContractFacts: Extracted facts matching the document type.

    Raises:
        ProcessingError: If extraction fails after all retries.
    """
    prompt = f"<document>\n{_text(pages)}\n</document>"
    agent = get_extractor(doc_type)
    result = await with_retries(lambda: agent.run(prompt), get_settings().llm_max_attempts)
    log.info("llm_call", stage="extract", model=result.response.model_name)
    output = result.output
    assert isinstance(output, InvoiceFacts | ContractFacts)  # noqa: S101 - agent matches type
    return output


async def analyze(
    pages: list[ParsedPage], classify: Classify, extract: Extract, min_confidence: float
) -> Outcome:
    """Run the full analysis pipeline on parsed document pages.

    Orchestrates classification, extraction, and verification steps:
    1. Classify document type and confidence
    2. If confidence too low or type is OTHER -> needs_review/rejected
    3. Extract facts for the classified type
    4. Derive missing contract values (currency, total_value)
    5. Ground evidence quotes to document pages
    6. Repair missing evidence by searching for values
    7. Check for missing required facts
    8. Check business rule violations
    9. Determine final outcome

    Args:
        pages: Parsed document pages.
        classify: Classification function (llm_classify).
        extract: Extraction function (llm_extract).
        min_confidence: Minimum classification confidence threshold.

    Returns:
        Outcome: Complete processing result with status, facts, evidence, findings.
    """
    """Decide what to do with a parsed document.

    needs_review: the system cannot be confident (classification or extraction failed or was
    unsure, a quote is not in the document, a required fact is missing).
    rejected: the document was read with confidence but is not an invoice or contract, or it
    breaks a business rule. accepted: everything checks out.
    """
    try:
        classification = await classify(pages)
    except ProcessingError as exc:
        return Outcome(DocumentStatus.NEEDS_REVIEW, f"classification failed: {exc}")
    kind, confidence = classification.document_type, classification.confidence
    if confidence < min_confidence:
        return Outcome(
            DocumentStatus.NEEDS_REVIEW,
            f"classification confidence {confidence:.2f} is below {min_confidence:.2f}",
            kind,
            confidence,
        )
    if kind is DocumentType.OTHER:
        return Outcome(DocumentStatus.REJECTED, "not an invoice or a contract", kind, confidence)
    try:
        facts = await extract(kind, pages)
    except ProcessingError as exc:
        return Outcome(DocumentStatus.NEEDS_REVIEW, f"extraction failed: {exc}", kind, confidence)

    notes = derive_contract_values(facts, pages) if isinstance(facts, ContractFacts) else []
    evidence, grounding = locate_evidence(facts.evidence, pages)
    evidence, grounding = ground_by_value(facts, evidence, grounding, pages)
    uncertain = grounding + missing_facts(facts, evidence)
    violations = business_violations(facts)
    base = Outcome(
        DocumentStatus.ACCEPTED,
        None,
        kind,
        confidence,
        uncertain + violations + notes,
        facts,
        evidence,
    )
    if uncertain:
        base.status, base.reason = DocumentStatus.NEEDS_REVIEW, uncertain[0].message
    elif violations:
        base.status, base.reason = DocumentStatus.REJECTED, violations[0].message
    return base


async def _save(document_id: UUID, outcome: Outcome) -> None:
    """Persist the pipeline outcome to the database.

    Converts the internal Outcome dataclass to the database Document model
    format (JSON-serialized facts, evidence, findings) and updates the record.

    Args:
        document_id: UUID of the document to update.
        outcome: Pipeline outcome to persist.
    """
    await crud.save_result(
        document_id,
        status=outcome.status,
        reason=outcome.reason,
        document_type=outcome.document_type,
        classification_confidence=outcome.confidence,
        findings=[f.model_dump() for f in outcome.findings],
        facts=outcome.facts.model_dump(mode="json", exclude={"evidence"})
        if outcome.facts
        else None,
        evidence=[e.model_dump(mode="json") for e in outcome.evidence],
        model=get_settings().llm_model if outcome.facts else None,
    )
    log.info(
        "document_outcome",
        document_id=str(document_id),
        status=outcome.status,
        document_type=outcome.document_type,
        reason=outcome.reason,
    )


async def process_document(document_id: UUID) -> None:
    """Background task: run the full pipeline and store the outcome.

    This is the main entry point for document processing, called as a FastAPI
    background task after upload. It:
    1. Fetches the document and its raw content from storage
    2. Parses the document to per-page text
    3. Runs the analysis pipeline within a tracing span
    4. Persists the outcome
    5. Handles all errors by marking the document as needs_review

    The function never leaves a document stuck in PROCESSING - any unexpected
    error results in a needs_review outcome with a generic reason.

    Args:
        document_id: UUID of the document to process.
    """
    """Background task: run the whole pipeline and store the outcome."""
    try:
        document = await crud.get_document(document_id)
        if document is None:
            return
        content = await get_storage().get(document.storage_uri)
        try:
            pages = await parse_document(content, document.filename)
        except ProcessingError as exc:
            await _save(document_id, Outcome(DocumentStatus.NEEDS_REVIEW, f"parsing failed: {exc}"))
            return
        with document_span(str(document_id), document.filename):
            outcome = await analyze(
                pages, llm_classify, llm_extract, get_settings().min_classification_confidence
            )
        await _save(document_id, outcome)
    except Exception:  # background boundary: never leave a document stuck in processing
        logger.exception("unexpected error while processing %s", document_id)
        try:
            await _save(
                document_id,
                Outcome(DocumentStatus.NEEDS_REVIEW, "unexpected error, see the service logs"),
            )
        except Exception:  # the database itself is down; startup recovery will flag it
            logger.exception("could not record the failure for %s", document_id)
