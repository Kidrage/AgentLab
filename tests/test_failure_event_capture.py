"""Tests for P2-I failure event capture."""

from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import datetime

import pytest

from agent_runtime.recovery import create_failure_event, FailureEvent


class TestFailureEventCapture:
    """Tests for failure event capture functionality."""

    def test_failure_event_from_command_result(self) -> None:
        """Test creating failure event from command execution results."""
        event = create_failure_event(
            task_id="task_0001",
            project="AgentLab",
            stage="pytest",
            command="python -m pytest tests/ -q",
            exit_code=1,
            stdout="running 5 tests...\n",
            stderr="tests/test_example.py FAILED\nAssertionError",
        )

        assert event.task_id == "task_0001"
        assert event.project == "AgentLab"
        assert event.stage == "pytest"
        assert event.command == "python -m pytest tests/ -q"
        assert event.exit_code == 1
        assert event.stdout_tail is not None
        assert "running 5 tests" in event.stdout_tail
        assert event.stderr_tail is not None
        assert "AssertionError" in event.stderr_tail
        assert event.created_at

    def test_failure_event_truncates_stdout_stderr(self) -> None:
        """Test that stdout/stderr are truncated to max length."""
        long_output = "x" * 10000
        event = create_failure_event(
            task_id="task_0001",
            project="AgentLab",
            stage="test",
            command="echo test",
            exit_code=1,
            stdout=long_output,
            stderr=long_output,
            stdout_tail_chars=5000,
            stderr_tail_chars=5000,
        )

        assert len(event.stdout_tail) <= 5000
        assert len(event.stderr_tail) <= 5000

    def test_failure_event_redacts_secrets(self) -> None:
        """Test that secrets are redacted from stdout/stderr."""
        event = create_failure_event(
            task_id="task_0001",
            project="AgentLab",
            stage="test",
            command="echo test",
            exit_code=1,
            stdout="API_KEY=sk-1234567890abcdef",
            stderr="error: secret=mysecret123",
        )

        # Redacted content should not contain raw secrets
        assert "sk-1234567890abcdef" not in event.stdout_tail or "[REDACTED" in event.stdout_tail
        assert "mysecret123" not in event.stderr_tail or "[REDACTED" in event.stderr_tail

    def test_failure_event_uses_relative_or_redacted_paths(self) -> None:
        """Test that absolute paths are handled appropriately."""
        paths = [
            "/".join(["", "Users", "testuser", "project", "artifacts", "output.txt"]),
            "logs/error.log",
            "/tmp/temp_file.json",
        ]

        event = create_failure_event(
            task_id="task_0001",
            project="AgentLab",
            stage="test",
            command="echo test",
            exit_code=1,
            artifact_paths=paths,
        )

        # Paths should either be preserved (for common roots) or redacted
        artifact_str = json.dumps(event.artifact_paths)
        # Not all paths need to be redacted, but none should expose user info freely
        assert "/".join(["", "Users", "testuser"]) not in artifact_str or "[REDACTED" in artifact_str

    def test_failure_event_to_dict(self) -> None:
        """Test converting failure event to dictionary."""
        event = create_failure_event(
            task_id="task_0001",
            project="AgentLab",
            stage="pytest",
            command="python -m pytest tests/",
            exit_code=1,
            stderr="test failed",
        )

        event_dict = event.to_dict()
        assert event_dict["task_id"] == "task_0001"
        assert event_dict["project"] == "AgentLab"
        assert event_dict["stage"] == "pytest"
        assert isinstance(event_dict["created_at"], str)

    def test_failure_event_json_path(self) -> None:
        """Test generating json path for failure event."""
        event = create_failure_event(
            task_id="task_0001",
            project="AgentLab",
            stage="test",
            command="echo",
            exit_code=0,
        )

        run_dir = Path("/tmp/AgentLab/runs/task_0001")
        path = event.to_json_path(run_dir)
        assert "failure_event.json" in str(path)
        assert "recovery" in str(path)

    def test_failure_event_from_missing_artifact(self) -> None:
        """Test creating failure event from missing artifact scenario."""
        event = create_failure_event(
            task_id="task_0001",
            project="AgentLab",
            stage="runtime",
            command=None,
            exit_code=None,
            error_type="missing_artifact",
            artifact_paths=["output/report.md"],
            context_pack_path="context/context_pack.yml",
        )

        assert event.error_type == "missing_artifact"
        assert "output/report.md" in event.artifact_paths
        assert event.context_pack_path is not None

    def test_failure_event_empty_stderr(self) -> None:
        """Test handling empty or None stderr."""
        event = create_failure_event(
            task_id="task_0001",
            project="AgentLab",
            stage="test",
            command="echo test",
            exit_code=0,
            stderr=None,
            stdout=None,
        )

        assert event.stderr_tail is None
        assert event.stdout_tail is None

    def test_failure_event_long_command_truncation(self) -> None:
        """Test that long stderr/stderr are properly truncated with tail."""
        very_long_stderr = "line\n" * 2000 + "FAILED\n"

        event = create_failure_event(
            task_id="task_0001",
            project="AgentLab",
            stage="test",
            command="echo test",
            exit_code=1,
            stderr=very_long_stderr,
            stderr_tail_chars=1000,
        )

        # Should contain end of original string (tail)
        assert "FAILED" in event.stderr_tail
        assert len(event.stderr_tail) <= 1000

    def test_failure_event_created_at_timestamp(self) -> None:
        """Test that created_at is a valid ISO timestamp."""
        event = create_failure_event(
            task_id="task_0001",
            project="AgentLab",
            stage="test",
            command="echo",
            exit_code=0,
        )

        # Should be parseable as ISO format
        try:
            datetime.fromisoformat(event.created_at.replace("Z", "+00:00"))
        except ValueError:
            pytest.fail(f"created_at is not valid ISO format: {event.created_at}")


class TestExtractErrorType:
    """Tests for extract_error_type_from_stderr function."""

    def test_extract_syntax_error(self) -> None:
        """Test extracting syntax error type."""
        from agent_runtime.recovery.failure_event import extract_error_type_from_stderr

        stderr = "  File \"test.py\", line 1\n    def foo(\n               ^\nSyntaxError"
        error_type = extract_error_type_from_stderr(stderr)
        assert error_type == "syntax_error"

    def test_extract_import_error(self) -> None:
        """Test extracting import error type."""
        from agent_runtime.recovery.failure_event import extract_error_type_from_stderr

        stderr = "ModuleNotFoundError: No module named 'nonexistent'"
        error_type = extract_error_type_from_stderr(stderr)
        assert error_type == "import_error"

    def test_extract_test_failure(self) -> None:
        """Test extracting test failure type."""
        from agent_runtime.recovery.failure_event import extract_error_type_from_stderr

        stderr = "FAILED tests/test_example.py::test_foo"
        error_type = extract_error_type_from_stderr(stderr)
        assert error_type == "test_failure"

    def test_extract_missing_artifact(self) -> None:
        """Test extracting missing artifact type."""
        from agent_runtime.recovery.failure_event import extract_error_type_from_stderr

        stderr = "FileNotFoundError: No such file or directory: 'output.txt'"
        error_type = extract_error_type_from_stderr(stderr)
        assert error_type == "missing_artifact"

    def test_extract_yaml_parse_error(self) -> None:
        """Test extracting yaml parse error type."""
        from agent_runtime.recovery.failure_event import extract_error_type_from_stderr

        stderr = "yaml.parser.ParserError: parser error"
        error_type = extract_error_type_from_stderr(stderr)
        assert error_type == "yaml_parse_failure"

    def test_extract_text_integrity_error(self) -> None:
        """Test extracting text integrity error type."""
        from agent_runtime.recovery.failure_event import extract_error_type_from_stderr

        stderr = "text integrity check failed"
        error_type = extract_error_type_from_stderr(stderr)
        assert error_type == "text_integrity_failure"

    def test_extract_timeout_error(self) -> None:
        """Test extracting timeout error type."""
        from agent_runtime.recovery.failure_event import extract_error_type_from_stderr

        stderr = "TimeoutError: operation timed out"
        error_type = extract_error_type_from_stderr(stderr)
        assert error_type == "timeout"

    def test_extract_permission_error(self) -> None:
        """Test extracting permission error type."""
        from agent_runtime.recovery.failure_event import extract_error_type_from_stderr

        stderr = "PermissionError: Permission denied"
        error_type = extract_error_type_from_stderr(stderr)
        assert error_type == "permission_error"

    def test_extract_secret_leak_error(self) -> None:
        """Test extracting secret leak risk type."""
        from agent_runtime.recovery.failure_event import extract_error_type_from_stderr

        stderr = "secret detector: potential credential exposure"
        error_type = extract_error_type_from_stderr(stderr)
        assert error_type == "secret_leak_risk"

    def test_extract_unknown_error(self) -> None:
        """Test extracting unknown error type."""
        from agent_runtime.recovery.failure_event import extract_error_type_from_stderr

        stderr = "some random error message"
        error_type = extract_error_type_from_stderr(stderr)
        assert error_type is None

    def test_extract_error_type_none(self) -> None:
        """Test extracting error type from None stderr."""
        from agent_runtime.recovery.failure_event import extract_error_type_from_stderr

        error_type = extract_error_type_from_stderr(None)
        assert error_type is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
