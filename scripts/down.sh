#!/usr/bin/env bash
# Stop local dependencies.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose -f docker/docker-compose.yml down
