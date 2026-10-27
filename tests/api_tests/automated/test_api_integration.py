"""Integration tests against a real Postgres started with testcontainers."""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from docintel.bootstrap import Container, build_container
from docintel.config import Settings
from docintel.main import create_app
from docintel.models.values import DocumentType
from docintel.shared import messaging
from docintel.shared.ports import DocumentParser
from tests.api_tests.automated.stubs import (
    CorruptParser,
    FlakyExtractor,
    StubClassifier,
    StubParser,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        os.environ["DOCINTEL_DATABASE_URL"] = url
        command.upgrade(Config("alembic/docintel/alembic.ini"), "head")  # also tests the migration
        yield url


@dataclass
class Scenario:
    extractor_failures: int = 0
    corrupt_parser: bool = False


class Harness:
    def __init__(
        self, client: httpx.AsyncClient, container: Container, extractor: FlakyExtractor
    ) -> None:
        self.client, self.container, self.extractor = client, container, extractor

    async def new_case(self) -> str:
        response = await self.client.post("/v1alpha1/cases")
        assert response.status_code == 201
        return str(response.json()["case_id"])

    async def upload(self, case_id: str, content: bytes = b"%PDF invoice") -> httpx.Response:
        return await self.client.post(
            f"/v1alpha1/cases/{case_id}/documents", files={"file": ("invoice.pdf", content)}
        )

    async def wait_for_status(self, document_id: str, status: str, seconds: float = 20) -> None:
        async with asyncio.timeout(seconds):
            while True:
                body = (await self.client.get(f"/v1alpha1/documents/{document_id}")).json()
                if body["status"] == status:
                    return
                await asyncio.sleep(0.05)

    async def count(self, sql: str) -> int:
        async with self.container.sessions() as session:
            return int((await session.execute(text(sql))).scalar_one())


async def reset_database(url: str) -> None:
    """Empty every table before the app (and its worker) starts, so no stale job is claimed."""
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE outbox, jobs, extractions, analyses, submitted_documents, cases CASCADE")
        )
    await engine.dispose()


async def run_harness(
    database_url: str, tmp_path: Path, scenario: Scenario
) -> AsyncIterator[Harness]:
    extractor = FlakyExtractor(fail_times=scenario.extractor_failures)
    parser: DocumentParser = CorruptParser() if scenario.corrupt_parser else StubParser()
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        llm_model="stub",
        classifier_model="stub",
        local_storage_path=tmp_path,
        poll_seconds=0.05,
        embedded_worker=True,
    )

    def factory(cfg: Settings) -> Container:
        return build_container(
            cfg,
            parser=parser,
            llm=(StubClassifier(), {DocumentType.INVOICE: extractor}),
        )

    await reset_database(database_url)
    app = create_app(settings, factory)
    async with app.router.lifespan_context(app):
        container: Container = app.state.container
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Harness(client, container, extractor)


@pytest.fixture
async def harness(database_url: str, tmp_path: Path) -> AsyncIterator[Harness]:
    async for h in run_harness(database_url, tmp_path, Scenario()):
        yield h


@pytest.fixture
async def corrupt_harness(database_url: str, tmp_path: Path) -> AsyncIterator[Harness]:
    async for h in run_harness(database_url, tmp_path, Scenario(corrupt_parser=True)):
        yield h


@pytest.fixture
async def flaky_harness(database_url: str, tmp_path: Path) -> AsyncIterator[Harness]:
    async for h in run_harness(database_url, tmp_path, Scenario(extractor_failures=2)):
        yield h


async def test_upload_stores_the_document_and_announces_it(harness: Harness) -> None:
    case_id = await harness.new_case()

    response = await harness.upload(case_id)

    assert response.status_code == 202
    assert response.json()["duplicate"] is False
    assert await harness.count("SELECT count(*) FROM submitted_documents") == 1
    assert (
        await harness.count("SELECT count(*) FROM outbox WHERE event_type='DocumentSubmitted'") == 1
    )


async def test_uploading_the_same_bytes_again_creates_nothing_new(harness: Harness) -> None:
    case_id = await harness.new_case()
    first = (await harness.upload(case_id)).json()

    second = (await harness.upload(case_id)).json()

    assert second["duplicate"] is True
    assert second["document_id"] == first["document_id"]
    assert await harness.count("SELECT count(*) FROM submitted_documents") == 1
    assert (
        await harness.count("SELECT count(*) FROM outbox WHERE event_type='DocumentSubmitted'") == 1
    )


async def test_the_pipeline_runs_by_itself_to_an_accepted_result(harness: Harness) -> None:
    case_id = await harness.new_case()
    document_id = (await harness.upload(case_id)).json()["document_id"]

    await harness.wait_for_status(document_id, "accepted")

    result = (await harness.client.get(f"/v1alpha1/documents/{document_id}/result")).json()
    assert result["facts"]["vendor_name"] == "Acme Supplies"
    assert result["facts"]["total"] == {"amount": "1150.00", "currency": "EGP"}
    assert {e["field"] for e in result["evidence"]} >= {"total", "vendor_name"}


async def test_unknown_ids_return_problem_details(harness: Harness) -> None:
    response = await harness.client.get("/v1alpha1/documents/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "urn:docintel:error:not_found"
    assert response.json()["correlation_id"]


async def test_readiness_reports_the_database(harness: Harness) -> None:
    response = await harness.client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["database"] == "up"


async def test_a_corrupt_document_ends_failed_with_a_dead_job_not_stuck(
    corrupt_harness: Harness,
) -> None:
    case_id = await corrupt_harness.new_case()
    document_id = (await corrupt_harness.upload(case_id)).json()["document_id"]

    await corrupt_harness.wait_for_status(document_id, "failed")

    assert await corrupt_harness.count("SELECT count(*) FROM jobs WHERE status='dead'") == 1


async def test_transient_provider_failures_are_retried_until_it_works(
    flaky_harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(messaging, "backoff", lambda attempt: 0.05)
    case_id = await flaky_harness.new_case()
    document_id = (await flaky_harness.upload(case_id)).json()["document_id"]

    await flaky_harness.wait_for_status(document_id, "accepted")

    assert flaky_harness.extractor.calls == 3
