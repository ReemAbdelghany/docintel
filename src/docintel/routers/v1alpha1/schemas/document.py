"""API request/response schemas and LLM structured output models.

This module defines all Pydantic models used for:
- API request/response serialization (CaseResponse, UploadResponse, DocumentResponse)
- LLM structured output (Classification, InvoiceFacts, ContractFacts, FieldEvidence)
- Internal validation findings (Finding)

The LLM output models (InvoiceFacts, ContractFacts) are used directly by
Pydantic AI agents as output_type, ensuring the model returns validated,
structured data that matches these schemas exactly.
"""

from datetime import date
from decimal import Decimal
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from docintel.shared.document_types import DocumentType


class FieldEvidence(BaseModel):
    """A verbatim quote from the document that supports one extracted fact.

    The model provides the field name and quote. The grounding step in the
    verification pipeline fills in the page number by locating the quote
    in the parsed document text.

    Attributes:
        field: Name of the fact field this evidence supports.
        quote: Verbatim text span from the document (single line, no ellipsis).
        page: 1-based page number where the quote was found (filled by grounding).
    """

    field: str
    quote: str
    page: int | None = None  # filled in by the grounding check, never by the model


class LineItem(BaseModel):
    """A single line item from an invoice.

    Attributes:
        description: Item description text.
        amount: Line item amount (plain number, no thousands separators).
    """

    description: str
    amount: Decimal


class InvoiceFacts(BaseModel):
    """Structured facts extracted from an invoice document.

    All amounts are plain numbers without thousands separators. Currency is
    the 3-letter ISO code (e.g., EGP, USD). Evidence is required for
    vendor_name, invoice_number, issue_date, and total.

    Attributes:
        vendor_name: Company issuing the invoice.
        invoice_number: Invoice identifier.
        issue_date: Date the invoice was issued.
        currency: 3-letter ISO currency code.
        subtotal: Subtotal before tax.
        tax: Tax amount.
        total: Total amount due.
        line_items: List of invoice line items.
        evidence: Model-provided quotes for each fact (grounded later).
    """

    vendor_name: str | None = None
    invoice_number: str | None = None
    issue_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    evidence: list[FieldEvidence] = Field(default_factory=list)

    # Required fields that must be present and grounded for acceptance
    REQUIRED: ClassVar[tuple[str, ...]] = ("vendor_name", "invoice_number", "issue_date", "total")


class ContractFacts(BaseModel):
    """Structured facts extracted from a contract/agreement document.

    Covers leases, service agreements, supply contracts, etc. Amounts are
    plain numbers without thousands separators. Currency is the 3-letter
    ISO code. total_value is ONLY a total for the entire term stated in
    the document itself - never a periodic amount.

    Attributes:
        title: Document title if present.
        parties: Legal names of all contracting parties (people or companies).
        effective_date: Agreement start date (commencement date).
        end_date: Agreement expiration date.
        recurring_amount: Amount paid each period (e.g., monthly rent).
        recurring_period: Period for recurring amount (monthly/quarterly/yearly).
        annual_increase_percent: Yearly increase percentage for recurring amount.
        security_deposit: Security deposit amount if stated.
        total_value: Total for the WHOLE term as stated in document.
        currency: 3-letter ISO currency code.
        evidence: Model-provided quotes for each fact (grounded later).
    """

    title: str | None = None
    parties: list[str] = Field(
        default_factory=list,
        description="Legal names of each contracting party (people or companies); no roles",
    )
    effective_date: date | None = Field(
        default=None, description="Date the agreement starts (commencement date)"
    )
    end_date: date | None = Field(default=None, description="Date the agreement expires")
    recurring_amount: Decimal | None = Field(
        default=None, description="Amount paid each period, for example the monthly rent"
    )
    recurring_period: Literal["monthly", "quarterly", "yearly"] | None = None
    annual_increase_percent: Decimal | None = Field(
        default=None, description="Yearly increase of the recurring amount, in percent"
    )
    security_deposit: Decimal | None = None
    total_value: Decimal | None = Field(
        default=None,
        description="Only a total for the WHOLE term that the document states; never the "
        "periodic amount",
    )
    currency: str | None = Field(
        default=None, description="3-letter ISO code of the money amounts, for example EGP"
    )
    evidence: list[FieldEvidence] = Field(default_factory=list)

    # Required fields that must be present and grounded for acceptance
    REQUIRED: ClassVar[tuple[str, ...]] = ("parties", "effective_date")


class Classification(BaseModel):
    """Document classification result from the LLM.

    Attributes:
        document_type: Classified type (invoice, contract, other).
        confidence: Confidence score between 0.0 and 1.0.
    """

    document_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0)


class Finding(BaseModel):
    """A validation finding (warning, error, or derivation note).

    Findings are generated during the deterministic verification step and
    included in the API response to explain the document outcome.

    Attributes:
        code: Machine-readable finding code (e.g., MISSING_FACT, TOTAL_MISMATCH).
        message: Human-readable explanation.
        field: Related fact field name (None for document-level findings).
    """

    code: str
    message: str
    field: str | None = None


class CaseResponse(BaseModel):
    """Response for case creation.

    Attributes:
        case_id: UUID of the newly created case.
    """

    case_id: UUID


class UploadResponse(BaseModel):
    """Response for document upload.

    Attributes:
        document_id: UUID of the uploaded/created document.
        duplicate: True if the same content was already uploaded to this case.
        status: Initial document status (always "processing" for new uploads).
        status_url: URL to poll for processing results.
    """

    document_id: UUID
    duplicate: bool
    status: str
    status_url: str


class DocumentResponse(BaseModel):
    """Complete document status and extraction results.

    Returned by GET /documents/{document_id}. Contains the final outcome
    of the processing pipeline including all extracted facts, evidence,
    and any findings.

    Attributes:
        document_id: UUID of the document.
        case_id: UUID of the parent case.
        filename: Original uploaded filename.
        status: Final status (accepted/rejected/needs_review/processing).
        document_type: Classified type (invoice/contract/other) or None.
        classification_confidence: Classification confidence score or None.
        reason: Human-readable reason for rejection or review (None if accepted).
        findings: List of validation findings (warnings, errors, derivations).
        facts: Extracted facts as a dictionary (InvoiceFacts or ContractFacts).
        evidence: Grounded evidence quotes with page numbers.
        model: LLM model specification used for extraction (None if not extracted).
    """

    document_id: UUID
    case_id: UUID
    filename: str
    status: str
    document_type: str | None
    classification_confidence: float | None
    reason: str | None
    findings: list[Finding]
    facts: dict[str, object] | None
    evidence: list[FieldEvidence]
    model: str | None
