#!/bin/sh
# T719: container self-test — the CLI must run and the engine must answer
# before uvicorn accepts any traffic. Exit 0 (allow) or 3 (escalate: the
# engine answered, model degraded — the same tolerance the server has,
# T512/T513) passes; anything else kills the boot. Then hand off to CMD.
set -e
rc=0
bouncer check "container self-test" --preset "${BOUNCER_PRESET:-gaming}" --quiet || rc=$?
case "$rc" in
  0|3) ;;
  *) echo "bouncer: self-test failed (exit $rc)" >&2; exit 1 ;;
esac
exec "$@"
