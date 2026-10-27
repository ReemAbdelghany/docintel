"""Domain services: stateless logic that belongs to no single aggregate."""

import unicodedata
from collections.abc import Iterable
from decimal import Decimal

from docintel.models.analysis import Finding, Severity
from docintel.models.facts import Facts
from docintel.models.parsed import ParsedDocument
from docintel.models.values import Evidence, Money

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold().translate(ARABIC_DIGITS)
    return " ".join(folded.split())


def amount_in_text(amount: Decimal, text: str) -> bool:
    cleaned = normalize(text).replace(",", "").replace(" ", "")
    return any(c in cleaned for c in {f"{amount:f}", f"{amount.normalize():f}"})


class GroundingVerifier:
    """Confirms every cited quote really appears in the parsed text and contains its value."""

    def verify(
        self, facts: Facts, evidence: Iterable[Evidence], doc: ParsedDocument
    ) -> list[Finding]:
        findings: list[Finding] = []
        for ev in evidence:
            page = doc.page(ev.page)
            if page is None or normalize(ev.snippet) not in normalize(page.text):
                findings.append(
                    Finding(
                        "UNGROUNDED_EVIDENCE",
                        Severity.BLOCKING,
                        ev.field,
                        f"quote not found on page {ev.page}",
                    )
                )
                continue
            value = getattr(facts, ev.field, None)
            if isinstance(value, Money) and not amount_in_text(value.amount, ev.snippet):
                findings.append(
                    Finding(
                        "VALUE_NOT_IN_QUOTE",
                        Severity.BLOCKING,
                        ev.field,
                        "amount does not appear in the cited text",
                    )
                )
        return findings
