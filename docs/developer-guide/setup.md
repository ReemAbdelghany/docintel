# Setup

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker Compose.

```bash
uv sync                                  # install dependencies
cp config/.env.example config/.env       # local settings
scripts/up.sh                            # Postgres, MinIO, Jaeger
scripts/check.sh                         # all quality gates
uv run fastapi dev src/docintel/main.py  # run the API
```

Migrations (from M3 on):

```bash
uv run alembic -c alembic/docintel/alembic.ini revision --autogenerate -m "describe change"
uv run alembic -c alembic/docintel/alembic.ini upgrade head
```
