"""The LLM-facing contract. Tuned with prompts; mapped into domain facts, never used as them."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class LlmEvidence(BaseModel):
    field: str
    page: int
    quote: str = Field(description="Exact text copied from the document that supports the value")


class LlmLineItem(BaseModel):
    description: str
    amount: Decimal


class LlmInvoice(BaseModel):
    vendor_name: str | None = None
    invoice_number: str | None = None
    issue_date: date | None = None
    currency: str | None = Field(None, description="ISO 4217 code such as EGP, AED, SAR or USD")
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    line_items: list[LlmLineItem] = []
    evidence: list[LlmEvidence] = []


class LlmClassification(BaseModel):
    doc_type: Literal["lease", "invoice", "contract", "other"]
    confidence: float = Field(ge=0, le=1)
