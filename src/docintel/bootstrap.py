"""Composition root: the only file that knows which concrete classes are used."""

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from docintel.config import Settings
from docintel.models.values import DocumentType
from docintel.shared.messaging import EventHandler, JobStore, build_event_handlers
from docintel.shared.ports import (
    BlobStore,
    Classifier,
    DocumentParser,
    Extractor,
    Telemetry,
    UnitOfWork,
)
from docintel.shared.queries import Queries
from docintel.shared.use_cases.create_case import CreateCase
from docintel.shared.use_cases.fail_document import FailDocument
from docintel.shared.use_cases.process_document import (
    AnalyzeDocument,
    ParseDocument,
    StartAnalysis,
)
from docintel.shared.use_cases.submit_document import SubmitDocument
from docintel.utils.providers.db.queries import SqlQueries
from docintel.utils.providers.db.unit_of_work import SqlUnitOfWork
from docintel.utils.providers.parsing import make_parser
from docintel.utils.providers.queue.sql_job_store import SqlJobStore
from docintel.utils.providers.storage import make_blob_store
from docintel.utils.tracking.telemetry import LogTelemetry

LlmComponents = tuple[Classifier, Mapping[DocumentType, Extractor]]


class _LlmFactory(Protocol):
    def __call__(self, settings: Settings, telemetry: Telemetry) -> LlmComponents: ...


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    uow_factory: Callable[[], UnitOfWork]
    blobs: BlobStore
    queries: Queries
    job_store: JobStore
    create_case: CreateCase
    submit_document: SubmitDocument
    start_analysis: StartAnalysis
    parse_document: ParseDocument
    analyze_document: AnalyzeDocument | None
    fail_document: FailDocument
    event_handlers: dict[str, list[EventHandler]]


def _load_llm_components(settings: Settings, telemetry: Telemetry) -> LlmComponents | None:
    """Build the LLM adapters, or None if that package is not available yet."""
    try:
        module = importlib.import_module("docintel.utils.providers.llm")
        factory = cast(_LlmFactory, module.make_llm_components)
    except (ImportError, AttributeError):
        return None
    return factory(settings, telemetry)


def build_container(
    settings: Settings,
    *,
    parser: DocumentParser | None = None,
    llm: LlmComponents | None = None,
    blobs: BlobStore | None = None,
) -> Container:
    """Wire adapters into use cases. Tests inject fakes through the keyword arguments."""
    engine = create_async_engine(settings.database_url, pool_size=10, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def uow_factory() -> SqlUnitOfWork:
        return SqlUnitOfWork(sessions)

    telemetry = LogTelemetry()
    blob_store = blobs or make_blob_store(settings)
    document_parser = parser or make_parser(settings)
    components = llm or _load_llm_components(settings, telemetry)
    start_analysis = StartAnalysis(uow_factory)
    analyze = (
        AnalyzeDocument(uow_factory, blob_store, components[0], components[1], telemetry)
        if components
        else None
    )
    return Container(
        settings=settings,
        engine=engine,
        sessions=sessions,
        uow_factory=uow_factory,
        blobs=blob_store,
        queries=SqlQueries(sessions),
        job_store=SqlJobStore(sessions),
        create_case=CreateCase(uow_factory),
        submit_document=SubmitDocument(uow_factory, blob_store),
        start_analysis=start_analysis,
        parse_document=ParseDocument(uow_factory, blob_store, document_parser, telemetry),
        analyze_document=analyze,
        fail_document=FailDocument(uow_factory),
        event_handlers=build_event_handlers(uow_factory, start_analysis),
    )
