"""The decision: accept automatically or send to a person, with readable reasons."""

from collections.abc import Sequence
from dataclasses import dataclass

from docintel.models.analysis import Finding
from docintel.models.values import Confidence


@dataclass(frozen=True, slots=True)
class Decision:
    accept: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewPolicy:
    """Thresholds are injected configuration; the rules are code."""

    min_classification: Confidence

    def decide(self, findings: Sequence[Finding], classification: Confidence) -> Decision:
        reasons = [_reason(f) for f in findings if f.blocking]
        if classification.value < self.min_classification.value:
            reasons.append("LOW_CLASSIFICATION_CONFIDENCE")
        return Decision(accept=not reasons, reasons=tuple(reasons))


def _reason(finding: Finding) -> str:
    base = f"{finding.code}:{finding.field}" if finding.field else finding.code
    return f"{base} ({finding.message})" if finding.message else base
