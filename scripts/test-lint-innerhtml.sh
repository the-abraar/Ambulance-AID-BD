#!/usr/bin/env bash
# Self-check: lint-innerhtml.sh must report every line of lint-fixtures/sinks.js (one sink shape per line).
set -uo pipefail
cd "$(dirname "$0")/.."
f=scripts/lint-fixtures/sinks.js
out=$(scripts/lint-innerhtml.sh scripts/lint-fixtures) && { echo "lint passed on the sink fixture"; exit 1; }
missed=0
for n in $(seq 1 "$(wc -l < "$f")"); do
  grep -q "^$f:$n:" <<<"$out" || { echo "lint missed $f:$n: $(sed -n "${n}p" "$f")"; missed=1; }
done
exit $missed
