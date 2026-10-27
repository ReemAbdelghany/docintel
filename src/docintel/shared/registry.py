"""Which rules apply to which document type. Adding a type is a local change."""

from collections.abc import Mapping

from docintel.models.rules import ExtractionRules, InvoiceRules
from docintel.models.values import DocumentType


def default_rules() -> Mapping[DocumentType, ExtractionRules]:
    return {DocumentType.INVOICE: InvoiceRules()}
