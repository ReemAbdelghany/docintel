"""Pure mapping between aggregates and rows or JSON. Decimal and date travel as strings."""

import dataclasses
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import UUID

from docintel.models.analysis import DocumentAnalysis, Extraction, Finding, Provenance, Severity
from docintel.models.events import (
    AnalysisAccepted,
    AnalysisFailed,
    DocumentParsed,
    DocumentSubmitted,
    DomainEvent,
    ExtractionCompleted,
    ReviewRequested,
)
from docintel.models.facts import Facts, InvoiceFacts, LineItem
from docintel.models.states import DocumentStatus
from docintel.models.values import Confidence, DocumentType, Evidence, Money
from docintel.utils.providers.db.tables import AnalysisRow, ExtractionRow, Json


def _money_to_json(money: Money | None) -> Json | None:
    return None if money is None else {"amount": str(money.amount), "currency": money.currency}


def _money_from_json(data: object) -> Money | None:
    if data is None:
        return None
    item = cast(Json, data)
    return Money(Decimal(str(item["amount"])), str(item["currency"]))


def _invoice_to_json(facts: InvoiceFacts) -> Json:
    return {
        "vendor_name": facts.vendor_name,
        "invoice_number": facts.invoice_number,
        "issue_date": facts.issue_date.isoformat() if facts.issue_date else None,
        "subtotal": _money_to_json(facts.subtotal),
        "tax": _money_to_json(facts.tax),
        "total": _money_to_json(facts.total),
        "line_items": [
            {"description": i.description, "amount": _money_to_json(i.amount)}
            for i in facts.line_items
        ],
    }


def _invoice_from_json(data: Json) -> InvoiceFacts:
    issue_date = data.get("issue_date")
    items = cast(list[Json], data.get("line_items") or [])
    return InvoiceFacts(
        vendor_name=cast("str | None", data.get("vendor_name")),
        invoice_number=cast("str | None", data.get("invoice_number")),
        issue_date=date.fromisoformat(str(issue_date)) if issue_date else None,
        subtotal=_money_from_json(data.get("subtotal")),
        tax=_money_from_json(data.get("tax")),
        total=_money_from_json(data.get("total")),
        line_items=tuple(
            LineItem(str(i["description"]), cast(Money, _money_from_json(i["amount"])))
            for i in items
        ),
    )


def facts_to_json(facts: Facts) -> tuple[str, Json]:
    """Return the facts_type tag and the JSON form. One branch per document type."""
    if isinstance(facts, InvoiceFacts):
        return "invoice", _invoice_to_json(facts)
    raise TypeError(f"no mapper for {type(facts).__name__}")


def facts_from_json(facts_type: str, data: Json) -> Facts:
    match facts_type:
        case "invoice":
            return _invoice_from_json(data)
        case _:
            raise TypeError(f"no mapper for facts type {facts_type}")


def _finding_to_json(f: Finding) -> Json:
    return {"code": f.code, "severity": f.severity.value, "field": f.field, "message": f.message}


def _finding_from_json(d: Json) -> Finding:
    return Finding(
        str(d["code"]),
        Severity(str(d["severity"])),
        cast("str | None", d.get("field")),
        str(d.get("message", "")),
    )


def extraction_to_row(document_id: UUID, e: Extraction) -> ExtractionRow:
    facts_type, facts = facts_to_json(e.facts)
    return ExtractionRow(
        document_id=document_id,
        version=e.version,
        facts_type=facts_type,
        facts=facts,
        evidence=[dataclasses.asdict(x) for x in e.evidence],
        provenance=dataclasses.asdict(e.provenance),
    )


def extraction_from_row(row: ExtractionRow) -> Extraction:
    return Extraction(
        version=row.version,
        facts=facts_from_json(row.facts_type, row.facts),
        evidence=tuple(
            Evidence(str(x["field"]), int(cast(int, x["page"])), str(x["snippet"]))
            for x in row.evidence
        ),
        provenance=Provenance(
            str(row.provenance["model"]),
            str(row.provenance["prompt_version"]),
            str(row.provenance["schema_version"]),
            int(cast(int, row.provenance["input_tokens"])),
            int(cast(int, row.provenance["output_tokens"])),
        ),
    )


def apply_to_row(analysis: DocumentAnalysis, row: AnalysisRow) -> None:
    """Copy the aggregate's current state onto its row."""
    row.status = analysis.status.value
    row.parsed_uri = analysis.parsed_uri
    row.document_type = analysis.document_type.value if analysis.document_type else None
    row.classification_confidence = (
        analysis.classification_confidence.value if analysis.classification_confidence else None
    )
    row.findings = [_finding_to_json(f) for f in analysis.findings]


def to_row(analysis: DocumentAnalysis) -> AnalysisRow:
    row = AnalysisRow(
        document_id=analysis.document_id,
        case_id=analysis.case_id,
        filename=analysis.filename,
        storage_uri=analysis.storage_uri,
    )
    apply_to_row(analysis, row)
    return row


def to_domain(row: AnalysisRow, extractions: list[ExtractionRow]) -> DocumentAnalysis:
    analysis = DocumentAnalysis(row.document_id, row.case_id, row.filename, row.storage_uri)
    analysis.status = DocumentStatus(row.status)
    analysis.parsed_uri = row.parsed_uri
    analysis.document_type = DocumentType(row.document_type) if row.document_type else None
    analysis.classification_confidence = (
        Confidence(row.classification_confidence)
        if row.classification_confidence is not None
        else None
    )
    analysis.findings = [_finding_from_json(f) for f in row.findings]
    analysis.extractions = [extraction_from_row(e) for e in extractions]
    return analysis


_EVENTS: dict[str, type[DomainEvent]] = {
    cls.__name__: cls
    for cls in (
        DocumentSubmitted,
        DocumentParsed,
        ExtractionCompleted,
        AnalysisAccepted,
        ReviewRequested,
        AnalysisFailed,
    )
}


def event_to_json(event: DomainEvent) -> Json:
    out: Json = {}
    for f in dataclasses.fields(event):
        value = getattr(event, f.name)
        if isinstance(value, UUID):
            out[f.name] = str(value)
        elif isinstance(value, tuple):
            out[f.name] = list(value)
        else:
            out[f.name] = value
    return out


def event_from_json(event_type: str, data: Json) -> DomainEvent:
    cls = _EVENTS[event_type]
    kwargs: Json = {}
    for f in dataclasses.fields(cls):
        value = data[f.name]
        if f.name.endswith("_id") and value is not None:
            kwargs[f.name] = UUID(str(value))
        elif isinstance(value, list):
            kwargs[f.name] = tuple(value)
        else:
            kwargs[f.name] = value
    return cls(**kwargs)  # type: ignore[arg-type]  # fields come from the dataclass itself
