"""The pipeline: parse, classify, extract, verify, then accept, reject or route to review."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID

import structlog

from docintel.config import get_settings
from docintel.routers.v1alpha1.components import crud
from docintel.routers.v1alpha1.components.rules import (
    business_violations,
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

CLASSIFY_CHARS = 6000  # the first pages are enough to tell an invoice from a contract


@dataclass
class Outcome:
    status: DocumentStatus
    reason: str | None = None
    document_type: DocumentType | None = None
    confidence: float | None = None
    findings: list[Finding] = field(default_factory=list)
    facts: Facts | None = None
    evidence: list[FieldEvidence] = field(default_factory=list)


def _text(pages: list[ParsedPage]) -> str:
    return "\n\n".join(f"[page {p.number}]\n{p.text}" for p in pages)


async def llm_classify(pages: list[ParsedPage]) -> Classification:
    prompt = f"<document>\n{_text(pages)[:CLASSIFY_CHARS]}\n</document>"
    agent = get_classifier()
    result = await with_retries(lambda: agent.run(prompt), get_settings().llm_max_attempts)
    log.info("llm_call", stage="classify", model=result.response.model_name)
    return result.output


async def llm_extract(doc_type: DocumentType, pages: list[ParsedPage]) -> Facts:
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

    evidence, grounding = locate_evidence(facts.evidence, pages)
    uncertain = grounding + missing_facts(facts, evidence)
    violations = business_violations(facts)
    base = Outcome(
        DocumentStatus.ACCEPTED, None, kind, confidence, uncertain + violations, facts, evidence
    )
    if uncertain:
        base.status, base.reason = DocumentStatus.NEEDS_REVIEW, uncertain[0].message
    elif violations:
        base.status, base.reason = DocumentStatus.REJECTED, violations[0].message
    return base


async def _save(document_id: UUID, outcome: Outcome) -> None:
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
