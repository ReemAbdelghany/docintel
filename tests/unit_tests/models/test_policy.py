from docintel.models.analysis import Finding, Severity
from docintel.models.rules import ReviewPolicy
from docintel.models.values import Confidence

POLICY = ReviewPolicy(Confidence(0.7))


def test_clean_and_confident_is_accepted() -> None:
    assert POLICY.decide([], Confidence(0.9)).accept


def test_advisory_findings_do_not_block() -> None:
    assert POLICY.decide([Finding("FUTURE_DATE", Severity.ADVISORY)], Confidence(0.9)).accept


def test_blocking_findings_become_readable_reasons() -> None:
    finding = Finding("TOTAL_MISMATCH", Severity.BLOCKING, "total", "1150 vs 1200")

    decision = POLICY.decide([finding], Confidence(0.9))

    assert not decision.accept
    assert decision.reasons == ("TOTAL_MISMATCH:total (1150 vs 1200)",)


def test_low_classification_confidence_adds_a_reason() -> None:
    assert POLICY.decide([], Confidence(0.5)).reasons == ("LOW_CLASSIFICATION_CONFIDENCE",)
