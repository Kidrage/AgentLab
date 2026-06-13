from __future__ import annotations

import re
from pathlib import PurePosixPath

from agent_runtime.review.models import ReviewFinding
from agent_runtime.review.policy import ReviewPolicy


SECRET_PATTERNS = [
    re.compile(r"(?<!-)sk-[A-Za-z0-9][A-Za-z0-9_-]{6,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{8,}"),
    re.compile(r"GITHUB_TOKEN\s*="),
    re.compile(r"AWS_SECRET_ACCESS_KEY"),
    re.compile(r"OPENAI_API_KEY\s*="),
    re.compile(r"DEEPSEEK_API_KEY\s*="),
]

PRIVATE_URL_PATTERNS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "10.",
    "192.168.",
    "file://",
]

NEGATIVE_RE = re.compile(r"\b(no|false|none|not accessed|not executed|skipped|rejected|denied)\b", re.I)
AFFIRMATIVE_RE = re.compile(r"\b(yes|true|accessed|executed|started|cloned|copied)\b", re.I)


def safety_findings(text_evidence: dict[str, str], policy: ReviewPolicy) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    combined = "\n".join(f"## {name}\n{text}" for name, text in text_evidence.items())

    if policy.safety_checks.get("forbid_secret_patterns", True):
        for pattern in SECRET_PATTERNS:
            if pattern.search(combined):
                findings.append(
                    ReviewFinding(
                        finding_id=f"secret-{_slug(pattern.pattern)}",
                        severity="critical",
                        category="secrets",
                        message=f"Potential secret pattern found: {pattern.pattern}",
                        evidence=_matching_regex_lines(text_evidence, pattern),
                        recommendation="Remove or redact secret-like values from submitted artifacts.",
                    )
                )

    if policy.safety_checks.get("forbid_private_url_access", True):
        for pattern in PRIVATE_URL_PATTERNS:
            lines = _matching_lines(text_evidence, pattern)
            suspicious = [line for line in lines if _is_affirmative_line(line)]
            if suspicious:
                findings.append(
                    ReviewFinding(
                        finding_id=f"private-url-{_slug(pattern)}",
                        severity="high",
                        category="safety",
                        message=f"Private/local/file URL access appears affirmed: {pattern}",
                        evidence=suspicious,
                        recommendation="Remove private/local/file URL access from the delivery evidence.",
                    )
                )

    phrase_checks = [
        ("external-script", "executed external script", "forbid_external_script_execution", "critical"),
        ("mcp-server", "started mcp server", "forbid_mcp_server_start", "critical"),
        ("remote-clone", "cloned remote repo", "forbid_remote_clone", "high"),
        ("third-party-source", "copied third-party source", "forbid_third_party_source_copy", "critical"),
    ]
    for finding_id, phrase, flag, severity in phrase_checks:
        if not policy.safety_checks.get(flag, True):
            continue
        lines = _matching_lines(text_evidence, phrase)
        suspicious = [line for line in lines if _is_affirmative_line(line)]
        if suspicious:
            findings.append(
                ReviewFinding(
                    finding_id=f"safety-{finding_id}",
                    severity=severity,
                    category="safety",
                    message=f"Forbidden action appears affirmed: {phrase}",
                    evidence=suspicious,
                    recommendation="Remove the forbidden action and resubmit with safe evidence.",
                )
            )

    structured_checks = [
        ("remote-clone", ["remote repos cloned", "remote repo cloned", "cloned remote repo"], "forbid_remote_clone", "high"),
        ("external-script", ["external scripts executed", "external script executed"], "forbid_external_script_execution", "critical"),
        ("mcp-server", ["mcp servers started", "mcp server started"], "forbid_mcp_server_start", "critical"),
        ("third-party-source", ["third-party source copied"], "forbid_third_party_source_copy", "critical"),
        ("private-url", ["private urls accessed", "private/local/file urls accessed"], "forbid_private_url_access", "high"),
    ]
    for finding_id, labels, flag, severity in structured_checks:
        if not policy.safety_checks.get(flag, True):
            continue
        suspicious: list[str] = []
        for label in labels:
            for line in _matching_lines(text_evidence, label):
                if _is_affirmative_line(line):
                    suspicious.append(line)
        if suspicious:
            findings.append(
                ReviewFinding(
                    finding_id=f"safety-{finding_id}-structured",
                    severity=severity,
                    category="safety",
                    message=f"Forbidden structured safety evidence is affirmative: {labels[0]}",
                    evidence=suspicious,
                    recommendation="Resubmit only after the forbidden action is absent and evidence says no/false.",
                )
            )

    return _dedupe_findings(findings)


def scope_findings(changed_files: list[str], text_evidence: dict[str, str], policy: ReviewPolicy) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    changed = [item.strip() for item in changed_files if item and item.strip()]
    for path in changed:
        normalized = path.strip("/").replace("\\", "/")
        if _matches_any_path(normalized, policy.forbidden_paths):
            findings.append(
                ReviewFinding(
                    finding_id=f"forbidden-path-{_slug(normalized)}",
                    severity="critical" if normalized.startswith((".git/", "secrets/")) else "high",
                    category="scope",
                    message=f"Changed file touches forbidden path: {path}",
                    evidence=[path],
                    recommendation="Remove forbidden path changes from the delivery.",
                )
            )
        elif _matches_any_path(normalized, policy.high_risk_paths):
            if not _has_scope_rationale(normalized, text_evidence):
                findings.append(
                    ReviewFinding(
                        finding_id=f"high-risk-path-{_slug(normalized)}",
                        severity="low",
                        category="scope",
                        message=f"Changed file touches high-risk path without explicit rationale: {path}",
                        evidence=[path],
                        recommendation="Document why this high-risk path needed to change.",
                        status="warn",
                    )
                )

    if not changed and _mentions_modified_files(text_evidence):
        findings.append(
            ReviewFinding(
                finding_id="changed-files-missing",
                severity="medium",
                category="scope",
                message="Report appears to claim modified files, but changed_files is empty.",
                evidence=["changed_files=[]"],
                recommendation="Provide the changed_files list for review.",
            )
        )
    return findings


def _matching_lines(text_evidence: dict[str, str], pattern: str) -> list[str]:
    matches: list[str] = []
    needle = pattern.lower()
    for name, text in text_evidence.items():
        for line in text.splitlines():
            if needle in line.lower():
                matches.append(f"{name}: {line.strip()}")
    return matches


def _matching_regex_lines(text_evidence: dict[str, str], pattern: re.Pattern[str]) -> list[str]:
    matches: list[str] = []
    for name, text in text_evidence.items():
        for line in text.splitlines():
            if pattern.search(line):
                matches.append(f"{name}: {line.strip()}")
    return matches


def _is_affirmative_line(line: str) -> bool:
    tail = line.split(":", maxsplit=1)[-1].strip()
    if NEGATIVE_RE.search(tail):
        return False
    return bool(AFFIRMATIVE_RE.search(tail))


def _matches_any_path(path: str, prefixes: list[str]) -> bool:
    for prefix in prefixes:
        normalized = prefix.strip("/").replace("\\", "/")
        if not normalized:
            continue
        if normalized.endswith("/"):
            if path.startswith(normalized):
                return True
        elif path == normalized or path.startswith(normalized + "/"):
            return True
    return False


def _has_scope_rationale(path: str, text_evidence: dict[str, str]) -> bool:
    basename = PurePosixPath(path).name.lower()
    combined = "\n".join(text_evidence.values()).lower()
    return basename in combined and any(word in combined for word in ("reason", "rationale", "because", "scope"))


def _mentions_modified_files(text_evidence: dict[str, str]) -> bool:
    combined = "\n".join(text_evidence.values()).lower()
    return any(
        phrase in combined
        for phrase in (
            "## changed files",
            "## modified files",
            "modified files:",
            "files changed:",
        )
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "item"


def _dedupe_findings(findings: list[ReviewFinding]) -> list[ReviewFinding]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    result: list[ReviewFinding] = []
    for finding in findings:
        key = (finding.finding_id, tuple(finding.evidence))
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result
