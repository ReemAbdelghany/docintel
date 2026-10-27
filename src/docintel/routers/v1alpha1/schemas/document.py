"""Request and response schemas, and the structured output the model must return."""

from datetime import date
from decimal import Decimal
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from docintel.shared.document_types import DocumentType


class FieldEvidence(BaseModel):
    """A verbatim quote from the document that supports one extracted fact."""

    field: str
    quote: str
    page: int | None = None  # filled in by the grounding check, never by the model


class LineItem(BaseModel):
    description: str
    amount: Decimal


class InvoiceFacts(BaseModel):
    vendor_name: str | None = None
    invoice_number: str | None = None
    issue_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    evidence: list[FieldEvidence] = Field(default_factory=list)

    REQUIRED: ClassVar[tuple[str, ...]] = ("vendor_name", "invoice_number", "issue_date", "total")


class ContractFacts(BaseModel):
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

    REQUIRED: ClassVar[tuple[str, ...]] = ("parties", "effective_date")


class Classification(BaseModel):
    document_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0)


class Finding(BaseModel):
    code: str
    message: str
    field: str | None = None


class CaseResponse(BaseModel):
    case_id: UUID


class UploadResponse(BaseModel):
    document_id: UUID
    duplicate: bool
    status: str
    status_url: str


class DocumentResponse(BaseModel):
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
