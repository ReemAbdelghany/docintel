#!/usr/bin/env bash
# Start local dependencies: Postgres, MinIO, Jaeger.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose -f docker/docker-compose.yml up -d
