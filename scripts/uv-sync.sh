#!/usr/bin/env bash
# Sync deps with uv. On external/USB volumes, use --local-venv so the env lives on APFS
# (fixes AppleDouble `._*` errors like `._vba_extract.py` during wheel install).
#
# Usage:
#   ./scripts/uv-sync.sh --all-extras
#   ./scripts/uv-sync.sh --local-venv --all-extras    # recommended on "Leo Disk" etc.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export UV_LINK_MODE="${UV_LINK_MODE:-copy}"
# Reduce AppleDouble / resource-fork files during copies (helps some macOS + external volume installs).
if [[ "$(uname -s)" == "Darwin" ]]; then
  export COPYFILE_DISABLE="${COPYFILE_DISABLE:-1}"
fi

ARGS=()
USE_LOCAL_VENV=0
for arg in "$@"; do
  if [[ "$arg" == "--local-venv" ]]; then
    USE_LOCAL_VENV=1
  else
    ARGS+=("$arg")
  fi
done

if [[ "$USE_LOCAL_VENV" -eq 1 ]]; then
  NAME="$(basename "$ROOT")"
  export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.venvs/$NAME}"
  mkdir -p "$(dirname "$UV_PROJECT_ENVIRONMENT")"
  echo "uv: using project environment at $UV_PROJECT_ENVIRONMENT (APFS/local disk)" >&2
  # Stale .venv on the external volume is ignored once UV_PROJECT_ENVIRONMENT is set.
fi

exec uv sync "${ARGS[@]}"
