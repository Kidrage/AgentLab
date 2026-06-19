from __future__ import annotations

from fnmatch import fnmatch


def inspect_changed_files(changed_files: list[str], allowed_files: list[str], forbidden_files: list[str]) -> dict:
    forbidden_hits = []
    outside_allowed = []
    for path in changed_files:
        if any(fnmatch(path, pattern) for pattern in forbidden_files):
            forbidden_hits.append(path)
        if allowed_files and not any(fnmatch(path, pattern) for pattern in allowed_files):
            outside_allowed.append(path)
    return {
        "verdict": "PASS" if not forbidden_hits and not outside_allowed else "FAIL",
        "forbidden_hits": forbidden_hits,
        "outside_allowed": outside_allowed,
    }
