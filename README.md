# Document Intelligence Service

Upload a PDF or an image of a contract or an invoice and get structured, verified data back. Each document is parsed, classified, extracted, checked against its own text and business rules, and then **accepted**, **rejected**, or routed to **manual review** when the system cannot be confident.

**Core philosophy**: *Missing fact + review > confidently wrong value.*

---

## Why This Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.12+ | Best ML/LLM ecosystem (Docling, Pydantic AI), mature type system for strict mypy |
| API Framework | FastAPI | Native async, OpenAPI, DI, Pydantic integration |
| ORM | SQLModel | Single source of truth for DB + API models, SQLAlchemy 2.0 async |
| LLM Orchestration | Pydantic AI | Structured output via Pydantic, built-in retries/fallbacks, AgentCanvas tracing |
| Document Parsing | Docling | Best-in-class layout analysis + table extraction + OCR, runs locally |
| Validation | Pure Python rules | Deterministic, testable, **zero model calls** |
| Storage | Protocol + Local/S3 | Swappable backend, content-addressed (SHA-256), path-traversal safe |
| Observability | structlog + Logfire | JSON logs, distributed traces with token/cost |
| Config | Pydantic Settings | Type-safe, env-prefix, `.env`, `SecretStr` for secrets |
| Package Manager | uv | 10-100x faster than pip, lockfile, workspace support |
| Testing | pytest + pytest-asyncio | Async-native, fixtures, parametrize |

---

## Quick Start

Requirements: Python 3.12+, `uv`, Docker, and a free NVIDIA API key (build.nvidia.com).

```bash
uv sync
cp config/.env.example config/.env          # add DOCINTEL_NVIDIA_API_KEY
docker compose -f docker/docker-compose.yml up -d postgres
uv run alembic -c alembic/docintel/alembic.ini upgrade head
python src/docintel/main.py                 # http://127.0.0.1:8000/docs
```

---

## Architecture

```
POST /cases/{id}/documents (202 Accepted)
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  BACKGROUND TASK: process_document(document_id)             │
├─────────────────────────────────────────────────────────────┤
│  1. PARSE (Docling) — PDF/image → per-page text + OCR       │
│  2. CLASSIFY (LLM) — First 6000 chars → type + confidence   │
│  3. EXTRACT (LLM) — Full doc → InvoiceFacts/ContractFacts   │
│  4. VERIFY (Pure Python — rules.py)                         │
│     • locate_evidence: ground quotes to pages               │
│     • ground_by_value: repair missing quotes by value       │
│     • missing_facts: required fields present + grounded     │
│     • derive_contract_values: infer currency, total_value   │
│     • business_violations: totals match, dates ordered      │
│  5. DECIDE — uncertain→NEEDS_REVIEW, violations→REJECTED    │
│  6. PERSIST — JSONB columns for facts/evidence/findings     │
└─────────────────────────────────────────────────────────────┘
```

**Critical invariant**: `rules.py` makes **zero model calls**. All verification is deterministic Python.

---

## API (`/v1alpha1`)

| Endpoint | Purpose |
| --- | --- |
| `POST /cases` | Create an onboarding case |
| `POST /cases/{id}/documents` | Upload PDF/image; background processing (202) |
| `GET /documents/{id}` | Status, decision, reason, extracted facts, evidence |
| `GET /cases/{id}/documents` | List case documents (testing) |
| `POST /documents/{id}/reprocess` | Re-run pipeline (testing) |

Test with Bruno: `cd bruno && npx @usebruno/cli run --env local`

---

## Outcomes

| Status | Meaning |
|--------|---------|
| **accepted** | Confident classification, required facts present & grounded, business rules pass |
| **rejected** | Not invoice/contract, or breaks a rule (e.g., total ≠ subtotal + tax) |
| **needs_review** | Parsing/classification/extraction failed/unsure, or value not traceable to document |

---

## Development Cycle

```bash
# 1. Start infrastructure
docker compose -f docker/docker-compose.yml up -d postgres

# 2. Apply migrations
uv run alembic -c alembic/docintel/alembic.ini upgrade head

# 3. Run API (hot reload)
python src/docintel/main.py --reload

# 4. Quality gate (CI)
scripts/check.sh
#    ruff check && ruff format --check && mypy src && pytest

# 5. Generate migration after model changes
uv run alembic -c alembic/docintel/alembic.ini revision --autogenerate -m "describe change"
```

**Branch naming**: `<prefix>/issue-<number>-<slug>` (feature/, bug/, enabler/, docs/)

---

## Running Tests & Lint

```bash
# All quality gates
scripts/check.sh

# Individual
uv run ruff check
uv run ruff format --check
uv run mypy src
uv run pytest -v
```

---

## Observability & Tracing

```bash
# 1. Add Logfire token to config/.env
DOCINTEL_LOGFIRE_TOKEN=your_token_here

# 2. Process a document (via API or Bruno)

# 3. Generate trace report
scripts/trace_report.sh
# Output: docs/assets/trace-report.html
```

Shows: classify → extract timeline, prompts, responses, tokens, latency, cost per step.

---

## Swappable by Configuration

| Capability | Setting | Options |
| --- | --- | --- |
| Storage | `DOCINTEL_STORAGE_BACKEND` | `local` (default), `s3` |
| LLM | `DOCINTEL_LLM_MODEL` | `nim:<model>` (default), `openai-compatible:<model>`, any Pydantic AI model |

---

## Production Deployment

### Docker (Multi-stage)
```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY src/ src/
COPY alembic/ alembic/
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn", "docintel.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Terraform (AWS ECS Fargate + RDS)
- **Compute**: ECS Fargate service (2+ tasks, ALB)
- **Database**: RDS Postgres (managed, encrypted)
- **Secrets**: AWS Secrets Manager (DB URL, NVIDIA API key, Logfire token)
- **Storage**: S3 bucket (when `DOCINTEL_STORAGE_BACKEND=s3`)
- **CI/CD**: GitHub Actions → ECR → ECS rolling deploy + Alembic migration task

See `docs/developer-guide/architecture.md` and ADRs in `docs/developer-guide/adr/` for full details.
