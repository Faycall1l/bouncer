#!/bin/sh
# Verify gate (T404, documented in CONTRIBUTING T804): green tests +
# clean lint, then one box = one commit + push. Stops at the first red —
# never push red; fix forward instead.
# usage: ./verify.sh "T### what this commit does"
set -u
[ $# -eq 1 ] || { echo 'usage: $0 "T### message"' >&2; exit 64; }

python -m pytest -q || exit 1
ruff check . || exit 1

git add -A || exit 1
git commit -m "$1" || exit 1
git push origin HEAD || exit 1
