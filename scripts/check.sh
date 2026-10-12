#!/usr/bin/env bash
# One command for all checks. `--fast` = lint + stray files only (pre-commit).
set -euo pipefail
cd "$(dirname "$0")/.."
FAST=0; [ "${1:-}" = "--fast" ] && FAST=1

PY="${PYTHON:-}"
[ -n "$PY" ] || PY=$(command -v python3.11 || command -v python3.12 || true)
[ -n "$PY" ] || { echo "Python 3.11 or 3.12 is required (set \$PYTHON); 3.14 breaks scipy and others." >&2; exit 1; }
VENV="${CHECK_VENV:-$HOME/.cache/Ambulance-AID-BD-check-venv}"
if [ ! -x "$VENV/bin/python" ]; then "$PY" -m venv "$VENV"; fi
"$VENV/bin/pip" install -q -r backend/requirements-dev.txt
export PATH="$VENV/bin:$PATH"

names=(); results=()
step() { # step <name> <command...>
  local n="$1"; shift
  echo "== $n"
  if "$@"; then results+=(pass); else results+=(FAIL); fi
  names+=("$n")
}
stray() { local f; f=$(find . \( -name node_modules -o -name .venv -o -name .git -o -name dist -o -name build \) -prune -o \
  \( -name '*-e' -o -name '*.orig' -o -name '*.rej' -o -name '*.bak' \) -type f -print); [ -z "$f" ] || { echo "$f"; return 1; }; }
jscheck() { find backend/web -name '*.js' -print0 | xargs -0 -n1 node --check; }
rev() { (cd backend && pytest $(ls tests/test_*.py | sort -r)); }

step lint ruff check backend
step stray-files stray
if [ "$FAST" = 0 ]; then
  step js-syntax jscheck
  step unsafe-html scripts/lint-innerhtml.sh
  step openapi openapi-spec-validator docs/api-spec/openapi.yaml
  step pytest bash -c 'cd backend && pytest'
  step pytest-reverse rev
fi

echo; printf '%-18s | %s\n' step result
fail=0
for i in "${!names[@]}"; do printf '%-18s | %s\n' "${names[$i]}" "${results[$i]}"; [ "${results[$i]}" = pass ] || fail=1; done
exit $fail
