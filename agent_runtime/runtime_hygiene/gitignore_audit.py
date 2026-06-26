"""Gitignore auditor for runtime hygiene."""

from pathlib import Path
from typing import Any

REQUIRED_RULES = [
    ".agents/",
    ".claude/",
    ".codex/",
    ".hermes/",
    ".agy/",
    ".openclaw/",
    ".gemini/",
    ".qwen/",
    ".claude.json",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.log",
    "*.pid",
    "*.sock",
    ".env",
    ".env.*"
]

class GitignoreAudit:
    def __init__(self, missing_rules: list[str], warnings: list[str]):
        self.missing_rules = missing_rules
        self.warnings = warnings

    def to_dict(self) -> dict[str, Any]:
        return {
            "missing_rules": self.missing_rules,
            "warnings": self.warnings
        }

def audit_gitignore(agentlab_root: Path) -> GitignoreAudit:
    """Audit the root .gitignore file for required patterns."""
    gitignore_path = agentlab_root / ".gitignore"
    missing_rules = []
    warnings = []

    if not gitignore_path.exists():
        missing_rules = REQUIRED_RULES.copy()
        warnings.append(".gitignore file does not exist at repository root")
        return GitignoreAudit(missing_rules, warnings)

    try:
        content = gitignore_path.read_text(encoding="utf-8")
        lines = [line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
        
        # Check each required rule
        for rule in REQUIRED_RULES:
            if rule not in lines:
                missing_rules.append(rule)
                warnings.append(f"Required gitignore pattern missing: {rule}")
    except Exception as e:
        warnings.append(f"Failed to read .gitignore: {str(e)}")

    return GitignoreAudit(missing_rules, warnings)
