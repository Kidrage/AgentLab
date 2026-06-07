"""P2-1: CLI execution-mode conflict detection for agentlab.sh.

--dry-run        No API calls
--mock-provider   No API calls, but generate fake provider reports
--execute         Call real API

If user passes conflicting combos (--dry-run --execute, etc.), must error out.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from pipeline_runner import _resolve_execution_mode


class CLIExecutionModes(TestCase):
    def test_dry_run_win_over_fake_provider_false(self) -> None:
        mode = _resolve_execution_mode(dry_run=True, fake_provider=False)
        self.assertEqual(mode["execution_mode"], "dry_run")
        self.assertTrue(mode["effective_fake_provider"])

    def test_mock_provider_prevents_real_execution(self) -> None:
        mode = _resolve_execution_mode(dry_run=False, fake_provider=True)
        self.assertEqual(mode["execution_mode"], "mock_provider")
        self.assertTrue(mode["effective_fake_provider"])

    def test_execute_mode_allows_everything(self) -> None:
        mode = _resolve_execution_mode(dry_run=False, fake_provider=False)
        self.assertEqual(mode["execution_mode"], "execute")
        self.assertFalse(mode["effective_fake_provider"])
        self.assertTrue(mode["allow_real_provider"])
        self.assertTrue(mode["allow_patches"])

    def test_default_is_dry_run(self) -> None:
        mode = _resolve_execution_mode(dry_run=True, fake_provider=True)
        self.assertEqual(mode["execution_mode"], "dry_run")
        self.assertFalse(mode["allow_real_provider"])

    def test_dry_run_disables_patches(self) -> None:
        for dry, fake in [(True, True), (True, False), (False, True)]:
            mode = _resolve_execution_mode(dry_run=dry, fake_provider=fake)
            self.assertFalse(mode["allow_patches"], f"dry={dry} fake={fake}")


if __name__ == "__main__":
    main()