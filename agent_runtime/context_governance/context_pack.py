"""ContextPack orchestration and artifact writing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from atomic_io import atomic_write_yaml

from .compression_policy import build_compression_trace
from .context_budget import build_context_budget
from .information_profiler import build_context_profile, load_context_config
from .packers import (
    AbstractReasoningPacker,
    CrawlContextPacker,
    DataContextPacker,
    HistoryPacker,
    ImageContextPacker,
    LogContextPacker,
    LongTextPacker,
    NarrativePacker,
    RepoContextPacker,
    ToolOutputPacker,
    WebContextPacker,
)
from .schemas import ContextBudget, ContextPack, ContextProfile


PACKER_BY_SCENARIO = {
    "short_prompt": LongTextPacker,
    "code_repo": RepoContextPacker,
    "repo_audit": RepoContextPacker,
    "code_debug": LogContextPacker,
    "long_text_report": LongTextPacker,
    "narrative_or_novel": NarrativePacker,
    "image_or_screenshot": ImageContextPacker,
    "web_research": WebContextPacker,
    "crawler_batch": CrawlContextPacker,
    "data_table_or_stream": DataContextPacker,
    "log_analysis": LogContextPacker,
    "abstract_reasoning": AbstractReasoningPacker,
    "tool_output": ToolOutputPacker,
    "task_history": HistoryPacker,
}


def _run_dir(agentlab_root: Path, project: str, task_id: str) -> Path:
    return agentlab_root / "projects" / project / "runs" / task_id


def read_request(run_dir: Path) -> str:
    path = run_dir / "user_request.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_context_artifacts(agentlab_root: Path, project: str, task_id: str, *, request_text: str | None = None, file_hints: list[str] | None = None, source_hints: list[str] | None = None) -> dict[str, Any]:
    run_dir = _run_dir(agentlab_root, project, task_id)
    text = read_request(run_dir) if request_text is None else request_text
    governance = load_context_config(agentlab_root, "context_governance.yml")
    budget_policy = load_context_config(agentlab_root, "context_budget_policy.yml")
    profile = build_context_profile(task_id, text, file_hints=file_hints, source_hints=source_hints, governance_config=governance)
    budget = build_context_budget(profile, text, budget_policy)
    packer_cls = PACKER_BY_SCENARIO.get(profile.information_type, LongTextPacker)
    pack = packer_cls().pack(profile, budget, text, run_dir)
    pack_dict = _bounded_pack(pack.as_dict(), max_chars=50000)
    trace = build_compression_trace(profile.as_dict(), pack_dict)
    return {
        "context_profile": profile.as_dict(),
        "context_budget": budget.as_dict(),
        "context_pack": pack_dict,
        "compression_trace": trace,
    }


def _bounded_pack(pack: dict[str, Any], max_chars: int = 50000) -> dict[str, Any]:
    """Guard against accidentally embedding giant raw text in context_pack.yml."""
    total = len(yaml.safe_dump(pack, sort_keys=False, allow_unicode=True))
    if total <= max_chars:
        return pack
    pack = dict(pack)
    pack.setdefault("warnings", []).append("context_pack truncated by deterministic size guard; use externalized refs for drilldown")
    for section in pack.get("packed_sections", []):
        content = section.get("content", "")
        if len(content) > 2000:
            section["content"] = content[:2000] + "\n...[truncated by P2-G size guard]"
    return pack


def write_context_artifacts(agentlab_root: Path, project: str, task_id: str, *, request_text: str | None = None, file_hints: list[str] | None = None, source_hints: list[str] | None = None) -> dict[str, str]:
    run_dir = _run_dir(agentlab_root, project, task_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts = build_context_artifacts(agentlab_root, project, task_id, request_text=request_text, file_hints=file_hints, source_hints=source_hints)
    written: dict[str, str] = {}
    for key, filename in [
        ("context_profile", "context_profile.yml"),
        ("context_budget", "context_budget.yml"),
        ("context_pack", "context_pack.yml"),
        ("compression_trace", "compression_trace.yml"),
    ]:
        path = run_dir / filename
        atomic_write_yaml(path, artifacts[key])
        written[key] = str(path)
    return written


def load_context_artifacts(run_dir: Path) -> dict[str, Any]:
    data = {}
    for key, filename in [
        ("context_profile", "context_profile.yml"),
        ("context_budget", "context_budget.yml"),
        ("context_pack", "context_pack.yml"),
        ("compression_trace", "compression_trace.yml"),
    ]:
        path = run_dir / filename
        data[key] = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    return data


def context_summary(artifacts: dict[str, Any]) -> str:
    profile = artifacts.get("context_profile") or {}
    budget = artifacts.get("context_budget") or {}
    pack = artifacts.get("context_pack") or {}
    lines = [
        "Context Governance Summary",
        f"- task_id: {profile.get('task_id')}",
        f"- information_type: {profile.get('information_type')}",
        f"- modality: {', '.join(profile.get('modality') or [])}",
        f"- compression: {profile.get('compression_level')} / {profile.get('compression_safety')}",
        f"- strategy: {', '.join(profile.get('recommended_strategy') or [])}",
        f"- budget_policy: {budget.get('budget_policy')} max_input={budget.get('max_input_tokens')}",
        f"- packed_sections: {len(pack.get('packed_sections') or [])}",
        f"- omitted_sections: {len(pack.get('omitted_sections') or [])}",
        f"- externalized_artifacts: {len(pack.get('externalized_artifacts') or [])}",
    ]
    return "\n".join(lines)