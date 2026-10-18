#!/usr/bin/env bash
# One-command setup for macOS and Linux. Safe to run again: finished steps are skipped.
#
#   ./setup.sh [--dev] [--yes] [--skip-login] [--account EMAIL] [--browser chrome|msedge]
#
# It installs uv (which brings Python 3.12), pnpm and Node when they are missing, the Python
# packages from uv.lock, and builds the web app; `brightlearn setup` then makes the home folder,
# logs in to NotebookLM (opens your browser) and reports the optional model CLIs. --dev also
# installs pytest and ruff; every other argument goes to `brightlearn setup`.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
. scripts/env.sh
trap 'say ""; say "setup.sh: the step above failed. Fix it and run ./setup.sh again; finished steps are skipped."' ERR

DEV=0
YES=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --dev) DEV=1 ;;
    --yes | -y) YES=1; ARGS+=("$a") ;;
    *) ARGS+=("$a") ;;
  esac
done

step() { say ""; say "==> $*"; }
confirm() {
  [ "$YES" = 1 ] && return 0
  printf '%s [Y/n] ' "$1" >&2
  read -r answer
  case "$answer" in n | N | no | NO) return 1 ;; *) return 0 ;; esac
}

# 1. uv: the official installer when it is missing or too old to know --managed-python.
if ! command -v uv >/dev/null 2>&1 || ! uv sync --help 2>/dev/null | grep -q -- --managed-python; then
  step "Installing uv (user-local, from astral.sh)"
  confirm "Install uv?" || fail "uv is required: https://docs.astral.sh/uv/"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
say "uv: $(uv --version)"

# 2. Where the Python environment lives (scripts/env.sh decided).
if [ "$UV_PROJECT_ENVIRONMENT" != "$PWD/.venv" ]; then
  mkdir -p "$(dirname "$UV_PROJECT_ENVIRONMENT")"
  if [ -d .venv ] && [ ! -L .venv ] && [ -f .venv/pyvenv.cfg ]; then rm -rf .venv; fi
  ln -sfn "$UV_PROJECT_ENVIRONMENT" .venv
  say "Python env: $UV_PROJECT_ENVIRONMENT (outside this iCloud-synced folder; .venv links to it)"
fi

# 3. pnpm, and Node 22.12 or newer (what the web build needs).
if ! command -v pnpm >/dev/null 2>&1; then
  step "Installing pnpm (user-local, from get.pnpm.io)"
  confirm "Install pnpm?" || fail "pnpm is required: https://pnpm.io/installation"
  curl -fsSL https://get.pnpm.io/install.sh | sh -
fi
node_ok() {
  node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>22||(a===22&&b>=12)?0:1)' 2>/dev/null
}
if ! command -v node >/dev/null 2>&1 || ! node_ok; then
  step "Installing Node LTS with pnpm"
  confirm "Install Node LTS?" || fail "Node 22.12 or newer is required: https://nodejs.org/"
  pnpm env use --global lts
fi
say "pnpm $(pnpm --version), node $(node --version)"

# 4. Python packages, exactly as uv.lock says (uv downloads Python 3.12 the first time).
step "Python environment"
if [ "$DEV" = 1 ]; then uv sync --locked; else uv sync --locked --no-dev; fi

# 5. The web app.
step "Web app"
pnpm --dir web install --frozen-lockfile
pnpm --dir web build

# 6. Home folder, NotebookLM login, optional model CLIs, doctor.
step "brightlearn setup"
uv run --no-sync brightlearn setup ${ARGS[@]+"${ARGS[@]}"}
