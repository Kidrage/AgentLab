"""ContextPack orchestration and artifact writing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from atomic_io import atomic_write_yaml
from agent_runtime.knowledge_system import (
    InsufficientEvidenceError,
    KnowledgeTaskRequest,
    PreparedKnowledgeContext,
    prepare_task,
)
from agent_runtime.knowledge_system.config import load_knowledge_config

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
    pack_dict = pack.as_dict()
    knowledge_context = _prepare_knowledge_context(
        agentlab_root,
        project,
        task_id,
        text,
        profile.information_type,
        file_hints=file_hints,
    )
    if knowledge_context is not None and knowledge_context.mode in {"assist", "enforce"}:
        _inject_knowledge_evidence(pack_dict, knowledge_context)
    pack_dict = _bounded_pack(pack_dict, max_chars=50000)
    trace = build_compression_trace(profile.as_dict(), pack_dict)
    artifacts = {
        "context_profile": profile.as_dict(),
        "context_budget": budget.as_dict(),
        "context_pack": pack_dict,
        "compression_trace": trace,
    }
    if knowledge_context is not None:
        artifacts["knowledge_context"] = knowledge_context.as_dict()
    return artifacts


def _prepare_knowledge_context(
    agentlab_root: Path,
    project: str,
    task_id: str,
    request_text: str,
    information_type: str,
    *,
    file_hints: list[str] | None,
) -> PreparedKnowledgeContext | None:
    config = load_knowledge_config(agentlab_root)
    if config.mode == "off":
        return None
    prepared = prepare_task(
        KnowledgeTaskRequest(
            agentlab_root=agentlab_root,
            project=project,
            task_id=task_id,
            request_text=request_text,
            domain=_knowledge_domain(information_type),
            file_hints=tuple(file_hints or ()),
        )
    )
    if config.mode == "enforce" and prepared.status != "READY":
        raise InsufficientEvidenceError(prepared)
    return prepared


def _knowledge_domain(information_type: str) -> str:
    if information_type in {"code_repo", "repo_audit", "code_debug"}:
        return "code_engineering"
    if information_type == "narrative_or_novel":
        return "longform_narrative"
    if information_type == "web_research":
        return "research"
    if information_type == "image_or_screenshot":
        return "media_production"
    return "general_production"


def _inject_knowledge_evidence(
    pack: dict[str, Any], prepared: PreparedKnowledgeContext
) -> None:
    trace_id = prepared.evidence_bundle.trace.trace_id
    for item in prepared.evidence_bundle.items:
        pack.setdefault("packed_sections", []).append(
            {
                "section_id": f"knowledge_evidence_{item.rank}",
                "title": f"Governed knowledge evidence {item.rank}",
                "content": f"[{item.namespace}] {item.locator}\n{item.excerpt}",
                "tokens_estimate": max(1, (len(item.excerpt) + 3) // 4),
                "source_refs": [item.locator],
            }
        )
        pack.setdefault("evidence_refs", []).append(
            {
                "path": item.source.path,
                "kind": "knowledge_evidence",
                "evidence_id": item.evidence_id,
                "namespace": item.namespace,
                "locator": item.locator,
                "content_hash": item.source.content_hash,
                "authority": item.authority,
                "lifecycle": item.lifecycle,
                "channel": item.channel,
                "rank": item.rank,
                "retrieval_trace_id": trace_id,
                "index_snapshot": prepared.evidence_bundle.trace.index_snapshot,
            }
        )
    if prepared.status != "READY":
        pack.setdefault("warnings", []).append(
            "Knowledge retrieval returned INSUFFICIENT_EVIDENCE; assist mode did not block execution."
        )


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
        ("knowledge_context", "knowledge_context.yml"),
    ]:
        if key not in artifacts:
            continue
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
        ("knowledge_context", "knowledge_context.yml"),
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
    knowledge = artifacts.get("knowledge_context") or {}
    if knowledge:
        bundle = knowledge.get("evidence_bundle") or {}
        lines.extend(
            [
                f"- knowledge_mode: {knowledge.get('mode')}",
                f"- knowledge_status: {knowledge.get('status')}",
                f"- knowledge_evidence: {len(bundle.get('items') or [])}",
            ]
        )
    return "\n".join(lines)
