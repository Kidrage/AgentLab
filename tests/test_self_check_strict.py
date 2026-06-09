from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import rule_self_check
import run_task


class StrictSelfCheckTests(TestCase):
    def test_strict_warning_becomes_blocking_reason(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            changed_file = root / "agent_runtime" / "demo.py"
            changed_file.parent.mkdir(parents=True)
            changed_file.write_text("x = 1\n", encoding="utf-8")

            def fake_run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
                if cmd[:2] == ["git", "rev-parse"]:
                    return 0, "true\n", ""
                if cmd[:2] == ["git", "status"]:
                    return 0, " M agent_runtime/demo.py\n", ""
                if cmd[:2] == ["git", "diff"]:
                    return 0, "", ""
                if cmd[1:3] == ["-m", "py_compile"]:
                    return 0, "", ""
                return 0, "", ""

            with patch.object(rule_self_check, "_run", side_effect=fake_run):
                report = rule_self_check.run_self_check(root, "Demo", "task_0001", strict=True)

            self.assertEqual(report["status"], "fail")
            self.assertFalse(report["auto_sync_eligible"])
            self.assertIn("No implementation report for code changes.", report["blocking_reasons"])

    def test_check_cli_exits_nonzero_on_fail(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            def fake_self_check(*args, **kwargs) -> dict:
                return {
                    "status": "fail",
                    "summary": {"passed": 0, "warnings": 1, "failed": 0},
                    "checks": [
                        {
                            "id": "report_completeness",
                            "status": "warn",
                            "message": "No implementation report for code changes.",
                        }
                    ],
                    "blocking_reasons": ["No implementation report for code changes."],
                    "auto_sync_eligible": False,
                }

            with patch.object(run_task, "runtime_context", return_value=(root, "Demo")):
                with patch.object(rule_self_check, "run_self_check", side_effect=fake_self_check):
                    result = runner.invoke(
                        run_task.app,
                        ["check", "--project", "Demo", "--task-id", "task_0001", "--strict"],
                    )

            self.assertEqual(result.exit_code, 1)
            self.assertIn("Self-Check", result.output)


if __name__ == "__main__":
    main()
