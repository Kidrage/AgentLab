"""Narrative delivery commands for longform writing projects."""

from __future__ import annotations

import os
from pathlib import Path

import typer
import yaml
from rich.console import Console

from atomic_io import atomic_write_yaml
from agent_runtime.policies import resolve_agentlab_root
from agent_runtime.narrative.assembly import (
    NarrativeAssemblyError,
    assemble_candidate_chapters,
)
from agent_runtime.narrative.acceptance_ladder import (
    build_narrative_acceptance_status,
)
from agent_runtime.narrative.authorial_audit import (
    build_authorial_audit_plan,
    compile_senior_editor_revision_contracts,
    execute_authorial_reviews,
)
from agent_runtime.narrative.author_team import (
    load_author_team_contract as resolve_author_team_contract,
    materialize_author_team_contract,
    register_author_team_proposal,
    select_author_team,
    validate_author_team_contract,
)
from agent_runtime.project_agents.registry import AgentRegistryError
from agent_runtime.narrative.blueprint_validation import (
    materialize_crown_blueprint,
    seal_crown_blueprint,
    validate_crown_blueprint,
)
from agent_runtime.narrative.blueprint_lifecycle import (
    publish_blueprint_change,
    seal_project_blueprint,
    validate_project_blueprint,
)
from agent_runtime.narrative.state_store import (
    NarrativeStateError,
    NarrativeStateStore,
)
from agent_runtime.narrative.user_acceptance import (
    record_candidate_acceptance,
)
from agent_runtime.narrative.planning_window import (
    PlanningWindowError,
    activate_planning_window,
    complete_planning_window_chapter,
    propose_planning_window,
    seal_planning_window,
)
from agent_runtime.task_runtime_v2.deterministic_executor import (
    DeterministicToolExecutor,
)
from agent_runtime.narrative.role_context import compile_role_context_pack
from agent_runtime.narrative.preferences import (
    CROWN_AUTHORIAL_PRIOR,
    PreferenceStore,
    classify_feedback,
)
from agent_runtime.narrative.quality.live_editor_preflight import (
    preflight_literary_ab_review,
)
from agent_runtime.narrative.quality.live_editor_runtime import (
    run_literary_ab_review,
)
from agent_runtime.narrative.task_packet import (
    append_narrative_instruction,
    compile_narrative_task_packet,
)
from agent_runtime.narrative_delivery import (
    run_narrative_doctor,
    validate_narrative_delivery,
    write_chapter_packet,
    write_narrative_delivery_receipt,
)


def register_narrative_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    narrative_app = typer.Typer(help="Longform narrative delivery commands.", no_args_is_help=True)
    planning_window_app = typer.Typer(
        help="Governed rolling narrative planning-window lifecycle.",
        no_args_is_help=True,
    )
    author_team_app = typer.Typer(
        help="Validate and select professional narrative author roles.",
        no_args_is_help=True,
    )
    context_app = typer.Typer(
        help="Compile role-scoped, evidence-bound narrative context.",
        no_args_is_help=True,
    )
    acceptance_app = typer.Typer(
        help="Verify evidence-bound P0-P5 narrative acceptance.",
        no_args_is_help=True,
    )
    candidate_app = typer.Typer(
        help="Govern Candidate Set user acceptance.",
        no_args_is_help=True,
    )
    feedback_app = typer.Typer(
        help="Append, inspect, and rollback authorial preference events.",
        no_args_is_help=True,
    )

    def active_project_root() -> Path:
        configured = os.environ.get("AGENTLAB_ROOT")
        return resolve_agentlab_root(configured) if configured else project_root

    @candidate_app.command("accept")
    def accept_candidate_set_command(
        project: str = typer.Option(..., "--project"),
        manifest_path: Path = typer.Option(..., "--manifest-path"),
        actor_id: str = typer.Option(..., "--actor-id"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
        approved_at: str = typer.Option(..., "--approved-at"),
        signature_path: Path = typer.Option(..., "--signature-path"),
    ) -> None:
        """Append one authenticated local-user Candidate Set acceptance."""

        try:
            result = record_candidate_acceptance(
                active_project_root() / "projects" / project,
                manifest_path=manifest_path,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                approved_at=approved_at,
                signature_path=signature_path,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    def blueprint_schema(project: str) -> str:
        authority = (
            active_project_root()
            / "projects"
            / project
            / "production"
            / "blueprint_authority.yml"
        )
        try:
            value = yaml.safe_load(authority.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            return ""
        return str(value.get("schema_version") or "") if isinstance(value, dict) else ""

    def crown_blueprint_range(project: str) -> tuple[int, int]:
        authority = (
            active_project_root()
            / "projects"
            / project
            / "production"
            / "blueprint_authority.yml"
        )
        try:
            value = yaml.safe_load(authority.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError(
                "cannot resolve chapter range from production/blueprint_authority.yml"
            ) from exc
        scope = value.get("scope") if isinstance(value, dict) else None
        chapter_range = (
            scope.get("detailed_chapter_contract_range")
            if isinstance(scope, dict)
            else None
        )
        if (
            not isinstance(chapter_range, list)
            or len(chapter_range) != 2
            or any(
                isinstance(item, bool) or not isinstance(item, int) or item < 1
                for item in chapter_range
            )
            or chapter_range[0] > chapter_range[1]
        ):
            raise ValueError(
                "production/blueprint_authority.yml has no valid detailed chapter range"
            )
        return chapter_range[0], chapter_range[1]

    @narrative_app.command("doctor")
    def doctor(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
    ) -> None:
        """Audit narrative project readiness and recent chapter delivery receipts."""
        result = run_narrative_doctor(project_root, project)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result.get("status") != "pass":
            raise typer.Exit(code=1)

    @narrative_app.command("prepare-chapter")
    def prepare_chapter(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        chapter: int = typer.Option(..., "--chapter", min=1, help="Chapter number."),
        task_id: str = typer.Option(..., "--task-id", help="Run id under projects/<Project>/runs/."),
    ) -> None:
        """Write a chapter packet from current production facts and prior chapters."""
        result = write_chapter_packet(project_root, project, task_id, chapter)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @narrative_app.command("review")
    def review(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        task_id: str = typer.Option(..., "--task-id", help="Run id under projects/<Project>/runs/."),
        write_receipt: bool = typer.Option(True, "--write-receipt/--no-write-receipt", help="Write narrative_delivery_receipt.yml."),
    ) -> None:
        """Validate narrative delivery outputs and block failed fiction reviews."""
        run_dir = project_root / "projects" / project / "runs" / task_id
        result = write_narrative_delivery_receipt(run_dir) if write_receipt else validate_narrative_delivery(run_dir)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        valid = result.get("delivery_check", result).get("valid")
        if not valid:
            raise typer.Exit(code=1)

    @narrative_app.command("assemble")
    def assemble(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        audit_manifest: Path = typer.Option(
            ..., "--audit-manifest", help="Passed continuous-audit manifest."
        ),
        output: Path = typer.Option(..., "--output", help="UTF-8 omnibus TXT path."),
        delivery_manifest: Path = typer.Option(
            ..., "--delivery-manifest", help="Assembly receipt YAML path."
        ),
    ) -> None:
        """Assemble only hash-bound candidate chapters approved by one audit."""
        try:
            result = assemble_candidate_chapters(
                project_root,
                project=project,
                audit_manifest=audit_manifest,
                output_path=output,
                delivery_manifest=delivery_manifest,
            )
        except NarrativeAssemblyError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @narrative_app.command("validate-blueprint")
    def validate_blueprint(
        project: str = typer.Option("Crown_of_Ash", "--project"),
        chapter_start: int | None = typer.Option(None, "--chapter-start", min=1),
        chapter_end: int | None = typer.Option(None, "--chapter-end", min=1),
    ) -> None:
        """Validate the selected Crown or project-specific narrative blueprint."""
        runtime_root = active_project_root()
        if blueprint_schema(project) == "narrative-blueprint-authority/v1":
            result = validate_project_blueprint(
                runtime_root,
                project=project,
            )
        else:
            try:
                authority_start, authority_end = crown_blueprint_range(project)
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc
            selected_start = (
                authority_start if chapter_start is None else chapter_start
            )
            selected_end = authority_end if chapter_end is None else chapter_end
            if selected_start > selected_end:
                raise typer.BadParameter(
                    "--chapter-start must not be greater than --chapter-end"
                )
            result = validate_crown_blueprint(
                runtime_root,
                project=project,
                chapter_start=selected_start,
                chapter_end=selected_end,
            )
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result["status"] != "pass":
            raise typer.Exit(code=1)

    @narrative_app.command("seal-blueprint")
    def seal_blueprint(
        project: str = typer.Option("Crown_of_Ash", "--project"),
        source_task: str | None = typer.Option(None, "--source-task"),
        source_run_artifact: str | None = typer.Option(
            None,
            "--source-run-artifact",
        ),
        allow_registered_blueprint_drift: bool = typer.Option(
            False,
            "--allow-registered-blueprint-drift",
            help=(
                "Administrative recovery only: reseal an externally audited, "
                "authorized drift. This is not a blueprint update interface."
            ),
        ),
    ) -> None:
        """Validate and seal the selected Crown or project-specific blueprint."""
        try:
            if blueprint_schema(project) == "narrative-blueprint-authority/v1":
                if not source_task:
                    raise ValueError(
                        "generic project-specific sealing requires --source-task"
                    )
                if source_run_artifact or allow_registered_blueprint_drift:
                    raise ValueError(
                        "generic sealing does not accept Crown recovery options"
                    )
                result = seal_project_blueprint(
                    project_root,
                    project=project,
                    source_task=source_task,
                )
            else:
                result = seal_crown_blueprint(
                    project_root,
                    project=project,
                    source_task=source_task,
                    source_run_artifact=source_run_artifact,
                    allow_registered_blueprint_drift=allow_registered_blueprint_drift,
                )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @narrative_app.command("publish-blueprint-change")
    def publish_blueprint_change_command(
        project: str = typer.Option(..., "--project"),
        manifest: Path = typer.Option(
            ...,
            "--manifest",
            help="Runtime v2 artifacts/blueprint_change_set.yml.",
        ),
        acceptance_receipt: Path = typer.Option(
            ...,
            "--acceptance-receipt",
            help="Hash-bound user and expert acceptance receipt.",
        ),
    ) -> None:
        """CAS-publish one validated blueprint change and archive the previous truth."""
        try:
            result = publish_blueprint_change(
                project_root,
                project=project,
                manifest_path=manifest,
                acceptance_receipt_path=acceptance_receipt,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    def load_request(path: Path) -> dict:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise typer.BadParameter(f"cannot read narrative request: {exc}") from exc
        if not isinstance(value, dict):
            raise typer.BadParameter("narrative request must be a mapping")
        return value

    @narrative_app.command("compile-task-packet")
    def compile_task_packet_command(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        request: Path = typer.Option(
            ...,
            "--request",
            help="Structured narrative request YAML.",
        ),
    ) -> None:
        """Create one append-only Runtime v2 narrative Task and expert DAG."""
        try:
            result = compile_narrative_task_packet(
                project_root,
                project=project,
                task_id=task_id,
                request=load_request(request),
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    @narrative_app.command("append-task-instruction")
    def append_task_instruction_command(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        instruction_id: str = typer.Option(..., "--instruction-id"),
        request: Path = typer.Option(
            ...,
            "--request",
            help="Structured narrative request YAML.",
        ),
    ) -> None:
        """Append a prompt event without overwriting prior narrative instructions."""
        try:
            result = append_narrative_instruction(
                project_root,
                project=project,
                task_id=task_id,
                instruction_id=instruction_id,
                request=load_request(request),
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    @narrative_app.command("materialize-blueprint")
    def materialize_blueprint(
        bundle: Path = typer.Option(..., "--bundle"),
        project: str = typer.Option("Crown_of_Ash", "--project"),
    ) -> None:
        """Initialize an empty production root from a validated blueprint bundle."""
        try:
            result = materialize_crown_blueprint(
                project_root,
                bundle_path=bundle,
                project=project,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @narrative_app.command("commit-fact-authority")
    def commit_fact_authority(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
    ) -> None:
        """Commit the one artifact-index-selected fact authority revision."""
        project_dir = project_root / "projects" / project
        store = NarrativeStateStore(
            project_dir / "project_brain",
            project=project,
        )
        try:
            result = store.commit_fact_authority(
                project_dir / "production" / "fact_authority.yml"
            )
        except (OSError, ValueError, NarrativeStateError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @planning_window_app.command("propose")
    def propose_planning_window_command(
        project: str = typer.Option(..., "--project"),
        output: Path = typer.Option(..., "--output"),
        locked_size: int = typer.Option(10, "--locked-size", min=8, max=10),
    ) -> None:
        """Build a candidate window from current hash-bound chapter contracts."""
        try:
            result = propose_planning_window(
                project_root,
                project=project,
                locked_size=locked_size,
            )
            atomic_write_yaml(output, result)
        except (OSError, PlanningWindowError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @planning_window_app.command("seal")
    def seal_planning_window_command(
        proposal: Path = typer.Option(..., "--proposal"),
        supersede_reason: str | None = typer.Option(
            None,
            "--supersede-reason",
        ),
    ) -> None:
        """Seal a proposal as the sole current planning window."""
        try:
            raw = yaml.safe_load(proposal.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise PlanningWindowError("proposal must be a mapping")
            result = seal_planning_window(
                project_root,
                proposal=raw,
                supersede_reason=supersede_reason,
            )
        except (OSError, UnicodeError, yaml.YAMLError, PlanningWindowError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @planning_window_app.command("activate")
    def activate_planning_window_command(
        project: str = typer.Option(..., "--project"),
    ) -> None:
        """Activate the sole sealed planning window."""
        try:
            result = activate_planning_window(project_root, project=project)
        except PlanningWindowError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @planning_window_app.command("complete")
    def complete_planning_window_command(
        project: str = typer.Option(..., "--project"),
        chapter: int = typer.Option(..., "--chapter", min=1),
        horizon_chapter: int = typer.Option(
            ...,
            "--horizon-chapter",
            min=1,
            help="New far-horizon chapter contract already produced by planning.",
        ),
    ) -> None:
        """Accept the next locked chapter and extend the planning horizon."""
        try:
            result = complete_planning_window_chapter(
                project_root,
                project=project,
                chapter=chapter,
                horizon_chapter=horizon_chapter,
            )
        except PlanningWindowError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    def load_author_team_contract(path: Path | None) -> dict:
        selected = path or (
            project_root / "config" / "narrative_author_team.yml"
        )
        try:
            value = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise typer.BadParameter(f"cannot read author-team contract: {exc}") from exc
        if not isinstance(value, dict):
            raise typer.BadParameter("author-team contract must be a mapping")
        if value.get("schema_version") == "narrative-author-team/v2":
            return value
        try:
            return resolve_author_team_contract(
                project_root,
                composition_path=selected,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    @author_team_app.command("validate")
    def validate_author_team_command(
        contract: Path | None = typer.Option(None, "--contract"),
    ) -> None:
        """Validate all v2 professional roles and separation-of-duty gates."""
        result = validate_author_team_contract(
            load_author_team_contract(contract)
        )
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )
        if result["status"] != "pass":
            raise typer.Exit(code=1)

    @author_team_app.command("select")
    def select_author_team_command(
        contract: Path | None = typer.Option(None, "--contract"),
        risk: list[str] | None = typer.Option(None, "--risk"),
    ) -> None:
        """Select the smallest role subgraph for declared chapter risks."""
        result = select_author_team(
            load_author_team_contract(contract),
            risk_flags=risk or [],
        )
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )
        if result["status"] != "pass":
            raise typer.Exit(code=1)

    @author_team_app.command("initialize")
    def initialize_author_team_command(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
    ) -> None:
        """Write a run-local author-team registration proposal."""
        try:
            result = materialize_author_team_contract(
                project_root,
                project=project,
                task_id=task_id,
            )
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    @author_team_app.command("register")
    def register_author_team_command(
        project: str = typer.Option(..., "--project"),
        proposal: Path = typer.Option(..., "--proposal"),
        proposal_sha256: str = typer.Option(..., "--proposal-sha256"),
        expected_snapshot_id: str = typer.Option(
            ...,
            "--expected-snapshot-id",
        ),
        actor_id: str = typer.Option(..., "--actor-id"),
        approved: bool = typer.Option(False, "--approved"),
    ) -> None:
        """Atomically register one explicitly approved run-local proposal."""
        try:
            result = register_author_team_proposal(
                project_root,
                project=project,
                proposal_path=proposal,
                expected_proposal_sha256=proposal_sha256,
                expected_snapshot_id=expected_snapshot_id,
                actor_id=actor_id,
                approved=approved,
            )
        except (AgentRegistryError, OSError, ValueError, yaml.YAMLError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    @context_app.command("compile")
    def compile_role_context_command(
        request: Path = typer.Option(..., "--request"),
    ) -> None:
        """Compile one role context pack from a v1 YAML request."""

        try:
            value = yaml.safe_load(request.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise typer.BadParameter(f"cannot read context request: {exc}") from exc
        if not isinstance(value, dict):
            raise typer.BadParameter("context request must be a mapping")
        if value.get("schema_version") != "role-context-compile-request/v1":
            raise typer.BadParameter("unsupported context request schema")

        try:
            root = active_project_root()
            project = str(value["project"])
            task_id = str(value["task_id"])
            source_root = root / "projects" / project

            def source_path(field: str) -> Path:
                path = Path(str(value[field]))
                return path.resolve() if path.is_absolute() else source_root / path

            candidates = value.get("evidence_candidates")
            if not isinstance(candidates, list):
                raise ValueError("evidence_candidates must be a list")
            normalized_candidates: list[dict] = []
            for item in candidates:
                if not isinstance(item, dict):
                    raise ValueError("each evidence candidate must be a mapping")
                normalized = dict(item)
                candidate_path = Path(str(normalized.get("path") or ""))
                normalized["path"] = (
                    candidate_path.resolve()
                    if candidate_path.is_absolute()
                    else source_root / candidate_path
                )
                normalized_candidates.append(normalized)
            result = compile_role_context_pack(
                root,
                project=project,
                task_id=task_id,
                role_id=str(value["role_id"]),
                context_bundle_manifest=source_path("context_bundle_manifest"),
                evidence_candidates=normalized_candidates,
                token_budget=int(value["token_budget"]),
                minimum_evidence_items=int(
                    value.get("minimum_evidence_items", 1)
                ),
                audit_chapter_id=(
                    int(value["audit_chapter_id"])
                    if value.get("audit_chapter_id") is not None
                    else None
                ),
                audit_candidate_path=(
                    source_path("audit_candidate_path")
                    if value.get("audit_candidate_path") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise typer.BadParameter(f"invalid context request: {exc}") from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip(),
            soft_wrap=True,
        )
        if result["status"] == "blocked":
            raise typer.Exit(code=1)

    @narrative_app.command("audit")
    def authorial_audit_command(
        request: Path = typer.Option(..., "--request"),
    ) -> None:
        """Plan authorial review or compile strict findings into revisions."""

        try:
            value = yaml.safe_load(request.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise typer.BadParameter(f"cannot read audit request: {exc}") from exc
        if not isinstance(value, dict):
            raise typer.BadParameter("audit request must be a mapping")
        if value.get("schema_version") != "authorial-audit-request/v1":
            raise typer.BadParameter("unsupported audit request schema")
        try:
            root = active_project_root()
            project = str(value["project"])
            task_id = str(value["task_id"])
            project_dir = root / "projects" / project
            action = str(value["action"])
            if action == "plan":
                candidate = Path(str(value["candidate_path"]))
                if not candidate.is_absolute():
                    candidate = project_dir / candidate
                risks = value.get("risk_flags", [])
                if not isinstance(risks, list):
                    raise ValueError("risk_flags must be a list")
                result = build_authorial_audit_plan(
                    root,
                    project=project,
                    task_id=task_id,
                    chapter_id=int(value["chapter_id"]),
                    candidate_path=candidate,
                    risk_flags=[str(item) for item in risks],
                )
            elif action == "execute_reviews":
                candidate = Path(str(value["candidate_path"]))
                if not candidate.is_absolute():
                    candidate = project_dir / candidate
                risks = value.get("risk_flags", [])
                if not isinstance(risks, list):
                    raise ValueError("risk_flags must be a list")
                raw_context_packs = value.get("context_pack_paths")
                if not isinstance(raw_context_packs, dict):
                    raise ValueError("context_pack_paths must be a mapping")
                context_pack_paths = {}
                for role_id, path_value in raw_context_packs.items():
                    pack_path = Path(str(path_value))
                    if not pack_path.is_absolute():
                        pack_path = project_dir / pack_path
                    context_pack_paths[str(role_id)] = pack_path
                result = execute_authorial_reviews(
                    root,
                    project=project,
                    task_id=task_id,
                    chapter_id=int(value["chapter_id"]),
                    candidate_path=candidate,
                    risk_flags=[str(item) for item in risks],
                    context_pack_paths=context_pack_paths,
                    outbound_expires_at=str(
                        value.get("outbound_expires_at") or ""
                    ),
                    execution_ordinal=int(
                        value.get("execution_ordinal", 1)
                    ),
                )
            elif action == "compile_revision":
                candidate = Path(str(value["candidate_path"]))
                if not candidate.is_absolute():
                    candidate = project_dir / candidate
                findings = value.get("findings")
                constraints = value.get("constraints")
                if not isinstance(findings, list) or not all(
                    isinstance(item, dict) for item in findings
                ):
                    raise ValueError("findings must be a list of mappings")
                if not isinstance(constraints, dict):
                    raise ValueError("constraints must be a mapping")
                result = compile_senior_editor_revision_contracts(
                    findings,
                    agentlab_root=root,
                    project=project,
                    task_id=task_id,
                    candidate_path=candidate,
                    constraints=constraints,
                )
            elif action == "execute_blind_ab":
                spec = Path(str(value["spec_path"]))
                if not spec.is_absolute():
                    spec = project_dir / spec
                preflight = preflight_literary_ab_review(
                    spec,
                    repository_root=root,
                )
                if (
                    preflight.get("project") != project
                    or preflight.get("task_id") != task_id
                    or preflight.get("status") != "ready"
                ):
                    raise ValueError("blind A/B preflight identity mismatch")
                review = run_literary_ab_review(
                    root,
                    project=project,
                    task_id=task_id,
                )
                result = {
                    "schema_version": "authorial-blind-ab-execution/v1",
                    "status": review.get("status"),
                    "project": project,
                    "task_id": task_id,
                    "preflight": preflight,
                    "review": review,
                }
            else:
                raise ValueError(f"unsupported audit action: {action}")
        except (KeyError, TypeError, ValueError) as exc:
            raise typer.BadParameter(f"invalid audit request: {exc}") from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip(),
            soft_wrap=True,
        )
        if result["status"] == "blocked":
            raise typer.Exit(code=1)

    @acceptance_app.command("status")
    def narrative_acceptance_status_command(
        project: str = typer.Option(..., "--project"),
        evidence_dir: Path | None = typer.Option(None, "--evidence-dir"),
    ) -> None:
        """Report the highest verified stage without inferring missing proof."""

        root = active_project_root()
        selected_project = root / "projects" / project
        selected_evidence = (
            evidence_dir
            if evidence_dir is not None
            else selected_project / "acceptance" / "narrative"
        )
        result = build_narrative_acceptance_status(
            root,
            project=project,
            project_root=selected_project,
            evidence_dir=selected_evidence,
        )
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip(),
            soft_wrap=True,
        )
        if result["status"] == "blocked":
            raise typer.Exit(code=1)

    @acceptance_app.command("project-metric-universe")
    def project_metric_universe_command(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        attempt_id: str = typer.Option(..., "--attempt-id"),
        metric_id: str = typer.Option(..., "--metric-id"),
        work_item_id: str = typer.Option(..., "--work-item-id"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        """Execute the allowlisted projector as a real TaskRuntime Attempt."""

        try:
            result = DeterministicToolExecutor(
                active_project_root(),
                project=project,
            ).execute_metric_universe(
                task_id=task_id,
                work_item_id=work_item_id,
                attempt_id=attempt_id,
                metric_id=metric_id,
                idempotency_key=idempotency_key,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip(),
            soft_wrap=True,
        )

    def preference_store(project: str) -> PreferenceStore:
        store = PreferenceStore(
            project_root / "projects" / project / "project_brain",
            project=project,
        )
        store.initialize(CROWN_AUTHORIAL_PRIOR)
        return store

    @feedback_app.command("intake")
    def intake_feedback_command(
        project: str = typer.Option(..., "--project"),
        text: str = typer.Option(..., "--text"),
        scope: str = typer.Option(..., "--scope"),
        scope_id: str = typer.Option(..., "--scope-id"),
        source: str = typer.Option("user", "--source"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
        expires_after_chapter: int | None = typer.Option(
            None,
            "--expires-after-chapter",
            min=1,
        ),
        polarity: int | None = typer.Option(None, "--polarity"),
    ) -> None:
        """Classify feedback and append one reversible preference event."""
        try:
            classified = classify_feedback(text, polarity=polarity)
            if classified["supervisor_review_required"]:
                result = {
                    **classified,
                    "status": "needs_supervisor_review",
                    "feedback_recorded": False,
                }
                console.print(
                    yaml.safe_dump(
                        result,
                        sort_keys=False,
                        allow_unicode=True,
                    ).rstrip()
                )
                raise typer.Exit(code=2)
            result = preference_store(project).intake(
                source=source,
                scope_level=scope,
                scope_id=scope_id,
                classifications=classified["classifications"],
                idempotency_key=idempotency_key,
                expires_after_chapter=expires_after_chapter,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    @feedback_app.command("profile")
    def preference_profile_command(
        project: str = typer.Option(..., "--project"),
        chapter: int | None = typer.Option(None, "--chapter", min=1),
        arc: str | None = typer.Option(None, "--arc"),
        window: str | None = typer.Option(None, "--window"),
        chapter_scope: str | None = typer.Option(None, "--chapter-scope"),
    ) -> None:
        """Show the effective profile and its active/retired overlays."""
        try:
            result = preference_store(project).profile(
                chapter=chapter,
                arc=arc,
                window=window,
                chapter_scope=chapter_scope,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    @feedback_app.command("rollback")
    def rollback_feedback_command(
        project: str = typer.Option(..., "--project"),
        event_id: str = typer.Option(..., "--event-id"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        """Append a rollback for the latest event in one preference scope."""
        try:
            result = preference_store(project).rollback(
                event_id=event_id,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    narrative_app.add_typer(author_team_app, name="author-team")
    narrative_app.add_typer(acceptance_app, name="acceptance")
    narrative_app.add_typer(candidate_app, name="candidate")
    narrative_app.add_typer(context_app, name="context")
    narrative_app.add_typer(feedback_app, name="feedback")
    narrative_app.add_typer(planning_window_app, name="planning-window")
    app.add_typer(narrative_app, name="narrative")
