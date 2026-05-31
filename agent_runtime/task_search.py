"""AgentLab Task Discovery & Resume Index — Local Search Engine.

Deterministic local search supporting English tokenization and CJK n-grams.
No LLM/API calls required.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml


def _load_search_policy(agentlab_root: Optional[Path] = None) -> dict:
    """Load search config from task_index_policy.yml."""
    if agentlab_root:
        policy_path = agentlab_root / "config" / "task_index_policy.yml"
        if policy_path.exists():
            try:
                policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
                return policy.get("search", {})
            except Exception:
                pass
    return {
        "default_limit": 10,
        "min_score": 1.0,
        "use_char_ngrams_for_cjk": True,
        "cjk_ngram_size": 2,
    }


def tokenize(text: str, *, cjk_ngrams: bool = True) -> list[str]:
    """Tokenize text into search tokens. Handles English and CJK.

    Latin text: lowercase, split on whitespace/punctuation, keep len >= 2.
    CJK text: generate character n-grams.
    """
    if not text:
        return []

    tokens = []

    # Separate CJK and non-CJK segments
    cjk_chars = []
    latin_parts = []
    current_latin = []

    for ch in text:
        if '\u4e00' <= ch <= '\u9fff' or '\u3040' <= ch <= '\u30ff' or '\uac00' <= ch <= '\ud7af':
            if current_latin:
                latin_parts.append(''.join(current_latin))
                current_latin = []
            cjk_chars.append(ch)
        else:
            if ch.isalpha() or ch.isdigit():
                current_latin.append(ch.lower())
            else:
                if current_latin:
                    latin_parts.append(''.join(current_latin))
                    current_latin = []
                # whitespace/punctuation as separator
    if current_latin:
        latin_parts.append(''.join(current_latin))

    # Process Latin tokens
    for part in latin_parts:
        words = re.split(r'[\s_\-\.\,]+', part)
        for w in words:
            w = w.strip()
            if len(w) >= 2:
                tokens.append(w.lower())

    # Process CJK n-grams
    if cjk_ngrams and cjk_chars:
        ngram_size = 2
        for i in range(len(cjk_chars) - ngram_size + 1):
            tokens.append(''.join(cjk_chars[i:i + ngram_size]))

    return tokens


def build_search_blob(record: dict) -> dict[str, str]:
    """Extract searchable text fields from a task record."""
    blob = {}
    blob["task_id"] = record.get("task_id", "")
    blob["title"] = record.get("title", "")
    blob["summary"] = record.get("summary", "")
    blob["query_terms"] = " ".join(record.get("query_terms", []))
    blob["user_request"] = record.get("summary", "")  # reuse summary
    blob["last_event"] = record.get("last_event", "")
    blob["status"] = record.get("status", "")
    # Artifact titles and summaries
    artifact_titles = []
    artifact_summaries = []
    for art in record.get("artifacts", []):
        artifact_titles.append(art.get("title", ""))
        if art.get("summary"):
            artifact_summaries.append(art["summary"])
    blob["artifact_titles"] = " ".join(artifact_titles)
    blob["artifact_summaries"] = " ".join(artifact_summaries)
    blob["file_names"] = " ".join([art.get("path", "") for art in record.get("artifacts", [])])
    return blob


def score_task(record: dict, query: str, policy: Optional[dict] = None) -> float:
    """Score a single task record against a query."""
    if policy is None:
        policy = {}
    field_weights = policy.get("field_weights", {
        "task_id": 3.0, "title": 6.0, "summary": 5.0, "query_terms": 5.0,
        "user_request": 4.0, "last_event": 3.0, "status": 2.0,
        "artifact_titles": 2.0, "artifact_summaries": 2.0, "file_names": 1.0,
    })
    min_score = policy.get("min_score", 1.0)
    use_cjk = policy.get("use_char_ngrams_for_cjk", True)

    query_tokens = tokenize(query, cjk_ngrams=use_cjk)
    query_lower = query.lower()

    if not query_tokens:
        return 0.0

    blob = build_search_blob(record)
    score = 0.0

    # Score each field
    for field_name, text in blob.items():
        weight = field_weights.get(field_name, 1.0)
        if not text:
            continue
        text_lower = text.lower()

        # Exact task_id match
        if field_name == "task_id" and query_lower == text_lower:
            score += 10.0
            continue

        # Token matches
        for token in query_tokens:
            if token in text_lower:
                score += weight * 1.0
            elif len(token) >= 3 and token in text_lower:
                score += weight * 0.6

    # Status filter match
    query_words = query_lower.split()
    status = record.get("status", "")
    for qw in query_words:
        if qw in ("paused", "blocked", "running", "completed", "failed", "archived", "recoverable", "可继续", "继续", "resume"):
            if qw in status.lower():
                score += 2.0

    # can_resume boost
    if record.get("can_resume") and any(w in query_lower for w in ("resume", "continue", "继续", "恢复", "可继续", "resum")):
        score += 3.0

    # Recent update boost (if updated_at exists)
    updated = record.get("updated_at", "")
    if updated:
        try:
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            delta = now - dt
            if delta < timedelta(days=1):
                score += 0.5
            elif delta < timedelta(days=7):
                score += 0.2
            elif delta < timedelta(days=30):
                score += 0.1
        except Exception:
            pass

    return max(score, 0.0)


def search_tasks(
    index: dict,
    query: str,
    *,
    status_filter: Optional[list[str]] = None,
    limit: int = 10,
    agentlab_root: Optional[Path] = None,
) -> list[dict]:
    """Search task index for matching tasks.

    Args:
        index: Parsed task_index.yml data.
        query: Search string (English and/or Chinese).
        status_filter: Only show tasks with these statuses.
        limit: Max results.
        agentlab_root: Path to AgentLab root for policy loading.

    Returns:
        List of task records with added 'score' field, sorted by score desc.
    """
    policy = _load_search_policy(agentlab_root)
    default_limit = policy.get("default_limit", limit)
    if limit <= 0:
        limit = default_limit

    tasks = index.get("tasks", [])
    results = []

    for task in tasks:
        # Status filter
        if status_filter:
            task_status = task.get("status", "")
            if task_status not in status_filter:
                continue

        score = score_task(task, query, policy)
        if score > 0:
            task_with_score = dict(task)
            task_with_score["score"] = round(score, 1)
            results.append(task_with_score)

    # Sort: can_resume first if query hints at resume, then score desc
    query_lower = query.lower()
    resume_hint = any(w in query_lower for w in ("resume", "continue", "继续", "恢复", "可继续", "resum"))

    def sort_key(r: dict) -> tuple:
        s = r.get("score", 0)
        can_res = r.get("can_resume", False)
        # If resume hint, prioritize can_resume
        resume_priority = 1 if (resume_hint and can_res) else 0
        return (-resume_priority, -s)

    results.sort(key=sort_key)
    return results[:limit]