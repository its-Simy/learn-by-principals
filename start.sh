#!/usr/bin/env bash
# Start BrightLearn:  ./start.sh [--port 8765] [--no-open]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
. scripts/env.sh
command -v uv >/dev/null 2>&1 || fail "uv is not installed: run ./setup.sh first"
[ -x "$UV_PROJECT_ENVIRONMENT/bin/python" ] || fail "no Python environment yet: run ./setup.sh first"
exec uv run --no-sync brightlearn start "$@"
