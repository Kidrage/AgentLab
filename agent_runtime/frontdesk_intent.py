"""Frontend-independent deterministic Frontdesk intent compiler."""

from __future__ import annotations

from typing import Any
import re

_STATUS = (
    "status",
    "check",
    "inspect",
    "show",
    "list",
    "help",
    "状态",
    "检查",
    "查看",
    "列出",
)
_MUTATION = (
    "fix",
    "implement",
    "change",
    "edit",
    "write",
    "build",
    "create",
    "update",
    "delete",
    "remove",
    "修复",
    "实现",
    "修改",
    "构建",
    "创建",
    "删除",
)
_EXTERNAL = (
    "deploy",
    "publish",
    "send",
    "upload",
    "push",
    "post",
    "部署",
    "发布",
    "发送",
    "上传",
    "推送",
)
_DESTRUCTIVE = ("delete", "remove", "destroy", "drop", "删除", "销毁")
_AUDIT = ("audit", "review", "verify", "governance", "审计", "复核", "治理")
_PROJECT = (
    "long-term",
    "multi-stage",
    "continuously",
    "ongoing maintenance",
    "program",
    "长期",
    "跨阶段",
    "持续",
    "长期维护",
)
_BOUNDED = ("one file", "single", "bounded", "focused", "一个文件", "单个", "限定")


def _contains(text: str, vocabulary: tuple[str, ...]) -> bool:
    return any(term in text for term in vocabulary)


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def compile_frontdesk_intent(
    request: str,
    *,
    project: str | None = None,
    project_contract_exists: bool = False,
    adapter: str | None = None,
) -> dict[str, Any]:
    """Compile frontdesk-intent/v2; transport adapter is intentionally ignored."""

    del adapter
    normalized = " ".join(str(request).strip().casefold().split())
    if not normalized:
        raise ValueError("frontdesk request must not be empty")
    has_mutation = _contains(normalized, _MUTATION)
    has_external = _contains(normalized, _EXTERNAL)
    has_destructive = _contains(normalized, _DESTRUCTIVE)
    has_audit = _contains(normalized, _AUDIT)
    project_signals = sum(term in normalized for term in _PROJECT)
    bounded = _contains(normalized, _BOUNDED)
    explicit_single_capability = bool(
        re.search(r"\b(?:use|with)\s+(?:one\s+)?(?:skill|mcp)\b", normalized)
    )
    status_only = (
        _contains(normalized, _STATUS)
        and not has_mutation
        and not has_external
        and not has_audit
    )
    evidence: list[str] = []
    approvals: list[str] = []
    capabilities: list[str] = []
    if status_only:
        intent = "deterministic_check"
        task_scope = "read_only_check"
        route_tier = "F0"
        confidence = 0.94
        capabilities = ["read_only_repo_search"]
        evidence.append("rule:deterministic_status_check")
    elif explicit_single_capability and not has_mutation:
        intent = "verified_capability_request"
        task_scope = "single_capability"
        route_tier = "F1"
        confidence = 0.86
        capabilities = ["verified_skill_or_mcp"]
        evidence.append("rule:explicit_single_capability")
    elif project_contract_exists and project_signals >= 2:
        intent = "project_program"
        task_scope = "project_program"
        route_tier = "F4"
        confidence = 0.9
        capabilities = [
            "project_agents",
            "program_governance",
            "durable_state",
            "independent_audit",
        ]
        evidence.extend(
            [
                "rule:explicit_long_running_program",
                "fact:project_contract_exists",
            ]
        )
    elif has_mutation and not has_audit:
        intent = "scoped_change"
        task_scope = "bounded_task"
        route_tier = "F2"
        confidence = 0.84 if bounded else 0.76
        capabilities = ["file_edit", "test_execution", "deterministic_verification"]
        evidence.append("rule:bounded_single_executor_change")
    else:
        intent = "governed_multi_role_request" if has_audit else "ambiguous_request"
        task_scope = "multi_role_closure"
        route_tier = "F3"
        confidence = 0.82 if has_audit else 0.58
        capabilities = ["planning", "scoped_execution", "independent_review"]
        evidence.append(
            "rule:planning_execution_review"
            if has_audit
            else "rule:uncertain_defaults_to_f3"
        )
        if project_signals or _word_count(normalized) < 6:
            approvals.append("project_contract_required_for_f4")
    mutation_scope = "project_scoped" if has_mutation else "none"
    external_effect = "external_write" if has_external else "none"
    if has_external:
        capabilities.append("external_write")
        approvals.append("explicit_external_effect_approval")
    if has_destructive:
        approvals.append("explicit_destructive_action_approval")
    if any(term in normalized for term in ("credential", "secret", "token", "密钥", "凭据")):
        capabilities.append("credential_access")
        approvals.append("credential_scope_approval")
    risk = "critical" if has_destructive and has_external else (
        "high" if has_destructive or has_external else (
            "medium" if has_mutation or route_tier in {"F3", "F4"} else "low"
        )
    )
    return {
        "schema_version": "frontdesk-intent/v2",
        "intent": intent,
        "project": project,
        "task_scope": task_scope,
        "mutation_scope": mutation_scope,
        "external_effect": external_effect,
        "required_capabilities": list(dict.fromkeys(capabilities)),
        "risk": risk,
        "route_tier": route_tier,
        "approval_requirements": list(dict.fromkeys(approvals)),
        "confidence": confidence,
        "evidence": evidence,
    }
