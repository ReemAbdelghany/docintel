#!/usr/bin/env bash
# Run every quality gate. Same commands CI runs.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
