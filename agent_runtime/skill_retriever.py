"""Retrieve active skills relevant to an AgentLab task."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from atomic_io import safe_read_yaml


DEFAULT_POLICY = {
    "enabled": True,
    "retrieval": {
        "max_skills_per_task": 3,
        "min_confidence": 0.0,
        "high_risk_requires_approval": True,
        "default_injected_agents": ["Coder", "TesterAuditor"],
    },
    "matching": {
        "trigger_weight": 3,
        "applies_to_weight": 2,
        "summary_weight": 1,
    },
}


def load_skill_injection_policy(agentlab_root: Path) -> dict[str, Any]:
    data = safe_read_yaml(agentlab_root / "config" / "skill_injection_policy.yml", default={}) or {}
    if not isinstance(data, dict):
        data = {}
    policy = dict(DEFAULT_POLICY)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(policy.get(key), dict):
            merged = dict(policy[key])
            merged.update(value)
            policy[key] = merged
        else:
            policy[key] = value
    return policy


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-zA-Z0-9_+-]+", text.lower()) if len(t) >= 3}


def _contains_phrase(task_text: str, phrase: str) -> bool:
    phrase = str(phrase or "").strip().lower()
    if not phrase:
        return False
    return phrase in task_text.lower()


NEGATION_MARKERS = (
    "not",
    "no",
    "without",
    "is not",
    "isn't",
    "不是",
    "并非",
    "非",
    "不要",
    "无需",
    "不需要",
    "不是一个",
)


def _contains_positive_phrase(task_text: str, phrase: str) -> bool:
    phrase = str(phrase or "").strip().lower()
    if not phrase:
        return False
    lowered = task_text.lower()
    start = lowered.find(phrase)
    while start != -1:
        prefix = lowered[max(0, start - 16):start]
        if not any(marker in prefix for marker in NEGATION_MARKERS):
            return True
        start = lowered.find(phrase, start + len(phrase))
    return False


def active_skill_root(agentlab_root: Path) -> Path:
    return agentlab_root / "skills" / "active"


def normalize_active_skill(agentlab_root: Path, skill_dir: Path) -> dict[str, Any] | None:
    metadata = safe_read_yaml(skill_dir / "metadata.yml", default={}) or {}
    if not isinstance(metadata, dict):
        return None
    status = metadata.get("status", "active")
    if status != "active":
        return None
    skill_id = metadata.get("skill_id") or skill_dir.name
    name = metadata.get("name") or metadata.get("skill_name") or skill_id
    summary = metadata.get("summary") or metadata.get("purpose") or ""
    risk = metadata.get("risk_level") or metadata.get("risk", {}).get("permission_level") or "medium"
    permissions = metadata.get("permissions") or metadata.get("risk") or {}
    triggers = metadata.get("triggers") or metadata.get("trigger_keywords") or metadata.get("trigger") or []
    applies_to = metadata.get("applies_to") or metadata.get("expected_benefit", {}).get("applies_to") or []
    if isinstance(triggers, str):
        triggers = [triggers]
    if isinstance(applies_to, str):
        applies_to = [applies_to]
    return {
        **metadata,
        "skill_id": skill_id,
        "name": name,
        "skill_name": metadata.get("skill_name") or name,
        "status": "active",
        "triggers": list(triggers),
        "applies_to": list(applies_to),
        "summary": summary,
        "load_tokens": int(metadata.get("load_tokens", 1200) or 0),
        "expected_saving_tokens": int(metadata.get("expected_saving_tokens", 3000) or 0),
        "risk_level": risk,
        "permissions": permissions,
        "confidence": float(metadata.get("confidence", 0.5) or 0.0),
        "skill_dir": str(skill_dir),
        "skill_path": str(skill_dir / "SKILL.md"),
    }


def load_active_skills(agentlab_root: Path) -> list[dict[str, Any]]:
    root = active_skill_root(agentlab_root)
    if not root.exists():
        return []
    skills = []
    for skill_dir in sorted(root.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill = normalize_active_skill(agentlab_root, skill_dir)
        if skill:
            skills.append(skill)
    return skills


def score_skill_for_task(skill: dict[str, Any], task_text: str, policy: dict[str, Any]) -> tuple[int, list[str]]:
    matching = policy.get("matching", {})
    score = 0
    reasons: list[str] = []
    task_tokens = _tokens(task_text)
    for trigger in skill.get("triggers", []):
        trigger_text = str(trigger)
        trigger_tokens = _tokens(trigger_text)
        if _contains_positive_phrase(task_text, trigger_text) or (
            task_tokens.intersection(trigger_tokens) and not _contains_phrase(task_text, trigger_text)
        ):
            score += int(matching.get("trigger_weight", 3))
            reasons.append(f"matched trigger: {trigger_text}")
    for item in skill.get("applies_to", []):
        item_text = str(item)
        item_tokens = _tokens(item_text)
        if _contains_positive_phrase(task_text, item_text) or (
            task_tokens.intersection(item_tokens) and not _contains_phrase(task_text, item_text)
        ):
            score += int(matching.get("applies_to_weight", 2))
            reasons.append(f"matched applies_to: {item_text}")
    summary_tokens = _tokens(str(skill.get("summary", "")))
    shared = sorted(task_tokens.intersection(summary_tokens))
    if shared:
        score += int(matching.get("summary_weight", 1))
        reasons.append(f"summary overlap: {', '.join(shared[:5])}")
    return score, reasons


def match_active_skills(
    agentlab_root: Path,
    *,
    task_text: str,
    policy: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    policy = policy or load_skill_injection_policy(agentlab_root)
    if not policy.get("enabled", True):
        return {"selected": [], "rejected": []}
    retrieval = policy.get("retrieval", {})
    max_skills = int(retrieval.get("max_skills_per_task", 3))
    min_confidence = float(retrieval.get("min_confidence", 0.0))
    high_risk_requires_approval = bool(retrieval.get("high_risk_requires_approval", True))
    injected_agents = list(retrieval.get("default_injected_agents", ["Coder", "TesterAuditor"]))

    candidates = []
    rejected: list[dict[str, Any]] = []
    for skill in load_active_skills(agentlab_root):
        if skill.get("default_injection") is False:
            rejected.append({
                "skill_id": skill["skill_id"],
                "name": skill["name"],
                "reason": "default_injection is false",
            })
            continue
        score, reasons = score_skill_for_task(skill, task_text, policy)
        if score <= 0:
            rejected.append({
                "skill_id": skill["skill_id"],
                "name": skill["name"],
                "reason": "no trigger or task-goal match",
            })
            continue
        if skill.get("confidence", 0.0) < min_confidence:
            rejected.append({
                "skill_id": skill["skill_id"],
                "name": skill["name"],
                "reason": f"confidence below policy minimum ({skill.get('confidence')} < {min_confidence})",
            })
            continue
        if str(skill.get("risk_level", "")).lower() == "high" and high_risk_requires_approval:
            rejected.append({
                "skill_id": skill["skill_id"],
                "name": skill["name"],
                "reason": "high-risk skill requires approval before injection",
                "load_tokens": skill.get("load_tokens", 0),
                "expected_saving_tokens": skill.get("expected_saving_tokens", 0),
                "risk_level": skill.get("risk_level", "high"),
                "confidence": skill.get("confidence", 0.0),
                "skill_path": skill.get("skill_path"),
                "requires_approval": True,
                "approval_type": "SKILL_INJECTION_APPROVAL",
            })
            continue
        candidates.append((score, skill, reasons))

    candidates.sort(key=lambda item: (item[0], item[1].get("expected_saving_tokens", 0)), reverse=True)
    selected = []
    for score, skill, reasons in candidates[:max_skills]:
        selected.append({
            "skill_id": skill["skill_id"],
            "name": skill["name"],
            "reason": "; ".join(reasons) or f"score={score}",
            "load_tokens": skill.get("load_tokens", 0),
            "expected_saving_tokens": skill.get("expected_saving_tokens", 0),
            "injected_into": injected_agents,
            "risk_level": skill.get("risk_level", "medium"),
            "confidence": skill.get("confidence", 0.0),
            "skill_path": skill.get("skill_path"),
        })
    for _score, skill, _reasons in candidates[max_skills:]:
        rejected.append({
            "skill_id": skill["skill_id"],
            "name": skill["name"],
            "reason": f"max skills per task exceeded ({max_skills})",
        })
    return {"selected": selected, "rejected": rejected}
