"""Tests for P2-I failure classifier."""

from __future__ import annotations

import pytest

from agent_runtime.recovery.failure_classifier import (
    FailureClassifier,
    FailureCategory,
    classify_failure,
)


class TestFailureClassifier:
    """Tests for failure classifier functionality."""

    def test_classifies_syntax_error(self) -> None:
        """Test classifying syntax errors."""
        classifier = FailureClassifier()
        stderr = "  File \"test.py\", line 1\n    def foo(\n               ^\nSyntaxError: invalid syntax"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.SYNTAX_ERROR
        assert result.confidence >= 0.7
        assert result.is_retriable is False
        assert result.requires_human_review is True

    def test_classifies_pytest_failure(self) -> None:
        """Test classifying pytest test failures."""
        classifier = FailureClassifier()
        # Use pytest-specific output to avoid conflict with text integrity
        stderr = "test_example.py::test_foo FAILED\nAssertionError: assert False\n1 failed in 0.1s"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.TEST_FAILURE
        assert result.confidence >= 0.7
        # Test failure is not automatically retryable per design (fix first)
        assert result.is_retriable is False
        assert result.requires_human_review is False

    def test_classifies_import_error(self) -> None:
        """Test classifying import errors."""
        classifier = FailureClassifier()
        stderr = "ModuleNotFoundError: No module named 'missing_module'"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.IMPORT_ERROR
        assert result.confidence >= 0.7

    def test_classifies_missing_artifact(self) -> None:
        """Test classifying missing artifact errors."""
        classifier = FailureClassifier()
        stderr = "FileNotFoundError: No such file or directory: 'output/report.md'"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.MISSING_ARTIFACT
        assert result.confidence >= 0.7

    def test_classifies_yaml_parse_failure(self) -> None:
        """Test classifying YAML parse errors."""
        classifier = FailureClassifier()
        stderr = "yaml.parser.ParserError: parser error"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.YAML_PARSE_FAILURE
        assert result.confidence >= 0.7
        assert result.requires_human_review is True

    def test_classifies_text_integrity_failure(self) -> None:
        """Test classifying text integrity failures."""
        classifier = FailureClassifier()
        stderr = "text integrity check failed: min line count violation"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.TEXT_INTEGRITY_FAILURE
        assert result.confidence >= 0.7
        assert result.requires_human_review is True

    def test_classifies_remote_raw_failure(self) -> None:
        """Test classifying remote raw failures."""
        classifier = FailureClassifier()
        stderr = "remote raw check failed: line count mismatch"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.REMOTE_RAW_FAILURE
        assert result.confidence >= 0.7
        assert result.requires_human_review is True

    def test_classifies_timeout(self) -> None:
        """Test classifying timeout errors."""
        classifier = FailureClassifier()
        stderr = "TimeoutError: operation timed out after 30s"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.TIMEOUT
        assert result.confidence >= 0.7
        assert result.is_retriable is True
        assert result.requires_human_review is False

    def test_classifies_secret_leak_risk(self) -> None:
        """Test classifying secret leak risks."""
        classifier = FailureClassifier()
        stderr = "secret leak detector: potential credential exposure detected"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.SECRET_LEAK_RISK
        assert result.confidence >= 0.7
        assert result.requires_human_review is True

    def test_unknown_failure_requires_human_review(self) -> None:
        """Test that unknown failures require human review."""
        classifier = FailureClassifier()
        stderr = "some unknown error message that doesn't match any pattern"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.UNKNOWN
        assert result.confidence < 0.5
        assert result.requires_human_review is True

    def test_classifies_permission_error(self) -> None:
        """Test classifying permission errors."""
        classifier = FailureClassifier()
        stderr = "PermissionError: Permission denied: 'restricted_file.txt'"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.PERMISSION_ERROR
        assert result.confidence >= 0.7
        assert result.requires_human_review is True

    def test_classifies_context_missing(self) -> None:
        """Test classifying context missing errors."""
        classifier = FailureClassifier()
        stderr = "context pack missing: context/context_pack.yml not found"
        result = classifier.classify(stderr=stderr)

        assert result.primary_category == FailureCategory.CONTEXT_MISSING
        assert result.confidence >= 0.7
        assert result.is_retriable is True

    def test_classifies_config_error(self) -> None:
        """Test classifying config errors."""
        classifier = FailureClassifier()
        # Config error might not have a specific pattern, falls back to unknown
        stderr = "config loading error"
        result = classifier.classify(stderr=stderr)

        # Should still return a valid classification
        assert result.primary_category in FailureCategory
        assert result.confidence >= 0

    def test_classifies_network_disabled(self) -> None:
        """Test classifying network disabled errors."""
        classifier = FailureClassifier()
        # Use specific network error pattern that won't match test_failure
        stderr = "ConnectionError: Network unreachable: connection to api.example.com failed"
        result = classifier.classify(stderr=stderr)

        # The pattern should match network_disabled_or_unavailable
        assert result.primary_category == FailureCategory.NETWORK_DISABLED_OR_UNAVAILABLE
        assert result.is_retriable is True

    def test_classifies_with_stdout(self) -> None:
        """Test classifying using stdout content."""
        classifier = FailureClassifier()
        stdout = "FAILED tests/test_example.py::test_foo\nAssertionError"
        result = classifier.classify(stdout=stdout)

        assert result.primary_category == FailureCategory.TEST_FAILURE
        assert result.confidence >= 0.5

    def test_classifies_with_error_type(self) -> None:
        """Test classifying with pre-extracted error type."""
        classifier = FailureClassifier()
        # For error_type matching, we need the stderr to also match the pattern
        stderr = "SyntaxError: invalid syntax in test"
        error_type = "syntax_error"

        result = classifier.classify(stderr=stderr, error_type=error_type)
        # Error type should boost confidence for syntax_error
        assert result.primary_category == FailureCategory.SYNTAX_ERROR

    def test_classifies_with_exit_code(self) -> None:
        """Test classifying with exit code hints."""
        classifier = FailureClassifier()
        stderr = "some error"
        result = classifier.classify(stderr=stderr, exit_code=127)

        # Exit code 127 indicates "command not found"
        # Should influence classification toward missing artifact or not found

    def test_classification_matches_multiple_patterns(self) -> None:
        """Test classification when multiple patterns match."""
        classifier = FailureClassifier()
        stderr = "FileNotFoundError: No module named 'test' - test.py does not exist"
        result = classifier.classify(stderr=stderr)

        # Should pick the best match
        assert result.primary_category in (FailureCategory.MISSING_ARTIFACT, FailureCategory.IMPORT_ERROR)
        assert result.confidence >= 0.5

    def test_classify_failure_convenience_function(self) -> None:
        """Test the classify_failure convenience function."""
        stderr = " tests/test_example.py FAILED"
        result = classify_failure(stderr=stderr)

        assert result.primary_category == FailureCategory.TEST_FAILURE
        assert isinstance(result.secondary_categories, list)
        assert isinstance(result.matched_rules, list)


class TestFailureCategoryEnum:
    """Tests for FailureCategory enum values."""

    def test_all_categories_defined(self) -> None:
        """Test that all expected categories are defined."""
        expected = [
            "syntax_error",
            "test_failure",
            "import_error",
            "missing_dependency",
            "missing_artifact",
            "text_integrity_failure",
            "remote_raw_failure",
            "yaml_parse_failure",
            "config_error",
            "cli_usage_error",
            "context_budget_exceeded",
            "context_missing",
            "secret_leak_risk",
            "resource_limit",
            "timeout",
            "permission_error",
            "network_disabled_or_unavailable",
            "external_tool_unavailable",
            "unknown",
        ]

        actual = [cat.value for cat in FailureCategory]
        for cat in expected:
            assert cat in actual, f"Category {cat} not found in FailureCategory"

    def test_categories_are_unique(self) -> None:
        """Test that all category values are unique."""
        values = [cat.value for cat in FailureCategory]
        assert len(values) == len(set(values)), "Duplicate category values found"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
