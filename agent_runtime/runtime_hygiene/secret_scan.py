"""Secret scanner for runtime hygiene."""

from pathlib import Path
from typing import Any
import re

SECRET_PATTERNS = {
    "OpenAI API Key": re.compile(r"sk-[a-zA-Z0-9]{32,}"),
    "Anthropic API Key": re.compile(r"sk-ant-[a-zA-Z0-9]{40,}"),
    "Google API Key": re.compile(r"AIzaSy[a-zA-Z0-9-_]{33}"),
    "Generic Assignment Secret": re.compile(r"(?:api[-_]?key|secret|token|password|credential|private[-_]?key)\s*[:=]\s*['\"]?([a-zA-Z0-9\-_\.\+=]{8,})['\"]?", re.IGNORECASE)
}

class SecretScanReport:
    def __init__(self, findings: list[dict[str, Any]], warnings: list[str]):
        self.findings = findings
        self.warnings = warnings

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": self.findings,
            "warnings": self.warnings
        }

def scan_secrets(agentlab_root: Path) -> SecretScanReport:
    """Scan files in the repository for potential secrets and tokens."""
    findings = []
    warnings = []

    # Ignore heavy or non-source directories to avoid performance issues
    ignored_names = {
        ".git", ".venv", "venv", "node_modules", "__pycache__",
        "projects", "acceptance_runs", "web_ui", "tests", "workspaces", ".agents"
    }

    # We want to scan only text files
    scannable_exts = {".py", ".yml", ".yaml", ".md", ".json", ".txt", ".sh", ".cfg", ".ini"}

    def scan_file(file_path: Path):
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            for idx, line in enumerate(content.splitlines(), 1):
                for name, regex in SECRET_PATTERNS.items():
                    for match in regex.finditer(line):
                        val = match.group(1) if len(match.groups()) > 0 else match.group(0)
                        if len(val) < 8 or any(x in val.lower() for x in ["your_", "placeholder", "xxx", "tbd", "test", "dummy"]):
                            continue
                        
                        # Redact the secret
                        redacted = line.replace(val, "*" * 8)
                        findings.append({
                            "file": str(file_path.relative_to(agentlab_root)),
                            "line": idx,
                            "pattern_matched": name,
                            "snippet_redacted": redacted
                        })
                        warnings.append(f"Potential secret leak ({name}) in {file_path.name}:{idx}")
        except Exception:
            pass

    def scan_dir(dir_path: Path):
        try:
            for item in dir_path.iterdir():
                if item.name in ignored_names:
                    continue
                # CRITICAL: do not follow symlinks when scanning directories
                if item.is_symlink():
                    continue
                if item.is_file():
                    if item.suffix in scannable_exts or item.name == ".env":
                        scan_file(item)
                elif item.is_dir():
                    scan_dir(item)
        except PermissionError:
            pass

    scan_dir(agentlab_root)
    return SecretScanReport(findings, warnings)
