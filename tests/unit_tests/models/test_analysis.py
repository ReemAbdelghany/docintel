from uuid import uuid4

import pytest

from docintel.models.analysis import DocumentAnalysis, Finding, Severity
from docintel.models.errors import IllegalTransition, InvariantViolated
from docintel.models.events import (
    AnalysisAccepted,
    AnalysisFailed,
    DocumentParsed,
    ExtractionCompleted,
    ReviewRequested,
)
from docintel.models.states import DocumentStatus
from docintel.models.values import Confidence, DocumentType, Evidence
from tests.unit_tests.builders import (
    a_new_analysis,
    a_provenance,
    a_validated_analysis,
    an_accepted_analysis,
    an_extracted_analysis,
    an_invoice,
)


def test_accept_is_blocked_by_a_blocking_finding() -> None:
    analysis = a_validated_analysis(findings=[Finding("ARITHMETIC", Severity.BLOCKING, "total")])

    with pytest.raises(InvariantViolated):
        analysis.accept()


def test_accept_allows_advisory_findings() -> None:
    analysis = a_validated_analysis(findings=[Finding("LOW_CONFIDENCE", Severity.ADVISORY)])

    analysis.accept()

    assert analysis.status is DocumentStatus.ACCEPTED


def test_accept_requires_evidence_for_every_required_fact() -> None:
    analysis = a_validated_analysis(evidence=())

    with pytest.raises(InvariantViolated):
        analysis.accept()


def test_accept_ignores_evidence_for_facts_that_are_absent() -> None:
    evidence = (Evidence("vendor_name", 1, "Acme Supplies"),)
    analysis = a_validated_analysis(evidence=evidence)

    with pytest.raises(InvariantViolated):
        analysis.accept()  # invoice_number, issue_date and total are present but unsupported


def test_cannot_skip_a_stage() -> None:
    analysis = DocumentAnalysis(uuid4(), uuid4(), "x.pdf", "local://x")

    with pytest.raises(IllegalTransition):
        analysis.classify(DocumentType.INVOICE, Confidence(0.9))


def test_cannot_accept_before_verification() -> None:
    analysis = an_extracted_analysis()

    with pytest.raises(IllegalTransition):
        analysis.accept()


def test_review_then_reprocess_returns_to_classification() -> None:
    analysis = a_validated_analysis()
    analysis.request_review(["total does not match line items"])

    analysis.reprocess()

    assert analysis.status is DocumentStatus.CLASSIFIED
    assert analysis.findings == []


def test_reextraction_keeps_history() -> None:
    analysis = an_accepted_analysis()
    analysis.reprocess()

    analysis.record_extraction(an_invoice(), (), a_provenance())

    assert [e.version for e in analysis.extractions] == [1, 2]
    assert analysis.current.version == 2


def test_any_working_stage_can_fail_and_failed_can_be_retried() -> None:
    analysis = a_new_analysis()
    analysis.fail("provider down")

    assert analysis.status is DocumentStatus.FAILED
    analysis._move(DocumentStatus.RECEIVED)  # manual retry is an allowed transition
    assert analysis.status is DocumentStatus.RECEIVED


def test_a_terminal_decision_cannot_fail() -> None:
    analysis = an_accepted_analysis()

    with pytest.raises(IllegalTransition):
        analysis.fail("too late")


def test_current_extraction_requires_one_to_exist() -> None:
    with pytest.raises(InvariantViolated):
        _ = a_new_analysis().current


def test_events_are_raised_in_order_and_pulled_once() -> None:
    analysis = a_new_analysis()
    analysis.record_parse("memory://parsed/x.json")
    analysis.classify(DocumentType.INVOICE, Confidence(0.9))
    analysis.record_extraction(an_invoice(), (), a_provenance())
    analysis.record_verification([])
    analysis.request_review(["missing evidence"])

    events = analysis.pull_events()

    assert [type(e) for e in events] == [DocumentParsed, ExtractionCompleted, ReviewRequested]
    assert analysis.pull_events() == []


def test_accept_and_failure_raise_their_events() -> None:
    accepted = an_accepted_analysis()
    failed = a_new_analysis()
    failed.fail("corrupt file")

    assert isinstance(accepted.pull_events()[-1], AnalysisAccepted)
    assert isinstance(failed.pull_events()[-1], AnalysisFailed)
