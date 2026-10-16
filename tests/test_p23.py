"""P23 tests (T411-T430): release gates. No weights."""
import sys

sys.path.insert(0, "src")

import pytest

from gatekeeper.cli import main


def test_all_subcommand_helps():  # T414
    for cmd in (["check", "--help"], ["serve", "--help"], ["demo", "--help"],
                ["watch", "--help"], ["review", "--help"], ["stats", "--help"],
                ["export", "--help"], ["pack", "--help"]):
        with pytest.raises(SystemExit) as ei:
            main(cmd)
        assert ei.value.code == 0, cmd
