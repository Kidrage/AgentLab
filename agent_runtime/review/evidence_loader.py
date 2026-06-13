from __future__ import annotations

from pathlib import Path

from agent_runtime.review.models import ReviewEvidence, ReviewTarget
from agent_runtime.review.policy import ReviewPolicy


TEXT_SUFFIXES = {".md", ".txt", ".yml", ".yaml", ".json", ".toml"}


def safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_text_sample(path: Path, max_bytes: int) -> str:
    if not path.exists() or not path.is_file():
        return ""
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return ""
    data = path.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="replace")


def collect_artifact_evidence(target: ReviewTarget, policy: ReviewPolicy) -> tuple[list[ReviewEvidence], dict[str, str]]:
    target_dir = target.target_dir
    names = list(dict.fromkeys(policy.required_artifacts + policy.optional_artifacts))
    artifacts: list[ReviewEvidence] = []
    text_evidence: dict[str, str] = {}

    for name in names:
        path = target_dir / name
        exists = path.exists() and path.is_file()
        sample = read_text_sample(path, policy.max_text_bytes) if exists else ""
        evidence = ReviewEvidence(
            path=name,
            exists=exists,
            summary=_summarize_text(sample),
            size_bytes=path.stat().st_size if exists else 0,
        )
        artifacts.append(evidence)
        if sample:
            text_evidence[name] = sample

    for explicit_path in (target.handoff_path, target.report_path):
        if not explicit_path:
            continue
        path = explicit_path if explicit_path.is_absolute() else target_dir / explicit_path
        name = safe_relative(path, target_dir)
        if name in text_evidence:
            continue
        exists = path.exists() and path.is_file()
        sample = read_text_sample(path, policy.max_text_bytes) if exists else ""
        artifacts.append(
            ReviewEvidence(
                path=name,
                exists=exists,
                kind="explicit",
                summary=_summarize_text(sample),
                size_bytes=path.stat().st_size if exists else 0,
            )
        )
        if sample:
            text_evidence[name] = sample

    return artifacts, text_evidence


def _summarize_text(text: str, limit: int = 300) -> str:
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
