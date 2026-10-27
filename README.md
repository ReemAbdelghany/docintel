# SME Document Intelligence Service

An auditable document-processing service for SME onboarding. It accepts business documents, extracts typed facts with page-level evidence, validates them deterministically, and routes doubtful results to human review.

The system prefers a missing fact and a review task over a confidently wrong value. The underwriting decision itself, reviewer authentication, and a full review UI are outside this project's scope.

## Quick start

Requirements: Python 3.12+, `uv`, and Docker Compose.

```bash
uv sync
cp config/.env.example config/.env
scripts/up.sh        # Postgres, MinIO, Jaeger
scripts/check.sh     # lint, types, architecture contracts, tests
```

The API entrypoint is `src/docintel/main.py`. Database migrations and the API/worker services are added in later milestones.

## Swappable by configuration

| Capability | Setting | Adapters |
| --- | --- | --- |
| Storage | `DOCINTEL_STORAGE_BACKEND` | `local` (default), `s3` (MinIO or AWS) |
| Parser | `DOCINTEL_PARSER_BACKEND` | `docling` (default), `unstructured` |
| LLM | `DOCINTEL_LLM_MODEL` | `nim:<model>` (NVIDIA NIM, default), `openai-compatible:<model>`, or any Pydantic AI model string |

## Project layout

```text
src/docintel/
  models/      # domain: framework-free dataclasses and rules
  shared/      # application: ports, use cases, composition root
  routers/     # API (versioned: v1alpha1)
  utils/       # providers (adapters), tracking, common helpers
tests/         # unit_tests, api_tests, backtesting (evals), stress_tests
alembic/  assets/  config/  docker/  docs/  scripts/
```

## Architecture

A modular monolith with dependencies pointing inward: `routers` and `utils/providers` depend on `shared`, which depends on `models`. Two import-linter contracts check this during `scripts/check.sh`.

The Postgres-backed job queue claims work with `FOR UPDATE SKIP LOCKED`. State changes and domain events are committed atomically; an outbox relay dispatches events at least once, so handlers are idempotent. See the [architecture guide](docs/developer-guide/architecture.md) and the [implementation guide](docs/developer-guide/explanation/implementation-guide.md).

## Development

```bash
scripts/check.sh
```

The implementation proceeds in milestones. M0 supplies the package layout, local dependencies, and architecture guardrails; later milestones add the domain, application workflow, persistence, parsing, extraction, review, and operations.
