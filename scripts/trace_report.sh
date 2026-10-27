#!/usr/bin/env bash
# Draw the agent workflow of the latest processed document as an HTML report with AgentCanvas.
# Needs LOGFIRE_READ_TOKEN in config/.env, and the service run with DOCINTEL_LOGFIRE_TOKEN set.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
. config/.env
set +a
uv run agentcanvas -o docs/assets/trace-report.html --no-open "$@"
echo "report: docs/assets/trace-report.html"
