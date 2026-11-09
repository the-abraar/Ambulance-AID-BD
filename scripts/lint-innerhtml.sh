#!/usr/bin/env bash
# Fail on every HTML sink, and on a raw object field (`${obj.field}`) in a template that holds markup,
# unless the line carries `// safe-html: <reason>`. Usage: lint-innerhtml.sh [dir] (default: the repo).
# vendor/ holds unmodified third-party code (minified Leaflet); it is pinned and reviewed by version, not linted.
# lint-fixtures/ holds the sink shapes that scripts/test-lint-innerhtml.sh expects this lint to report.
cd "$(dirname "$0")/.."
dir="${1:-.}"
sinks='innerHTML|outerHTML|insertAdjacentHTML|document\.write|dangerouslySetInnerHTML|srcdoc|setHTMLUnsafe|createContextualFragment|parseFromString|bindPopup|bindTooltip|divIcon'
rawfield='<[a-zA-Z/!].*\$\{[[:space:]]*[A-Za-z_$][A-Za-z0-9_$]*(\??\.[A-Za-z_$][A-Za-z0-9_$]*)+[[:space:]]*\}'
excl=(--exclude-dir=node_modules --exclude-dir=vendor --exclude-dir=.venv --exclude-dir=.git --exclude-dir=.claude
  --exclude-dir=dist --exclude-dir=build)
[ "$dir" = . ] && excl+=(--exclude-dir=lint-fixtures)
hits=$(grep -rnE --include='*.js' --include='*.jsx' --include='*.ts' --include='*.tsx' --include='*.html' "${excl[@]}" \
  "$sinks|$rawfield" "$dir" \
  | grep -vE '//[[:space:]]*safe-html:' \
  | grep -vE '^[^:]+:[0-9]+:[[:space:]]*(//|/?\*)' || true) # a comment that names a sink is not a sink
[ -z "$hits" ] || { echo "unsafe HTML sinks (add '// safe-html: <reason>' only if every value is escaped):"; echo "$hits"; exit 1; }
