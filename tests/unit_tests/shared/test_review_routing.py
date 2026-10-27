"""M6: nothing is accepted unless deterministic code agrees with the model."""

from docintel.models.states import DocumentStatus
from docintel.models.values import Evidence
from tests.unit_tests.builders import REQUIRED_EVIDENCE, an_invoice, money
from tests.unit_tests.fakes import Pipeline


async def test_wrong_invoice_lands_in_needs_review_with_a_readable_reason() -> None:
    pipeline = Pipeline(facts=an_invoice(total="1200.00"))
    document_id = await pipeline.submit()

    await pipeline.run_all()

    assert pipeline.status(document_id) is DocumentStatus.NEEDS_REVIEW
    reasons = pipeline.review_reasons(document_id)
    assert any(r.startswith("TOTAL_MISMATCH:total") for r in reasons)
    assert "1150.00" in reasons[0] and "1200.00" in reasons[0]


async def test_a_value_the_document_does_not_contain_is_not_accepted() -> None:
    invented = (
        *[e for e in REQUIRED_EVIDENCE if e.field != "total"],
        Evidence("total", 1, "Total 9999.00"),
    )
    pipeline = Pipeline(facts=an_invoice(total="9999.00"), evidence=invented)
    document_id = await pipeline.submit()

    await pipeline.run_all()

    assert pipeline.status(document_id) is DocumentStatus.NEEDS_REVIEW
    assert any(
        r.startswith("UNGROUNDED_EVIDENCE:total") for r in pipeline.review_reasons(document_id)
    )


async def test_low_classification_confidence_goes_to_review() -> None:
    pipeline = Pipeline(classification_confidence=0.4)
    document_id = await pipeline.submit()

    await pipeline.run_all()

    assert pipeline.status(document_id) is DocumentStatus.NEEDS_REVIEW
    assert "LOW_CLASSIFICATION_CONFIDENCE" in pipeline.review_reasons(document_id)


async def test_a_missing_required_fact_goes_to_review() -> None:
    facts = an_invoice()
    no_number = type(facts)(
        vendor_name=facts.vendor_name,
        invoice_number=None,
        issue_date=facts.issue_date,
        subtotal=facts.subtotal,
        tax=facts.tax,
        total=money("1150.00"),
    )
    pipeline = Pipeline(facts=no_number)
    document_id = await pipeline.submit()

    await pipeline.run_all()

    assert pipeline.status(document_id) is DocumentStatus.NEEDS_REVIEW
    assert any(
        r.startswith("MISSING_REQUIRED:invoice_number")
        for r in pipeline.review_reasons(document_id)
    )


async def test_a_job_resumed_after_extraction_is_still_verified() -> None:
    pipeline = Pipeline(facts=an_invoice(total="1200.00"))
    document_id = await pipeline.submit()
    await pipeline.run_all()
    analysis = pipeline.store.analyses[document_id]
    analysis.reprocess()
    analysis.record_extraction(
        analysis.current.facts, analysis.current.evidence, analysis.current.provenance
    )

    await pipeline.analyze(document_id)  # crashed between extract and verify; the retry finishes it

    assert pipeline.status(document_id) is DocumentStatus.NEEDS_REVIEW
