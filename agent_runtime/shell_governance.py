"""Production safety and native-surface policy for local workflow shells."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


GLOBAL_FORBIDDEN_FLAGS = {
    "-z",
    "--allow-dangerously-skip-permissions",
    "--ignore-rules",
    "--yolo",
    "--dangerously-skip-permissions",
}


@dataclass(frozen=True, slots=True)
class ShellExecutionPlan:
    shell_id: str
    channel: str
    profile_ref: str | None
    native_surface: str
    coordination_semantics: str
    task_packet_required: bool = True
    returned_receipts_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_production_argv(argv: Sequence[str], shell: Mapping[str, Any] | None = None) -> list[str]:
    """Return violations without executing or logging a potentially secret command."""

    values = [str(item) for item in argv]
    forbidden = {item.casefold() for item in GLOBAL_FORBIDDEN_FLAGS}
    forbidden.update(
        str(item).casefold()
        for item in (shell or {}).get("production_forbidden_flags") or []
    )
    issues: list[str] = []
    for index, raw_value in enumerate(values):
        option, separator, inline_value = raw_value.partition("=")
        normalized_option = option.casefold()
        if normalized_option in forbidden:
            issues.append(f"forbidden production flag: {option}")
        next_value = values[index + 1] if index + 1 < len(values) else ""
        option_value = inline_value if separator else next_value
        if (
            normalized_option == "--permission-mode"
            and option_value.casefold() == "bypasspermissions"
        ):
            issues.append("forbidden production permission mode: bypassPermissions")
        if (
            normalized_option == "--approval-mode"
            and option_value.casefold() == "yolo"
        ):
            issues.append("forbidden production approval mode: yolo")
    return list(dict.fromkeys(issues))


def assert_safe_production_argv(argv: Sequence[str], shell: Mapping[str, Any] | None = None) -> None:
    issues = validate_production_argv(argv, shell)
    if issues:
        raise ValueError("; ".join(issues))


def shell_execution_plan(
    shell_id: str,
    *,
    profile_ref: str | None = None,
    heterogeneous_roles: bool = False,
    same_role_parallelism: bool = False,
) -> ShellExecutionPlan:
    """Select a shell-native surface without confusing it with AgentLab memory."""

    if shell_id == "hermes":
        if heterogeneous_roles:
            return ShellExecutionPlan(
                shell_id="hermes",
                channel="cli_control_plane",
                profile_ref=profile_ref,
                native_surface="kanban",
                coordination_semantics="durable_cross_role_work",
            )
        if same_role_parallelism:
            return ShellExecutionPlan(
                shell_id="hermes",
                channel="api_runs",
                profile_ref=profile_ref,
                native_surface="delegate_task",
                coordination_semantics="same_role_short_parallelism",
            )
        return ShellExecutionPlan(
            shell_id="hermes",
            channel="api_runs",
            profile_ref=profile_ref,
            native_surface="run",
            coordination_semantics="single_role_session",
        )
    if shell_id == "claude":
        return ShellExecutionPlan(
            shell_id="claude",
            channel="cli",
            profile_ref=profile_ref,
            native_surface="agents" if same_role_parallelism else "print_mode",
            coordination_semantics="same_role_short_parallelism" if same_role_parallelism else "single_role_session",
        )
    return ShellExecutionPlan(
        shell_id=shell_id,
        channel="cli",
        profile_ref=profile_ref,
        native_surface="single_role_session",
        coordination_semantics="single_role_session",
    )
