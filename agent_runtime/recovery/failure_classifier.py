"""Failure classifier: deterministic categorization of failure types."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class FailureCategory(str, Enum):
    """Categories of failures for recovery planning."""

    SYNTAX_ERROR = "syntax_error"
    TEST_FAILURE = "test_failure"
    IMPORT_ERROR = "import_error"
    MISSING_DEPENDENCY = "missing_dependency"
    MISSING_ARTIFACT = "missing_artifact"
    TEXT_INTEGRITY_FAILURE = "text_integrity_failure"
    REMOTE_RAW_FAILURE = "remote_raw_failure"
    YAML_PARSE_FAILURE = "yaml_parse_failure"
    CONFIG_ERROR = "config_error"
    CLI_USAGE_ERROR = "cli_usage_error"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    CONTEXT_MISSING = "context_missing"
    SECRET_LEAK_RISK = "secret_leak_risk"
    RESOURCE_LIMIT = "resource_limit"
    TIMEOUT = "timeout"
    PERMISSION_ERROR = "permission_error"
    NETWORK_DISABLED_OR_UNAVAILABLE = "network_disabled_or_unavailable"
    EXTERNAL_TOOL_UNAVAILABLE = "external_tool_unavailable"
    UNKNOWN = "unknown"


@dataclass
class FailureClassification:
    """Result of failure classification."""

    primary_category: FailureCategory
    secondary_categories: list[FailureCategory]
    confidence: float
    matched_rules: list[str]
    is_retriable: bool
    requires_human_review: bool

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "primary_category": self.primary_category.value,
            "secondary_categories": [c.value for c in self.secondary_categories],
            "confidence": self.confidence,
            "matched_rules": self.matched_rules,
            "is_retriable": self.is_retriable,
            "requires_human_review": self.requires_human_review,
        }


class FailureClassifier:
    """Deterministic classifier for failure events.

    Uses pattern matching and rule-based logic to classify failures.
    No LLM calls are made - this is purely deterministic.
    """

    # Patterns for syntax errors
    SYNTAX_ERROR_PATTERNS = [
        re.compile(r"SyntaxError", re.IGNORECASE),
        re.compile(r"IndentationError", re.IGNORECASE),
        re.compile(r"unexpected EOF", re.IGNORECASE),
        re.compile(r"invalid syntax", re.IGNORECASE),
        re.compile(r"parse error", re.IGNORECASE),
    ]

    # Patterns for import errors
    IMPORT_ERROR_PATTERNS = [
        re.compile(r"ModuleNotFoundError", re.IGNORECASE),
        re.compile(r"ImportError", re.IGNORECASE),
        re.compile(r"No module named", re.IGNORECASE),
    ]

    # Patterns for text integrity failures - must come before generic test_failure
    TEXT_INTEGRITY_PATTERNS = [
        re.compile(r"text integrity.*fail", re.IGNORECASE),
        re.compile(r"integrity check.*fail", re.IGNORECASE),
        re.compile(r"min line count violation", re.IGNORECASE),
        re.compile(r"max line count violation", re.IGNORECASE),
    ]

    # Patterns for remote raw failures
    REMOTE_RAW_PATTERNS = [
        re.compile(r"remote raw.*fail", re.IGNORECASE),
        re.compile(r"GitHub raw.*fail", re.IGNORECASE),
        re.compile(r"line count mismatch", re.IGNORECASE),
    ]

    # Patterns for timeout errors
    TIMEOUT_PATTERNS = [
        re.compile(r"timed out", re.IGNORECASE),
        re.compile(r"TimeoutError", re.IGNORECASE),
        re.compile(r"timeout exceeded", re.IGNORECASE),
        re.compile(r"operation timed out", re.IGNORECASE),
    ]

    # Patterns for permission errors
    PERMISSION_PATTERNS = [
        re.compile(r"Permission denied", re.IGNORECASE),
        re.compile(r"PermissionError", re.IGNORECASE),
        re.compile(r"not allowed", re.IGNORECASE),
        re.compile(r"access denied", re.IGNORECASE),
    ]

    # Patterns for secret leak risks
    SECRET_LEAK_PATTERNS = [
        re.compile(r"secret.*leak", re.IGNORECASE),
        re.compile(r"secret.*detector", re.IGNORECASE),
        re.compile(r"redacted.*secret", re.IGNORECASE),
        re.compile(r"unauthorized", re.IGNORECASE),
    ]

    # Patterns for context budget exceeded
    CONTEXT_BUDGET_PATTERNS = [
        re.compile(r"context budget.*exceeded", re.IGNORECASE),
        re.compile(r"token.*limit.*exceeded", re.IGNORECASE),
        re.compile(r"context.*exceeded", re.IGNORECASE),
    ]

    # Patterns for context missing
    CONTEXT_MISSING_PATTERNS = [
        re.compile(r"context.*missing", re.IGNORECASE),
        re.compile(r"context.*pack.*missing", re.IGNORECASE),
        re.compile(r"context.*artifacts.*missing", re.IGNORECASE),
    ]

    # Patterns for resource limits
    RESOURCE_PATTERNS = [
        re.compile(r"resource.*limit", re.IGNORECASE),
        re.compile(r"out of memory", re.IGNORECASE),
        re.compile(r"OOM", re.IGNORECASE),
        re.compile(r"memory.*exceeded", re.IGNORECASE),
    ]

    # Patterns for network issues - must come before test_failure
    NETWORK_PATTERNS = [
        re.compile(r"Network unreachable", re.IGNORECASE),
        re.compile(r"ConnectionError.*network", re.IGNORECASE),
        re.compile(r"connection.*refused", re.IGNORECASE),
        re.compile(r"connection.*reset", re.IGNORECASE),
        re.compile(r"host.*unreachable", re.IGNORECASE),
        re.compile(r"EOF occurred in violation of protocol", re.IGNORECASE),
    ]

    # Patterns for missing artifacts - must come before test_failure
    MISSING_ARTIFACT_PATTERNS = [
        re.compile(r"No such file or directory", re.IGNORECASE),
        re.compile(r"FileNotFoundError", re.IGNORECASE),
        re.compile(r"missing artifact", re.IGNORECASE),
        re.compile(r"artifact.*missing", re.IGNORECASE),
        re.compile(r"cannot find", re.IGNORECASE),
    ]

    # Patterns for YAML parse errors
    YAML_PARSE_PATTERNS = [
        re.compile(r"yaml\.parser\.ParserError", re.IGNORECASE),
        re.compile(r"yaml\.scanner\.ScannerError", re.IGNORECASE),
        re.compile(r"could not determine a", re.IGNORECASE),
        re.compile(r"scanner error", re.IGNORECASE),
    ]

    # Patterns for test failures - must come LAST, after all specific patterns
    TEST_FAILURE_PATTERNS = [
        re.compile(r"pytest.*FAILED", re.IGNORECASE),
        re.compile(r"test.*FAILED", re.IGNORECASE),
        re.compile(r"AssertionError", re.IGNORECASE),
        re.compile(r"FAILED.*\d+ tests?", re.IGNORECASE),
    ]

    # Patterns for external tool unavailability
    EXTERNAL_TOOL_PATTERNS = [
        re.compile(r"external.*tool.*unavailable", re.IGNORECASE),
        re.compile(r"tool.*not found", re.IGNORECASE),
        re.compile(r"command.*not found", re.IGNORECASE),
        re.compile(r"executable.*not found", re.IGNORECASE),
    ]

    def __init__(self) -> None:
        """Initialize the classifier with all patterns."""
        self._all_patterns: list[tuple[list[re.Pattern], FailureCategory, str]] = [
            (self.SYNTAX_ERROR_PATTERNS, FailureCategory.SYNTAX_ERROR, "syntax_error_pattern"),
            (self.IMPORT_ERROR_PATTERNS, FailureCategory.IMPORT_ERROR, "import_error_pattern"),
            (self.TEST_FAILURE_PATTERNS, FailureCategory.TEST_FAILURE, "test_failure_pattern"),
            (self.MISSING_ARTIFACT_PATTERNS, FailureCategory.MISSING_ARTIFACT, "missing_artifact_pattern"),
            (self.YAML_PARSE_PATTERNS, FailureCategory.YAML_PARSE_FAILURE, "yaml_parse_pattern"),
            (self.TEXT_INTEGRITY_PATTERNS, FailureCategory.TEXT_INTEGRITY_FAILURE, "text_integrity_pattern"),
            (self.REMOTE_RAW_PATTERNS, FailureCategory.REMOTE_RAW_FAILURE, "remote_raw_pattern"),
            (self.TIMEOUT_PATTERNS, FailureCategory.TIMEOUT, "timeout_pattern"),
            (self.PERMISSION_PATTERNS, FailureCategory.PERMISSION_ERROR, "permission_pattern"),
            (self.SECRET_LEAK_PATTERNS, FailureCategory.SECRET_LEAK_RISK, "secret_leak_pattern"),
            (self.CONTEXT_BUDGET_PATTERNS, FailureCategory.CONTEXT_BUDGET_EXCEEDED, "context_budget_pattern"),
            (self.CONTEXT_MISSING_PATTERNS, FailureCategory.CONTEXT_MISSING, "context_missing_pattern"),
            (self.RESOURCE_PATTERNS, FailureCategory.RESOURCE_LIMIT, "resource_pattern"),
            (self.NETWORK_PATTERNS, FailureCategory.NETWORK_DISABLED_OR_UNAVAILABLE, "network_pattern"),
            (self.EXTERNAL_TOOL_PATTERNS, FailureCategory.EXTERNAL_TOOL_UNAVAILABLE, "external_tool_pattern"),
        ]

    def classify(
        self,
        stderr: str | None = None,
        stdout: str | None = None,
        error_type: str | None = None,
        exit_code: int | None = None,
    ) -> FailureClassification:
        """Classify a failure based on available evidence.

        Args:
            stderr: Stderr content from failed command
            stdout: Stdout content from failed command
            error_type: Optional pre-extracted error type
            exit_code: Optional exit code for additional clues

        Returns:
            FailureClassification with category, confidence, and metadata
        """
        combined_text = " ".join(filter(None, [stderr, stdout]))

        # Build list of matching patterns with their confidence weights
        matches: list[tuple[FailureCategory, float, str]] = []

        for patterns, category, rule_name in self._all_patterns:
            for pattern in patterns:
                if pattern.search(combined_text):
                    # Higher confidence for stderr matches
                    weight = 0.9 if stderr and pattern.search(stderr) else 0.7
                    matches.append((category, weight, rule_name))

        # Add confidence from error_type if provided
        if error_type:
            error_type_lower = error_type.lower()
            for patterns, category, rule_name in self._all_patterns:
                for pattern in patterns:
                    if pattern.search(error_type_lower):
                        matches.append((category, 0.95, f"error_type:{rule_name}"))
                        break

        # Add confidence from exit code for known patterns
        if exit_code is not None:
            if exit_code == 1:
                # Common exit code for many failures
                matches.append((FailureCategory.UNKNOWN, 0.5, "exit_code_1"))
            elif exit_code == 126:
                matches.append((FailureCategory.PERMISSION_ERROR, 0.85, "exit_code_126_permission"))
            elif exit_code == 127:
                matches.append((FailureCategory.MISSING_ARTIFACT, 0.8, "exit_code_127_not_found"))
            elif exit_code == 128:
                matches.append((FailureCategory.UNKNOWN, 0.6, "exit_code_128_signal"))

        if not matches:
            return FailureClassification(
                primary_category=FailureCategory.UNKNOWN,
                secondary_categories=[],
                confidence=0.3,
                matched_rules=[],
                is_retriable=False,
                requires_human_review=True,
            )

        # Aggregate by category
        category_scores: dict[FailureCategory, tuple[float, list[str]]] = {}
        for category, weight, rule in matches:
            if category not in category_scores:
                category_scores[category] = (0.0, [])
            current_score, current_rules = category_scores[category]
            category_scores[category] = (
                max(current_score, weight),
                list(set(current_rules + [rule])),
            )

        # Get primary category (highest confidence)
        primary_category = max(category_scores.keys(), key=lambda c: category_scores[c][0])
        primary_score, primary_rules = category_scores[primary_category]

        # Get secondary categories (other non-zero scores)
        secondary_categories = [
            cat for cat, (score, _) in category_scores.items()
            if cat != primary_category and score >= 0.5
        ]

        # Determine retryability and human review requirement
        is_retriable = self._is_retriable(primary_category)
        requires_human_review = self._requires_human_review(primary_category)

        return FailureClassification(
            primary_category=primary_category,
            secondary_categories=secondary_categories,
            confidence=round(primary_score, 2),
            matched_rules=primary_rules,
            is_retriable=is_retriable,
            requires_human_review=requires_human_review,
        )

    def _is_retriable(self, category: FailureCategory) -> bool:
        """Determine if a failure category is retryable."""
        retryable = {
            FailureCategory.TIMEOUT,
            FailureCategory.RESOURCE_LIMIT,
            FailureCategory.NETWORK_DISABLED_OR_UNAVAILABLE,
            FailureCategory.EXTERNAL_TOOL_UNAVAILABLE,
            FailureCategory.CONTEXT_MISSING,
            FailureCategory.MISSING_ARTIFACT,
        }
        return category in retryable

    def _requires_human_review(self, category: FailureCategory) -> bool:
        """Determine if a failure requires human review."""
        human_review = {
            FailureCategory.SECRET_LEAK_RISK,
            FailureCategory.PERMISSION_ERROR,
            FailureCategory.REMOTE_RAW_FAILURE,
            FailureCategory.TEXT_INTEGRITY_FAILURE,
            FailureCategory.YAML_PARSE_FAILURE,
            FailureCategory.SYNTAX_ERROR,
            FailureCategory.UNKNOWN,
        }
        return category in human_review


def classify_failure(
    stderr: str | None = None,
    stdout: str | None = None,
    error_type: str | None = None,
    exit_code: int | None = None,
) -> FailureClassification:
    """Convenience function to classify a failure.

    Args:
        stderr: Stderr content from failed command
        stdout: Stdout content from failed command
        error_type: Optional pre-extracted error type
        exit_code: Optional exit code

    Returns:
        FailureClassification result
    """
    classifier = FailureClassifier()
    return classifier.classify(stderr, stdout, error_type, exit_code)
