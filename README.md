# Document Intelligence Service

Upload a PDF or an image of a contract or an invoice and get structured, verified data back. Each document is parsed, classified, extracted, checked against its own text and business rules, and then **accepted**, **rejected**, or routed to **manual review** when the system cannot be confident.

## Quick start

Requirements: Python 3.12+, `uv`, Docker, and a free NVIDIA API key (build.nvidia.com).

```bash
uv sync
cp config/.env.example config/.env          # add DOCINTEL_NVIDIA_API_KEY
docker compose -f docker/docker-compose.yml up -d postgres
uv run alembic -c alembic/docintel/alembic.ini upgrade head
python src/docintel/main.py                 # http://127.0.0.1:8000/docs
```

## API (`/v1alpha1`)

| Endpoint | Purpose |
| --- | --- |
| `POST /cases` | Create an onboarding case |
| `POST /cases/{id}/documents` | Upload a PDF or image; processing runs in the background (202) |
| `GET /documents/{id}` | Status, decision, reason, extracted facts and evidence |
| `GET /cases/{id}/documents`, `POST /documents/{id}/reprocess` | For testing |

Open the `bruno/` folder in Bruno and run the numbered requests in order (or `cd bruno && npx @usebruno/cli run --env local`).

## Outcomes

- **accepted**: classified with confidence, required facts present and found in the document, business rules pass.
- **rejected**: not an invoice or contract, or it breaks a rule (for example the total does not match subtotal plus tax).
- **needs_review**: parsing or classification failed or was unsure, extraction failed, or a value cannot be traced to the document.

## Swappable by configuration

| Capability | Setting | Options |
| --- | --- | --- |
| Storage | `DOCINTEL_STORAGE_BACKEND` | `local` (default), `s3` |
| LLM | `DOCINTEL_LLM_MODEL` | `nim:<model>` (default), `openai-compatible:<model>`, or any Pydantic AI model string |

**See what the AI did:** [`docs/assets/trace-report.html`](docs/assets/trace-report.html) is an AgentCanvas report for one synthetic invoice (open it in a browser): the classify and extract calls, the prompts and replies, and the tokens per step. Regenerate it with `scripts/trace_report.sh` (see the setup guide).

See the [architecture](docs/developer-guide/architecture.md) and the ADRs in `docs/developer-guide/adr/`. Run the quality gates with `scripts/check.sh`.
