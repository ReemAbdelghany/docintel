"""The contract every document type's business rules implement."""

from typing import Protocol

from docintel.models.analysis import Finding
from docintel.models.facts import Facts


class ExtractionRules(Protocol):
    def check(self, facts: Facts) -> list[Finding]: ...
