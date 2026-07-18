"""Tests for CLI error classification logic and regression templates."""

from agent_runtime.workers.cli_error_classifier import classify_cli_error, CliErrorClass

def test_classify_binary_missing():
    assert classify_cli_error(None, "", "", binary_missing=True) == CliErrorClass.BINARY_MISSING
    assert classify_cli_error(127, "", "") == CliErrorClass.BINARY_MISSING

def test_classify_timeout():
    assert classify_cli_error(None, "", "", timeout_occurred=True) == CliErrorClass.TIMEOUT

def test_classify_invalid_invocation():
    # exit code 2 and usage patterns
    assert classify_cli_error(2, "", "usage: hermes ... unrecognized arguments") == CliErrorClass.INVALID_CLI_INVOCATION

def test_classify_auth_required():
    assert classify_cli_error(1, "", "API key not set") == CliErrorClass.AUTH_REQUIRED
    assert classify_cli_error(1, "", "Unauthorized access") == CliErrorClass.AUTH_REQUIRED

def test_classify_network_required():
    assert classify_cli_error(1, "", "Could not resolve host") == CliErrorClass.NETWORK_REQUIRED
    assert classify_cli_error(1, "", "connection timed out") == CliErrorClass.NETWORK_REQUIRED
    assert classify_cli_error(1, "API call failed: Connection error.", "") == CliErrorClass.NETWORK_REQUIRED
    assert classify_cli_error(1, "API Error: Unable to connect (FailedToOpenSocket)", "") == CliErrorClass.NETWORK_REQUIRED

def test_classify_rate_limited():
    assert classify_cli_error(1, "", "Rate limit exceeded. Try again in 10s.") == CliErrorClass.RATE_LIMITED
    assert classify_cli_error(1, "", "Too many requests (429).") == CliErrorClass.RATE_LIMITED
    assert (
        classify_cli_error(
            1,
            "",
            "429 Too Many Requests: quota exceeded for requests per minute",
        )
        == CliErrorClass.RATE_LIMITED
    )


def test_classify_quota_exhausted():
    assert (
        classify_cli_error(
            1,
            "",
            "Individual quota reached. Please upgrade your subscription to increase your limits. Resets in 33m53s.",
        )
        == CliErrorClass.QUOTA_EXHAUSTED
    )


def test_classify_model_unavailable():
    assert (
        classify_cli_error(1, "", "Requested model not found")
        == CliErrorClass.MODEL_UNAVAILABLE
    )

def test_classify_permission_denied():
    assert classify_cli_error(1, "", "Permission denied to write file") == CliErrorClass.PERMISSION_DENIED

def test_regression_old_hermes_templates():
    # Hermes old fake templates:
    # hermes --task {task_packet_path}
    # hermes --task-packet {task_packet_path}
    # These must be classified as invalid_cli_invocation when run and failing with usage error.
    assert classify_cli_error(2, "", "usage: hermes [-h] [-z PROMPT] [-q]\nhermes: error: unrecognized arguments: --task") == CliErrorClass.INVALID_CLI_INVOCATION
    assert classify_cli_error(2, "", "usage: hermes [-h] [-z PROMPT] [-q]\nhermes: error: unrecognized arguments: --task-packet") == CliErrorClass.INVALID_CLI_INVOCATION
