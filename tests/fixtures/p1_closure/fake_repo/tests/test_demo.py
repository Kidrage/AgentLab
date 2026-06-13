"""Tests for the P1 acceptance fake repository.

These tests are fixture content only. AgentLab's CodeGraph acceptance path
should inspect the checkout shape in dry-run/status mode, not execute this
test suite as an external provider workload.
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_runtime.demo import add


def test_add() -> None:
    assert add(2, 3) == 5


def test_add_negative_values() -> None:
    assert add(-2, -3) == -5
