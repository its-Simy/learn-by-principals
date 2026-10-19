# Shared by setup.sh, start.sh and BrightLearn.command: what the shell must own before uv runs.
# Sourced, never executed; bash 3.2 (macOS) compatible.

say() { printf '%s\n' "$*" >&2; }
fail() { say "error: $*"; exit 1; }

# User-local installs land here; a Finder-launched .command gets launchd's PATH only.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
case "$(uname -s)" in
  Darwin) : "${PNPM_HOME:=$HOME/Library/pnpm}" ;;
  *) : "${PNPM_HOME:=$HOME/.local/share/pnpm}" ;;
esac
export PNPM_HOME
export PATH="$PNPM_HOME:$PATH"

# The environment's Python is uv's own 3.12 (.python-version), never conda's or Homebrew's.
export UV_MANAGED_PYTHON=1
export PYTHONUTF8=1

# macOS: is this folder synced by iCloud? iCloud re-hides files inside dot-folders, Python 3.12
# then skips the environment's .pth file, and the `brightlearn` command stops importing.
in_icloud() {
  [ "$(uname -s)" = Darwin ] || return 1
  case "$PWD" in "$HOME/Library/Mobile Documents/"*) return 0 ;; esac
  local d="$PWD" attr
  while [ -n "$d" ] && [ "$d" != "/" ]; do
    for attr in com.apple.file-provider-domain-id com.apple.icloud.desktop com.apple.icloud.documents; do
      xattr -p "$attr" "$d" >/dev/null 2>&1 && return 0
    done
    d=$(dirname "$d")
  done
  return 1
}

# Where the Python environment lives: an explicit UV_PROJECT_ENVIRONMENT, else what an earlier
# run linked .venv to, else outside the repo when iCloud syncs it, else ./.venv.
venv_dir() {
  local target
  if [ -n "${UV_PROJECT_ENVIRONMENT:-}" ]; then
    printf '%s\n' "$UV_PROJECT_ENVIRONMENT"
  elif [ -L .venv ]; then
    target=$(readlink .venv)
    case "$target" in /*) ;; *) target="$PWD/$target" ;; esac
    printf '%s\n' "$target"
  elif in_icloud; then
    printf '%s\n' "$HOME/.venvs/$(basename "$PWD")"
  else
    printf '%s\n' "$PWD/.venv"
  fi
}
UV_PROJECT_ENVIRONMENT="$(venv_dir)"
export UV_PROJECT_ENVIRONMENT
