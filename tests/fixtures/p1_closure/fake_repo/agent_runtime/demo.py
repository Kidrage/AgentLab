"""Small fake module used by the P1 closure acceptance fixture.

The acceptance scenario only needs a local checkout-shaped repository for
CodeGraph dry-run/status checks. This module gives the fixture a realistic
Python file without adding dependencies or execution side effects.
"""


def add(left: int, right: int) -> int:
    """Return the sum of two integers."""
    return left + right


def describe_patch_target() -> str:
    """Describe why this fake repo exists."""
    return "local repo fixture for P1 acceptance"
