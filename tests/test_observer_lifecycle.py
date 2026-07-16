"""Observer role lifecycle coverage."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agent_runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from lifecycle_graph import (
    LIFECYCLE_NODES,
    NODE_REQUIRED_OUTPUTS,
    create_lifecycle,
    load_lifecycle,
    save_lifecycle,
)
from artifact_contract import required_artifacts_for_route
from pipeline_runner import (
    NODE_TO_AGENT,
    NODE_TO_REPORT,
    _observation_report_content,
    run_next_node,
)
from production_chain_audit import (
    _agent_lifecycle_coverage,
    _effective_lifecycle_nodes,
)
from schemas import AgentRoute
from task_snapshot import LIFECYCLE_ORDER, build_task_snapshot
from task_router import recommend_route


def test_observer_node_runs_only_when_route_includes_observer(tmp_path: Path) -> None:
    skipped = create_lifecycle(
        tmp_path / "skipped",
        {"route": {"agents": ["Supervisor"]}},
    )
    active = create_lifecycle(
        tmp_path / "active",
        {
            "route": {"agents": ["Supervisor", "Observer"]},
            "production_pack": {
                "pack_id": "legacy_pack_without_observer_node",
                "lifecycle_nodes": [
                    "INIT_TASK",
                    "PREPARE_PLAN",
                    "SUPERVISOR_PLAN",
                    "FINALIZE",
                ],
            },
        },
    )

    assert skipped["nodes"]["OBSERVATION_OPTIONAL"]["status"] == "skipped"
    assert skipped["nodes"]["OBSERVATION_OPTIONAL"]["skip_reason"] == (
        "Route does not include Observer"
    )
    assert active["nodes"]["OBSERVATION_OPTIONAL"]["status"] == "waiting"
    assert active["nodes"]["OBSERVATION_OPTIONAL"]["skip_reason"] is None


def test_observer_role_contract_is_registered_and_read_only() -> None:
    route = AgentRoute(task_size="small", agents=["Observer"])
    registry = yaml.safe_load(
        (ROOT / "config" / "agent_registry.yml").read_text(encoding="utf-8")
    )
    observer = registry["agents"]["Observer"]
    template_path = ROOT / observer["template_path"]
    old_order = [
        "INIT_TASK",
        "CONTEXT_PROFILE",
        "CONTEXT_BUDGET",
        "CONTEXT_PACK",
        "PREPARE_PLAN",
        "SUPERVISOR_PLAN",
        "REPO_CONTEXT",
        "RESEARCH_OPTIONAL",
        "INTERFACE_OPTIONAL",
        "WRITER_DRAFT",
        "FICTION_REVIEW",
        "SCRIBE_LEDGER",
        "NARRATIVE_REWRITE_PLAN",
        "CODER_IMPLEMENTATION",
        "ARTIFACT_PRODUCTION",
        "VISUAL_OBSERVATION",
        "VISUAL_REVIEW",
        "VALIDATION",
        "AUDIT",
        "VERIFY",
        "ARCHIVE",
        "SELF_CHECK",
        "SYNC_OPTIONAL",
        "FINALIZE",
    ]

    assert route.agents == ["Observer"]
    assert observer["model_profile"] == "perception_observer"
    assert observer["can_edit_source"] is False
    assert observer["can_run_shell"] is False
    assert observer["source_write_policy"] == "never"
    assert observer["required_outputs"] == [
        "runs/task_xxxx/observation_report.yml"
    ]
    assert template_path.exists()
    assert "files_changed: []" in template_path.read_text(encoding="utf-8")
    assert NODE_TO_AGENT["OBSERVATION_OPTIONAL"] == "Observer"
    assert NODE_TO_REPORT["OBSERVATION_OPTIONAL"] == "observation_report.yml"
    assert NODE_REQUIRED_OUTPUTS["OBSERVATION_OPTIONAL"] == [
        "observation_report.yml"
    ]
    assert [node for node in LIFECYCLE_NODES if node != "OBSERVATION_OPTIONAL"] == old_order
    assert LIFECYCLE_NODES.index("RESEARCH_OPTIONAL") < LIFECYCLE_NODES.index(
        "OBSERVATION_OPTIONAL"
    ) < LIFECYCLE_NODES.index("INTERFACE_OPTIONAL")


def test_observer_node_writes_read_only_report_and_status_receipt(tmp_path: Path) -> None:
    project = "Demo"
    task_id = "task_observer"
    run_dir = tmp_path / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True)
    plan = {
        "route": {"agents": ["Supervisor", "Observer"]},
        "production_pack": {
            "pack_id": "legacy_pack_without_observer_node",
            "lifecycle_nodes": [
                "INIT_TASK",
                "PREPARE_PLAN",
                "SUPERVISOR_PLAN",
                "FINALIZE",
            ],
        },
    }
    (run_dir / "workflow_plan.yml").write_text(
        yaml.safe_dump(plan, sort_keys=False), encoding="utf-8"
    )
    (run_dir / "user_request.md").write_text("Observe assigned inputs.\n", encoding="utf-8")
    lifecycle = create_lifecycle(run_dir, plan)
    for node_id in LIFECYCLE_NODES:
        if node_id == "OBSERVATION_OPTIONAL":
            lifecycle["nodes"][node_id]["status"] = "waiting"
        elif LIFECYCLE_NODES.index(node_id) < LIFECYCLE_NODES.index(
            "OBSERVATION_OPTIONAL"
        ):
            lifecycle["nodes"][node_id]["status"] = "completed"
    save_lifecycle(run_dir, lifecycle)

    result = run_next_node(tmp_path, project, task_id, fake_provider=True)

    report_path = run_dir / "observation_report.yml"
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    receipt = load_lifecycle(run_dir)["nodes"]["OBSERVATION_OPTIONAL"]
    snapshot = build_task_snapshot(run_dir, project=project, task_id=task_id)
    assert result == {
        "status": "completed",
        "node": "OBSERVATION_OPTIONAL",
        "report": str(report_path),
    }
    assert report["report_type"] == "observation_report"
    assert report["task_id"] == task_id
    assert report["status"] == "complete"
    assert report["read_only"] is True
    assert report["safety_receipt"] == {
        "files_changed": [],
        "commands_run": [],
        "production_actions": [],
        "self_approved": False,
    }
    assert receipt["status"] == "completed"
    assert receipt["report_path"] == str(report_path)
    assert LIFECYCLE_ORDER == LIFECYCLE_NODES
    assert snapshot["lifecycle"]["nodes"]["OBSERVATION_OPTIONAL"] == "completed"


def test_real_cli_observer_wrapper_normalizes_structured_yaml_and_model_receipt(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "model_execution_receipt_observer.yml"
    receipt_path.write_text("status: pass\nworker: agy\n", encoding="utf-8")
    wrapped = """# Observer Report (CLI Agent: agy)

- **Task**: task_observer

## Output

```yaml
schema_version: 1
status: complete
candidate_only: true
production_modified: false
observations:
  - summary: A timestamp is visible.
    source: clip.mp4
    timestamp: '00:00:03'
scientific_evidence:
  - claim: The frame contains a clock overlay.
actionable_suggestions:
  - Verify the timestamp against the source metadata.
uncertainties:
  - The overlay timezone is not identified.
```
"""

    report = yaml.safe_load(
        _observation_report_content(
            "task_observer",
            wrapped,
            provider="agy",
            model="Gemini 3.5 Flash (High)",
            model_execution_receipt=str(receipt_path),
            model_execution_chain=str(tmp_path / "model_execution_chain_observer.yml"),
        )
    )

    assert report["status"] == "complete"
    assert report["candidate_only"] is True
    assert report["production_modified"] is False
    assert report["self_approved"] is False
    assert report["observations"] == [
        {
            "summary": "A timestamp is visible.",
            "source": "clip.mp4",
            "timestamp": "00:00:03",
        }
    ]
    assert report["actionable_suggestions"] == [
        "Verify the timestamp against the source metadata."
    ]
    assert report["uncertainties"] == [
        "The overlay timezone is not identified."
    ]
    assert report["model_execution_receipt"] == str(receipt_path)
    assert report["runtime_provenance"]["model_execution_receipt_path"] == str(
        receipt_path
    )
    assert report["model_execution_chain"] == str(
        tmp_path / "model_execution_chain_observer.yml"
    )
    assert "Observer Report (CLI Agent" not in yaml.safe_dump(report)


def test_unparseable_cli_observer_wrapper_blocks_instead_of_defaulting_complete() -> None:
    wrapped = """# Observer Report (CLI Agent: agy)

## Output

```yaml
observations: [unterminated
```
"""

    report = yaml.safe_load(
        _observation_report_content(
            "task_observer",
            wrapped,
            provider="agy",
            model="Gemini 3.5 Flash (High)",
            model_execution_receipt="/run/model_execution_receipt_observer.yml",
        )
    )

    assert report["status"] == "blocked"
    assert report["observations"] == []
    assert report["candidate_only"] is True
    assert report["production_modified"] is False
    assert report["limitations"] == ["observer_output_unparseable"]


def test_chain_audit_counts_route_selected_observer_for_legacy_pack() -> None:
    pack = {
        "lifecycle_nodes": [
            "INIT_TASK",
            "PREPARE_PLAN",
            "SUPERVISOR_PLAN",
            "FINALIZE",
        ]
    }

    without_observer = _effective_lifecycle_nodes(pack, ["Supervisor"])
    with_observer = _effective_lifecycle_nodes(pack, ["Supervisor", "Observer"])
    coverage = _agent_lifecycle_coverage(
        ["Supervisor", "Observer"], with_observer
    )

    assert "OBSERVATION_OPTIONAL" not in without_observer
    assert with_observer == [
        "INIT_TASK",
        "PREPARE_PLAN",
        "SUPERVISOR_PLAN",
        "OBSERVATION_OPTIONAL",
        "FINALIZE",
    ]
    assert coverage["status"] == "pass"
    assert coverage["coverage"]["Observer"] == ["OBSERVATION_OPTIONAL"]


def test_observer_route_requires_observation_report_artifact() -> None:
    required = required_artifacts_for_route(["Observer"])

    assert "observation_report.yml" in required


def test_explicit_pdf_summary_routes_to_observer() -> None:
    route = recommend_route("Summarize the attached PDF and cite the relevant pages.")

    assert route.route_key == "observation_task"
    assert route.agents == ["Supervisor", "Observer"]


@pytest.mark.parametrize(
    "prompt",
    [
        "Summarize this long text and list its unsupported claims.",
        "OCR the attached image screenshot.png and extract the visible labels.",
        "Describe the attached video clip.mp4 scene by scene.",
        "Transcribe the attached audio recording.wav and identify the speakers.",
        "Extract the tables from the attached PDF report.pdf.",
        "总结这段长文本，并列出仍需核实的主张。",
        "观察这张图片 screenshot.png 并描述可见证据。",
        "转录这段音频 recording.mp3，并区分说话人。",
    ],
)
def test_explicit_multimodal_inputs_route_to_observer(prompt: str) -> None:
    route = recommend_route(prompt)

    assert route.route_key == "observation_task"
    assert route.agents == ["Supervisor", "Observer"]


@pytest.mark.parametrize(
    "prompt",
    [
        "Create a summary of the attached PDF.",
        "Make a transcript of attached audio.",
        "Produce OCR transcript of this image.",
    ],
)
def test_artifact_verbs_do_not_override_attached_input_observation(
    prompt: str,
) -> None:
    route = recommend_route(prompt)

    assert route.route_key == "observation_task"
    assert route.agents == ["Supervisor", "Observer"]


@pytest.mark.parametrize(
    "prompt",
    [
        "Generate an image poster from this prompt.",
        "Create a video from the storyboard.",
        "Render this video into a new MP4 deliverable.",
        "Generate this image and then describe the generated result.",
        "Render this video and summarize the rendered deliverable.",
        "制作一段音频旁白。",
        "生成这张图片的高清版本。",
    ],
)
def test_media_production_requests_do_not_route_to_observer(prompt: str) -> None:
    route = recommend_route(prompt)

    assert route.route_key != "observation_task"
    assert "ArtifactProducer" in route.agents


def test_generic_media_pipeline_analysis_is_not_treated_as_attached_asset() -> None:
    route = recommend_route(
        "Analyze the video generation pipeline and review the image backend design."
    )

    assert route.route_key != "observation_task"
    assert "Observer" not in route.agents


def test_observation_route_is_configured_and_observer_is_in_fallback_catalog() -> None:
    routing_config = yaml.safe_load(
        (ROOT / "config" / "routing_rules.yml").read_text(encoding="utf-8")
    )

    assert routing_config["routes"]["observation_task"] == {
        "size": "L2",
        "description": "显式长文本、附件图片、视频、音频、PDF或文档的只读观察、总结、OCR、转录与提取",
        "analysis_only": True,
        "agents": ["Supervisor", "Observer"],
    }
    assert "Observer" in routing_config["agent_order"]

    ordinary_route = recommend_route("Fix a typo in one source file.")
    assert "Observer" in ordinary_route.skipped_agents
