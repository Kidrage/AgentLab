from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.routing.role_assignment import RoleAssignmentEngine
from agent_runtime.routing.worker_router import route_task_packet
from agent_runtime.run_task import app
from agent_runtime.workflow_plan import build_workflow_plan


ROOT = Path(__file__).resolve().parents[1]


def test_role_preferences_and_coder_fallback() -> None:
    engine = RoleAssignmentEngine(ROOT)
    repo = engine.assign("RepoScout", available_workers=["rg", "claude_code"])
    assert repo.selected_worker == "rg"

    mapper = engine.assign("InterfaceMapper", available_workers=["ast_grep", "claude_code"])
    assert mapper.selected_worker == "ast_grep"

    verifier = engine.assign("Verifier", available_workers=["ruff", "claude_code"])
    assert verifier.selected_worker == "ruff"

    primary_coder = engine.assign("Coder", available_workers=["claude_code", "codex", "aider"])
    assert primary_coder.selected_worker == "claude_code"
    assert primary_coder.fallback_workers == ["codex", "aider"]

    coder = engine.assign("Coder", available_workers=["codex", "aider"])
    assert coder.selected_worker == "codex"
    assert "aider" in coder.fallback_workers
    assert coder.approval_required is True
    assert any(item.worker == "claude_code" for item in coder.rejected_workers)


def test_route_task_writes_explainable_evidence(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "config").symlink_to(ROOT / "config", target_is_directory=True)
    packet = tmp_path / "task_packet.yml"
    packet.write_text(yaml.safe_dump({
        "task_packet": {
            "project_id": "DemoProject",
            "phase_id": "phase1",
            "packet_id": "task_route_1",
            "role": "Coder",
            "available_workers": ["codex", "aider"],
            "allowed_files": ["agent_runtime/**"],
        }
    }), encoding="utf-8")
    result = route_task_packet(packet, root)
    decision = result["route_plan"]["decisions"][0]
    assert decision["selected_worker"] == "codex"
    evidence = Path(decision["evidence_paths"][0])
    assert evidence.exists()
    assert "claude_code" in evidence.read_text(encoding="utf-8")


def test_router_cli_smoke(tmp_path: Path) -> None:
    runner = CliRunner()
    assigned = runner.invoke(app, [
        "assign-role", "--role", "Coder", "--available-worker", "codex", "--available-worker", "aider",
    ])
    assert assigned.exit_code == 0
    assert "selected_worker: codex" in assigned.stdout

    decision = tmp_path / "decision.yml"
    payload = RoleAssignmentEngine(ROOT).assign("RepoScout", available_workers=["rg"])
    payload.write(decision)
    explained = runner.invoke(app, ["route-explain", "--decision", str(decision)])
    assert explained.exit_code == 0
    assert "Selected worker: rg" in explained.stdout


def test_route_probe_classifies_natural_language_task_without_task_packet() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["route-probe", "写", "Crown", "第", "1", "章"])

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.stdout)["route_probe"]
    assert payload["route_key"] == "narrative_light_chapter"
    assert payload["agents"] == ["Supervisor", "Writer"]
    assert payload["production_pack"] == "narrative_longform"
    assert payload["route_source"] == "mission_contract"
    assert payload["probe_only"] is True
    assert payload["evidence_written"] is False


def test_route_probe_keeps_code_article_and_audit_chains_distinct() -> None:
    runner = CliRunner()
    cases = [
        ("审计 Crown 前 10 章", "narrative_heavy_audit", ["Supervisor", "Reviewer", "Scribe", "Verifier"], "narrative_longform"),
        ("写一篇产品说明文章", "article_light_draft", ["Supervisor", "ArtifactProducer"], "article_light"),
        ("修复这个 Python 函数的 bug", "small_task", ["Supervisor", "Coder", "TesterAuditor"], "code_factory"),
    ]

    for text, route_key, agents, pack_id in cases:
        result = runner.invoke(app, ["route-probe", text])
        assert result.exit_code == 0, result.output
        payload = yaml.safe_load(result.stdout)["route_probe"]
        assert payload["route_key"] == route_key
        assert payload["agents"] == agents
        assert payload["production_pack"] == pack_id


def test_route_probe_uses_mission_contract_for_media_series_pack() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["route-probe", "把 Crown_of_Ash 做成漫画短视频海报图册连续剧"])
    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.stdout)["route_probe"]
    assert payload["route_source"] == "mission_contract"
    assert payload["route_key"] == "media_generation_task"
    assert payload["agents"] == ["Supervisor", "ArtifactProducer", "TesterAuditor", "Verifier"]
    assert payload["production_pack"] == "media_series_production"
    assert payload["production_pack_status"] == "configured"

    result_do_phrase = runner.invoke(app, ["route-probe", "给Crown_of_Ash做一段连贯视频脚本和海报图册"])
    assert result_do_phrase.exit_code == 0, result_do_phrase.output
    payload_do = yaml.safe_load(result_do_phrase.stdout)["route_probe"]
    assert payload_do["route_source"] == "mission_contract"
    assert payload_do["route_key"] == "media_generation_task"
    assert payload_do["production_pack"] == "media_series_production"


def test_route_probe_surfaces_pack_synthesis_candidate_for_unknown_non_code_domain() -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["route-probe", "设计一个长期沉浸式展览生成系统 需要保持展项人物和空间状态连续"],
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.stdout)["route_probe"]
    assert payload["route_source"] == "mission_contract"
    assert payload["production_pack"] == "pack_synthesis_candidate"
    assert payload["production_pack_status"] == "synthesis_candidate"
    assert payload["agents"] == ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]


def test_route_probe_surfaces_pack_synthesis_for_explicit_pack_design_request() -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["route-probe", "为一个未知领域任务创建生产包并准备生命周期与记忆合约"],
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.stdout)["route_probe"]
    assert payload["route_source"] == "mission_contract"
    assert payload["route_key"] == "artifact_production_task"
    assert payload["production_pack"] == "pack_synthesis_candidate"
    assert payload["production_pack_status"] == "synthesis_candidate"
    assert payload["mission_route_decision"]["selected_route"] == "artifact_production_task"
    assert payload["agents"] == ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]


def test_route_probe_matches_workflow_plan_route_and_pack(tmp_path: Path) -> None:
    runner = CliRunner()
    cases = [
        "写 Crown 第 1 章",
        "审计 Crown 前 10 章",
        "写一篇产品说明文章",
        "修复这个 Python 函数的 bug",
        "把 Crown_of_Ash 做成漫画短视频海报图册连续剧",
        "设计一个长期沉浸式展览生成系统 需要保持展项人物和空间状态连续",
    ]

    for index, text in enumerate(cases):
        task_id = f"task_route_probe_compare_{index}"
        request_path = tmp_path / f"{task_id}.md"
        request_path.write_text(text, encoding="utf-8")
        plan = build_workflow_plan(
            ROOT,
            "Probe",
            task_id,
            user_request_path=request_path,
        )

        result = runner.invoke(app, ["route-probe", "--project", "Probe", "--task-id", task_id, text])
        assert result.exit_code == 0, result.output
        payload = yaml.safe_load(result.stdout)["route_probe"]

        assert payload["route_key"] == plan.route.route_key
        assert payload["agents"] == plan.route.agents
        assert payload["production_pack"] == (plan.production_pack or {}).get("pack_id")
        assert payload["production_pack_status"] == (plan.production_pack or {}).get("status")
