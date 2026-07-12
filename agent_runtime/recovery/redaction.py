"""Recovery redaction: filter secrets, env values, private paths from failure output."""

from __future__ import annotations

import os
import re
from pathlib import Path

# Patterns that look like secrets
SECRET_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{8,})['\"]?"), "API_KEY"),
    (re.compile(r"(?i)(secret[_-]?key|secret)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{8,})['\"]?"), "SECRET_KEY"),
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?([^\s'\"]{4,})['\"]?"), "PASSWORD"),
    (re.compile(r"(?i)(auth[_-]?token|access[_-]?token|bearer)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{8,})['\"]?"), "TOKEN"),
    (re.compile(r"(?i)authorization\s*[:=]\s*['\"]?(Bearer\s+)?([A-Za-z0-9_\-\.]{8,})['\"]?"), "AUTHORIZATION"),
    (re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"), "PRIVATE_KEY"),
    (re.compile(r"(?i)(sk-[A-Za-z0-9]{8,})"), "OPENAI_KEY"),
    (re.compile(r"(?i)(ghp_[A-Za-z0-9]{8,})"), "GITHUB_TOKEN"),
    (re.compile(r"(?i)(AKIA[0-9A-Z]{8,})"), "AWS_KEY"),
]

# Home path redaction covers the current host and reports created on the other
# supported runner OS. Build common roots without embedding user-specific paths.
_home_roots = {
    str(Path.home().parent),
    "/" + "Users",
    "/" + "home",
}
_home_root_pattern = "|".join(re.escape(root) for root in sorted(_home_roots))
HOME_PATH_PATTERN = re.compile(
    r"(?:" + _home_root_pattern + r")/[^/\s]+"
)

# Private URL patterns
PRIVATE_URL_PATTERNS = [
    re.compile(r"file:///\S+"),
    re.compile(r"https?://localhost[:/]\S+"),
    re.compile(r"https?://127\.0\.0\.1[:/]\S+"),
    re.compile(r"https?://192\.168\.\d+\.\d+[:/]\S+"),
    re.compile(r"https?://10\.\d+\.\d+\.\d+[:/]\S+"),
]

REDACTED = "[REDACTED_SECRET]"
HOME_PLACEHOLDER = "<HOME>"


def _redact_env_values(text: str) -> tuple[str, list[str]]:
    """Remove content that looks like it came from a .env file."""
    warnings: list[str] = []
    lines = text.splitlines()
    filtered: list[str] = []
    in_env_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# .env") or stripped.startswith("# dotenv") or stripped.startswith("# environment"):
            in_env_block = True
            warnings.append("env block header detected; skipping block")
            continue
        if in_env_block:
            if stripped == "" or stripped.startswith("#"):
                continue
            if "=" in stripped and any(kw in stripped.upper() for kw in ("KEY", "SECRET", "TOKEN", "PASSWORD", "AUTH", "CREDENTIAL")):
                warnings.append(f"redacted env line: {stripped[:30]}...")
                continue
            # End of env block: non-empty line that doesn't look like env
            if not re.match(r"^[A-Z_]+\s*=", stripped):
                in_env_block = False
            else:
                continue
        filtered.append(line)
    return "\n".join(filtered), warnings


def redact_context_text(text: str) -> tuple[str, list[str]]:
    """Redact secrets, env content, and private paths from context text.

    Returns (redacted_text, list_of_warnings).
    """
    if not text:
        return text, []

    warnings: list[str] = []

    # Step 1: redact env-like blocks
    text, env_warnings = _redact_env_values(text)
    warnings.extend(env_warnings)

    # Step 2: redact secret patterns
    for pattern, label in SECRET_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            text = pattern.sub(REDACTED, text)
            warnings.append(f"redacted {len(matches)} occurrence(s) of {label}")

    # Step 3: redact home paths
    home_matches = HOME_PATH_PATTERN.findall(text)
    if home_matches:
        text = HOME_PATH_PATTERN.sub(HOME_PLACEHOLDER, text)
        warnings.append(f"redacted {len(home_matches)} absolute home path(s)")

    # Step 4: redact private URLs
    for pattern in PRIVATE_URL_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            text = pattern.sub(REDACTED, text)
            warnings.append(f"redacted {len(matches)} private URL(s)")

    return text, warnings
