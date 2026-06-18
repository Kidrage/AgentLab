"""S4 static trust scanner for skill packages.

The scanner is intentionally shallow and deterministic. It reads text metadata
and reports risk signals; it never executes package content.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


DEFAULT_TRUST_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "skill_trust_policy.yml"

DEFAULT_TRUST_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "fail_on_high": True,
    "suspicious_patterns": {
        "shell_execution": r"\b(subprocess|os\.system|shell|exec\(|eval\()\b",
        "network_access": r"\b(curl|wget|requests\.|urllib|http://|https://)\b",
        "secret_access": r"\b(API_KEY|TOKEN|SECRET|PASSWORD|os\.environ|dotenv)\b",
        "destructive_filesystem": r"\b(rm -rf|delete|unlink|shutil\.rmtree|truncate)\b",
        "path_traversal": r"\.\./",
        "binary_reference": r"\b(\.dylib|\.so|\.dll|\.exe)\b",
    },
}


def load_trust_policy(path: Path | str | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path is not None else DEFAULT_TRUST_POLICY_PATH
    policy = {
        "schema_version": DEFAULT_TRUST_POLICY["schema_version"],
        "fail_on_high": DEFAULT_TRUST_POLICY["fail_on_high"],
        "suspicious_patterns": dict(DEFAULT_TRUST_POLICY["suspicious_patterns"]),
    }
    if policy_path.exists():
        data = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            policy.update({k: v for k, v in data.items() if k != "suspicious_patterns"})
            if isinstance(data.get("suspicious_patterns"), dict):
                policy["suspicious_patterns"].update(data["suspicious_patterns"])
    return policy


def _package_text(package_path: Path, parsed_skill: dict[str, Any]) -> str:
    parts = [
        str(parsed_skill.get("display_name") or ""),
        str(parsed_skill.get("description") or ""),
        str(parsed_skill.get("body_preview") or ""),
        yaml.safe_dump(parsed_skill.get("entrypoints") or [], sort_keys=True),
    ]
    if package_path.is_dir():
        for name in ("SKILL.md", "skill.yml", "manifest.yml", "README.md"):
            path = package_path / name
            if path.exists() and path.is_file():
                try:
                    text = path.read_text(encoding="utf-8")[:4000]
                    if name == "SKILL.md" and text.startswith("---"):
                        chunks = text.split("---", 2)
                        if len(chunks) == 3:
                            text = chunks[2]
                    parts.append(text)
                except UnicodeDecodeError:
                    parts.append(name)
    return "\n".join(parts)


def scan_skill_trust(package_path: Path | str, parsed_skill: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run static trust checks against a local skill package."""

    policy = policy or load_trust_policy()
    path = Path(package_path)
    text = _package_text(path, parsed_skill)
    findings: list[dict[str, str]] = []
    for finding_id, pattern in (policy.get("suspicious_patterns") or {}).items():
        if re.search(str(pattern), text, re.IGNORECASE):
            severity = "high" if finding_id in {"shell_execution", "secret_access", "destructive_filesystem"} else "medium"
            findings.append(
                {
                    "finding_id": str(finding_id),
                    "severity": severity,
                    "message": f"Static pattern matched: {finding_id}",
                }
            )

    validation_errors = parsed_skill.get("validation_errors") or []
    for error in validation_errors:
        findings.append(
            {
                "finding_id": "metadata_incomplete",
                "severity": "medium",
                "message": str(error),
            }
        )

    high_count = sum(1 for finding in findings if finding.get("severity") == "high")
    medium_count = sum(1 for finding in findings if finding.get("severity") == "medium")
    trust_score = max(0, 100 - high_count * 35 - medium_count * 15)
    passed = not (policy.get("fail_on_high", True) and high_count)

    return {
        "schema_version": 1,
        "skill_id": parsed_skill.get("skill_id"),
        "package_path": str(path),
        "trust_score": trust_score,
        "findings": findings,
        "passed": passed,
        "notes": ["Static scan only; no skill code executed."],
    }
