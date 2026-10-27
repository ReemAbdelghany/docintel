import pytest

from docintel.models.errors import PayloadTooLarge, ProviderUnavailable
from docintel.models.events import DocumentParsed, DocumentSubmitted
from docintel.models.states import DocumentStatus
from docintel.models.values import DocumentType
from docintel.shared.use_cases.submit_document import MAX_UPLOAD_BYTES
from tests.unit_tests.fakes import Pipeline


async def test_clean_invoice_goes_all_the_way_to_accepted(pipeline: Pipeline) -> None:
    document_id = await pipeline.submit()

    await pipeline.run_all()

    assert pipeline.status(document_id) is DocumentStatus.ACCEPTED
    assert pipeline.store.analyses[document_id].current.version == 1


async def test_running_a_stage_twice_changes_nothing(pipeline: Pipeline) -> None:
    document_id = await pipeline.submit()
    await pipeline.run_all()

    await pipeline.parse(document_id)
    await pipeline.parse(document_id)
    await pipeline.analyze(document_id)

    assert pipeline.events_of(document_id).count(DocumentParsed) == 1
    assert len(pipeline.store.analyses[document_id].extractions) == 1
    assert pipeline.parser.calls == 1
    assert pipeline.extractor.calls == 1


async def test_uploading_the_same_file_twice_returns_the_existing_document(
    pipeline: Pipeline,
) -> None:
    first = await pipeline.submit(b"same bytes")
    second = await pipeline.submit(b"same bytes")
    await pipeline.run_all()

    assert first == second
    assert pipeline.events_of(first).count(DocumentSubmitted) == 1
    assert len(pipeline.store.analyses) == 1


async def test_delivering_the_submitted_event_twice_creates_one_analysis(
    pipeline: Pipeline,
) -> None:
    await pipeline.submit()
    submitted = next(e for e in pipeline.store.events if isinstance(e, DocumentSubmitted))

    await pipeline.start(submitted)
    await pipeline.start(submitted)

    assert len(pipeline.store.analyses) == 1
    assert len(pipeline.store.jobs) == 1


async def test_oversized_upload_is_refused_before_anything_is_stored(
    pipeline: Pipeline,
) -> None:
    with pytest.raises(PayloadTooLarge):
        await pipeline.submit(b"x" * (MAX_UPLOAD_BYTES + 1))

    assert pipeline.store.events == []


async def test_unsupported_document_type_goes_to_review() -> None:
    pipeline = Pipeline(doc_type=DocumentType.LEASE)  # no lease extractor until M10
    document_id = await pipeline.submit()

    await pipeline.run_all()

    assert pipeline.status(document_id) is DocumentStatus.NEEDS_REVIEW
    assert pipeline.review_reasons(document_id) == ("UNSUPPORTED_DOCUMENT_TYPE",)


async def test_a_transient_provider_failure_is_resumed_by_a_retry() -> None:
    pipeline = Pipeline(extractor_failures=1)
    document_id = await pipeline.submit()

    with pytest.raises(ProviderUnavailable):
        await pipeline.run_all()
    assert pipeline.status(document_id) is DocumentStatus.CLASSIFIED  # progress was kept

    await pipeline.analyze(document_id)  # what the worker does on retry

    assert pipeline.status(document_id) is DocumentStatus.ACCEPTED
    assert pipeline.extractor.calls == 2
