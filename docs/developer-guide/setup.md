# Setup

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker Compose.

```bash
uv sync                                  # install dependencies
cp config/.env.example config/.env       # local settings
docker compose -f docker/docker-compose.yml up -d postgres   # (scripts/up.sh also starts MinIO)
scripts/check.sh                         # all quality gates
uv run fastapi dev src/docintel/main.py  # run the API
```

Migrations (from M3 on):

```bash
uv run alembic -c alembic/docintel/alembic.ini revision --autogenerate -m "describe change"
uv run alembic -c alembic/docintel/alembic.ini upgrade head
```

## Try it end to end

```bash
docker compose -f docker/docker-compose.yml up -d postgres
uv run alembic -c alembic/docintel/alembic.ini upgrade head
python src/docintel/main.py          # API plus the embedded worker on http://127.0.0.1:8000
```

Then open the `bruno/` folder as a collection in Bruno and run it in order (01 to 10), or run it headless:

```bash
cd bruno && npx @usebruno/cli run --env local
```

The status requests poll until processing settles. With the free NVIDIA tier a full run takes about five minutes.

Set `DOCINTEL_NVIDIA_API_KEY` in `config/.env` (a free key from build.nvidia.com).

## See the agent workflow (AgentCanvas)

[AgentCanvas](https://github.com/vstorm-co/agentcanvas) draws what the AI did for one document as a single HTML file: the classify and extract calls, the prompts and replies, and the tokens and cost of each step. It reads traces from [Pydantic Logfire](https://logfire.pydantic.dev) (free tier), so you need two tokens from a Logfire project:

| Token | Where it goes | Purpose |
| --- | --- | --- |
| Write token | `DOCINTEL_LOGFIRE_TOKEN` in `config/.env` | The service sends one trace per document (off while empty) |
| Read token | `LOGFIRE_READ_TOKEN` in `config/.env` | AgentCanvas reads the traces back (for the EU region also set `LOGFIRE_BASE_URL`) |

Then process a document and build the report:

```bash
python src/docintel/main.py                 # with DOCINTEL_LOGFIRE_TOKEN set
# upload a sample document, wait for it to finish, then:
scripts/trace_report.sh                     # writes docs/assets/trace-report.html
scripts/trace_report.sh --list              # recent runs; use --trace-id <id> for a specific one
```

Tracing sends prompts and document text to Logfire. Use the synthetic files in `assets/Examples/`, never real customer documents.
