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
