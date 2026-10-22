#!/usr/bin/env python3
"""T991: versioned docs build — one git ref, one site snapshot.

    python scripts/build_docs_version.py v0.4.0 [--site-dir site]

Takes the ref's own mkdocs.yml + docs/ out of git (git archive — the
tag's bytes, never the working tree), verifies that tree is a buildable
docs site, then runs a strict mkdocs build of THAT tree into
<site-dir>/<ref>/, so a release's docs stay reachable beside the
current site. Each snapshot is mkdocs's own site-dir: building a tag
cleans only <site-dir>/<ref>/, never its neighbours — CI builds the
root site first, then the tags (T992).

Refs from before the docs era (every tag before v0.4.0) fail with a
clear message instead of shipping a broken half-site: there is nothing
to snapshot. mkdocs must be importable in the invoking interpreter —
mkdocs-material carries the pymdownx extensions mkdocs.yml names, and
the docs workflow installs it. The repository is never mutated: no
worktree, no checkout, no stash — extraction goes to a temp directory.

Exit 2 on usage errors, 1 on an unknown or unbuildable ref or a failed
build, 0 on success (printing the resolved sha and the snapshot dir).
Stdlib only for everything except the mkdocs build itself.
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

# exactly what a snapshot needs from the ref — nothing else ships
_TREE = ("mkdocs.yml", "docs")


def resolve_ref(ref: str) -> str:
    """Full commit sha for ref (annotated-tag safe); exit 1 if unknown."""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        check=False, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        print(f"bouncer-docs: unknown ref {ref!r} — nothing to snapshot",
              file=sys.stderr)
        raise SystemExit(1)
    return proc.stdout.strip()


def extract_snapshot(ref: str, dest: Path) -> str:
    """Archive the ref's mkdocs.yml + docs/ into dest; returns its sha.

    The bytes come from git at that commit — a snapshot of an old tag
    can never pick up an edited working tree, and no checkout runs.
    """
    sha = resolve_ref(ref)
    # docs-era check BEFORE archiving: git archive dies on unmatched
    # pathspecs, and its error would be a raw traceback instead of the
    # honest reason (every tag before v0.4.0 lands here)
    absent = [f for f in _TREE
              if subprocess.run(["git", "cat-file", "-e", f"{sha}:{f}"],
                                check=False,
                                capture_output=True).returncode != 0]
    if absent:
        print(f"bouncer-docs: {ref} has no {', '.join(absent)} — docs did "
              "not exist at this ref; snapshot needs v0.4.0 or newer",
              file=sys.stderr)
        raise SystemExit(1)
    proc = subprocess.run(
        ["git", "archive", "--format=tar", sha, "--", *_TREE],
        check=False, capture_output=True)
    if proc.returncode != 0:
        print(f"bouncer-docs: git archive failed for {ref}: "
              f"{proc.stderr.decode(errors='replace').strip()}",
              file=sys.stderr)
        raise SystemExit(1)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tf:
        try:
            tf.extractall(dest, filter="data")  # py3.12+ (backported)
        except TypeError:  # very old 3.10/3.11 patch level: no filter
            tf.extractall(dest)
    return sha


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="build_docs_version.py",
        description="build one git ref's docs into <site-dir>/<ref>/")
    ap.add_argument("ref", help="git ref to snapshot (a tag, e.g. v0.4.0)")
    ap.add_argument("--site-dir", default="site",
                    help="built-site root; the snapshot lands in "
                         "<site-dir>/<ref> (default: site)")
    args = ap.parse_args(argv)
    out = Path(args.site_dir) / args.ref
    with tempfile.TemporaryDirectory(prefix="bouncer-docs-") as td:
        src = Path(td)
        sha = extract_snapshot(args.ref, src)
        out.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [sys.executable, "-m", "mkdocs", "build", "--strict",
             "--config-file", str(src / "mkdocs.yml"),
             # inherit mkdocs' output stream for CI logs
             "--site-dir", str(out.resolve())], check=False)
        if proc.returncode != 0:
            print("bouncer-docs: mkdocs build failed — install "
                  "mkdocs-material in the invoking interpreter",
                  file=sys.stderr)
            return 1
    print(f"bouncer-docs: {args.ref} ({sha[:10]}) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
