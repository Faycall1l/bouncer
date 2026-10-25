"""T967: suite wall-time budget — no test over 1s without written justification.

Every test's full protocol (setup + call + teardown) is timed. Anything
over 1s must appear in SLOW_JUSTIFIED with a written reason; otherwise
the session ends nonzero after the summary lists the offenders. The
justified ones print their real time as a receipt, per the house rule
that timing numbers are printed, never asserted.

T969: shared CI runners + --cov instrumentation measure sub-second local
tests at 1.0-1.7s, so CI enforces a 5s backstop (same offender list,
same table) while verify.sh's local run keeps the strict 1s — the box's
gate is where contributors run it, and CI absorbs runner variance.
"""
import os
import time

import pytest

CI_BUDGET_S = 5.0

# name -> written justification. Editing this table IS the process: an
# entry only lands here with a sentence on why the test needs >1s.
SLOW_JUSTIFIED: dict[str, str] = {
    "test_ci_eval_gate_job_replays_weightless":
        "replays the CI eval-gate job as a real subprocess "
        "(gate.py --all --ci over a freshly generated weightless report set)",
    "test_t957_no_dead_public_code_in_src":
        "P50 dead-code sweep AST-parses every source file and "
        "cross-references every public symbol — O(repo), not O(one test)",
    "test_gate_pool_speedup_hits_scenario":
        "runs the real bench_pool.py end-to-end then gates its report — "
        "a timing benchmark that only means something if it does the work",
    "test_ci_benchmark_job_posts_summary":
        "replays the CI bench job as a subprocess (bench_stub + bench_pool, "
        "the same two runners CI invokes in its summary step)",
    "test_bench_pool_measures_mixed_language_thrash":
        "measures mixed-language pool thrash by running the multilingual "
        "deployment itself — the measurement IS the wall time",
    "test_packaging_smoke_release_tree":
        "builds a real wheel AND sdist and installs the wheel into a throwaway "
        "env — two package builds cannot fit in a second",
    "test_pool_bench_weightless":
        "runs bench_pool.py with an eviction demo (6 requests, pool of 2) — "
        "naive-vs-pooled timing needs real elapsed time",
    "test_systemone_safe_path_timeout_retry_breaker":
        "drives the passthrough through real timeout → retry → breaker paths; "
        "the waits are the behaviour under test",
    "test_batch_shares_one_deadline":
        "proves one shared deadline across a batch by elapsing real time — "
        "a timing contract cannot be faked with a clock stub",
    "test_pip_install_produces_working_bouncer":
        "pip-installs the freshly built wheel into a throwaway env and runs "
        "the console script from it — a real package install lives near 1s",
    "test_container_entrypoint_runs_self_test":
        "exercises the shell entrypoint as real subprocesses (sh -n syntax "
        "check plus six stubbed runs handing off to CMD) — spawn-heavy: "
        "sub-second idle, but shared machine load has measured it to 3s",
    "test_compose_snapshot_volumes_and_secrets":
        "validates compose.yaml through the real docker compose parser when "
        "the CLI is present (T717) — 0.24s idle with docker, but shared "
        "runner load has measured 5.8–11.7s (four CI legs, release push "
        "window 2026-10-22)",
    "test_ci_coverage_job_posts_number":
        "replays the CI coverage job as a subprocess — pytest --cov over "
        "test_cli.py, the same wiring the coverage leg runs; sub-second on "
        "the idle gates it landed under 2026-10-22, 2.18s when loaded",
    "test_gate_breaker_trips_and_closes":
        "spawns a real breaker sim with a 0.2s cool window plus four gate "
        "subprocesses for T682's both-true-or-broken checks — spawn-heavy "
        "like the entrypoint test: sub-second on the gates it landed "
        "under, 1.15s when the machine is loaded",
    "test_graceful_shutdown_drains_and_flushes":
        "drives the FastAPI lifespan directly; the drain/flush logic under "
        "test is sub-second, but startup warmup is environment-dependent "
        "(T849's note) and lands at 11-17s on CI runners with "
        "huggingface/laya present",
    "test_t991_versioned_docs_build_script_per_tag_snapshot":
        "spawns the docs-build CLI four times and builds a throwaway git "
        "repo (commits, lightweight + annotated tags) — spawn-heavy like "
        "the entrypoint test: sub-second idle, machine load has measured "
        "it near 2s",
    "test_t991_snapshot_build_strict_where_mkdocs_exists":
        "runs a real strict mkdocs-material build of the whole docs site "
        "into a per-tag dir — a full site build cannot fit in a second "
        "(and it skips itself where mkdocs is absent)",
    "test_wheel_builds_clean":
        "runs a real uv build and inspects the wheel and sdist contents — "
        "subprocess packaging work that is sub-second idle, but shared "
        "machine load has measured it past 1s (T991: 1.15s at load 2-3)",
    "test_p40_perf_sweep_weightless":
        "runs the real weightless perf sweep over generated reports — the "
        "sweep's subject IS wall time, so its own duration tracks machine "
        "load (T991: 1.43s at load 2-3)",
}

_overshoot: list[tuple[str, float]] = []
_justified_seen: list[tuple[str, float]] = []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    budget = CI_BUDGET_S if os.environ.get("CI") else 1.0
    start = time.perf_counter()
    yield
    took = time.perf_counter() - start
    if took > budget:
        if item.name in SLOW_JUSTIFIED:
            _justified_seen.append((item.nodeid, took))
        else:
            _overshoot.append((item.nodeid, took))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    tr = terminalreporter
    budget = CI_BUDGET_S if os.environ.get("CI") else 1.0
    if _justified_seen:
        tr.write_sep("=", "T967 slow tests (justified, receipt)")
        for nodeid, took in sorted(_justified_seen, key=lambda x: -x[1]):
            tr.write_line(f"  {took:6.2f}s  {nodeid}")
    if _overshoot:
        tr.write_sep("=", f"T967 WALL-TIME BUDGET EXCEEDED ({budget:g}s per test)")
        for nodeid, took in sorted(_overshoot, key=lambda x: -x[1]):
            tr.write_line(f"  {took:6.2f}s  {nodeid}")
        tr.write_line("  justify it in tests/conftest.py SLOW_JUSTIFIED "
                      "or make the test faster")


def pytest_sessionfinish(session, exitstatus):
    if _overshoot:
        session.exitstatus = 1
