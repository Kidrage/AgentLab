"""Classifier to map CLI command failures to semantic error classes."""

import yaml
from pathlib import Path
from typing import Optional, Any

# Standard CLI error classes
class CliErrorClass:
    BINARY_MISSING = "binary_missing"
    INVALID_CLI_INVOCATION = "invalid_cli_invocation"
    AUTH_REQUIRED = "auth_required"
    NETWORK_REQUIRED = "network_required"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    MODEL_UNAVAILABLE = "model_unavailable"
    PROVIDER_ERROR = "provider_error"
    TASK_FAILED = "task_failed"
    UNKNOWN_FAILURE = "unknown_failure"

DEFAULT_RULES = [
    {
        "error_class": CliErrorClass.INVALID_CLI_INVOCATION,
        "exit_codes": [2],
        "patterns": ["usage:", "unrecognized arguments", "error: unrecognized", "invalid choice:"]
    },
    {
        "error_class": CliErrorClass.AUTH_REQUIRED,
        "patterns": ["API key", "unauthorized", "auth required", "Authentication", "login required", "not authenticated"]
    },
    {
        "error_class": CliErrorClass.NETWORK_REQUIRED,
        "patterns": [
            "network",
            "DNS",
            "proxy",
            "connection failed",
            "connection error",
            "unable to connect",
            "failedtoopensocket",
            "failed to open socket",
            "timeout",
            "timed out",
            "timed_out",
            "Could not resolve",
        ]
    },
    {
        "error_class": CliErrorClass.PERMISSION_DENIED,
        "patterns": [
            "Permission denied",
            "operation not permitted",
            "sandbox denied",
            "AccessDenied",
            "not allowed",
        ]
    },
    {
        "error_class": CliErrorClass.QUOTA_EXHAUSTED,
        "patterns": ["individual quota reached. please upgrade your subscription"]
    },
    {
        "error_class": CliErrorClass.MODEL_UNAVAILABLE,
        "patterns": [
            "model not found",
            "unknown model",
            "unsupported model",
            "model unavailable",
            "model is not available",
        ],
    },
    {
        "error_class": CliErrorClass.RATE_LIMITED,
        "patterns": ["rate limit", "too many requests", "429"]
    }
]

def load_classification_rules(config_path: Path) -> list[dict[str, Any]]:
    """Load error classification rules from a YAML file, falling back to default rules."""
    if not config_path.exists():
        return DEFAULT_RULES
    try:
        content = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not data or "rules" not in data:
            return DEFAULT_RULES
        return data["rules"]
    except Exception:
        return DEFAULT_RULES

def classify_cli_error(
    exit_code: Optional[int],
    stdout: str,
    stderr: str,
    timeout_occurred: bool = False,
    binary_missing: bool = False,
    config_path: Optional[Path] = None
) -> str:
    """Classify the failure of a CLI command into a semantic error class."""
    if binary_missing:
        return CliErrorClass.BINARY_MISSING
        
    if timeout_occurred:
        return CliErrorClass.TIMEOUT

    # Combine stdout and stderr for pattern checking
    combined_output = (stdout or "") + "\n" + (stderr or "")
    
    # Load rules (either from config or defaults)
    rules = DEFAULT_RULES
    if config_path:
        rules = load_classification_rules(config_path)

    # Check matching rules
    for rule in rules:
        err_class = rule.get("error_class")
        rule_exit_codes = rule.get("exit_codes", [])
        rule_patterns = rule.get("patterns", [])

        # Match exit code
        exit_code_matched = exit_code in rule_exit_codes if exit_code is not None and rule_exit_codes else False
        
        # Match patterns
        pattern_matched = False
        for pattern in rule_patterns:
            if pattern.lower() in combined_output.lower():
                pattern_matched = True
                break
                
        # If exit_codes are specified in the rule, they should match (or patterns must match)
        if rule_exit_codes:
            if exit_code_matched or pattern_matched:
                return err_class
        else:
            if pattern_matched:
                return err_class

    # Default fallbacks
    if exit_code is not None:
        if exit_code == 127:  # Command not found
            return CliErrorClass.BINARY_MISSING
        if exit_code == 2:
            return CliErrorClass.INVALID_CLI_INVOCATION
        if exit_code != 0:
            return CliErrorClass.TASK_FAILED
            
    return CliErrorClass.UNKNOWN_FAILURE
