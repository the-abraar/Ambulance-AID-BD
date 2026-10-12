#!/usr/bin/env bash
# Fail on interpolation/concatenation into HTML sinks unless the line ends with `// safe-html: <reason>`.
cd "$(dirname "$0")/.."
hits=$(grep -rnE --include='*.js' --include='*.jsx' --include='*.tsx' --include='*.html' \
  --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git --exclude-dir=dist --exclude-dir=build \
  '(innerHTML|outerHTML|insertAdjacentHTML|document\.write|dangerouslySetInnerHTML)[^/]*(\$\{|\+)' . \
  | grep -vE '//[[:space:]]*safe-html:' || true)
[ -z "$hits" ] || { echo "unsafe HTML sinks (add '// safe-html: <reason>' only if escaped):"; echo "$hits"; exit 1; }
