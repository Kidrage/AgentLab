from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.cli.governance import build_revision_intake, run_governance_doctor
from agent_runtime.program_manager.project_fact_state import append_project_fact_events, rebuild_project_fact_snapshot
from agent_runtime.protocols import build_role_session
from agent_runtime.pipeline_runner import run_full_pipeline
from agent_runtime.revision_governance import (
    apply_revision,
    check_revision_conflicts,
    revision_dispatch_status,
    validate_revision,
    write_revision_intake,
)
from agent_runtime.run_task import app


runner = CliRunner()


def _copy_config_root(tmp_path: Path) -> Path:
    root = tmp_path / "AgentLab"
    (root / "config").mkdir(parents=True)
    for name in [
        "agent_model_profiles.yml",
        "model_catalog.yml",
        "model_providers.yml",
        "agent_registry.yml",
        "agent_role_bindings.yml",
        "model_capacity.yml",
        "worker_invocation_contracts.yml",
        "model_pricing.yml",
        "media_generation_backends.yml",
        "visual_acceptance.yml",
        "frontdesk_policy.yml",
        "content_project_governance.yml",
        "knowledge_system.yml",
    ]:
        shutil.copy(ROOT / "config" / name, root / "config" / name)
    return root


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_models_show_lists_writer_agy_gemini_default():
    result = runner.invoke(app, ["models", "show", "--role", "Writer"])

    assert result.exit_code == 0
    assert "writer" in result.output
    assert "agy" in result.output
    assert "gemini_3_6_flash_high_agy_oauth" in result.output


def test_models_show_lists_observer_supervisor_and_grok_research_routes():
    observer = runner.invoke(app, ["models", "show", "--role", "Observer"])
    supervisor = runner.invoke(app, ["models", "show", "--role", "Supervisor"])
    researcher = runner.invoke(app, ["models", "show", "--role", "Researcher"])

    assert observer.exit_code == 0
    assert "agy" in observer.output
    assert "gemini_3_6_flash_high_agy_oauth" in observer.output
    assert supervisor.exit_code == 0
    assert "grok_4_5_high_cli_oauth" in supervisor.output
    assert "grok" in supervisor.output
    assert "SupervisorDeepSeek" in supervisor.output
    assert researcher.exit_code == 0
    assert "grok" in researcher.output
    assert "grok_4_5_medium_cli_oauth" in researcher.output


def test_models_capacity_keeps_unobserved_remaining_and_reset_null():
    result = runner.invoke(app, ["models", "capacity"])

    assert result.exit_code == 0
    payload = yaml.safe_load(result.output)
    assert payload["remaining_and_reset_policy"] == "provider_evidence_or_null"
    observer_pools = {
        row["pool_id"]: row
        for row in payload["pools"]
        if row["pool_id"].startswith("agy_")
    }
    assert set(observer_pools) == {"agy_gemini_observer", "agy_claude_observer"}
    for row in observer_pools.values():
        assert row["status"] == "unknown"
        assert row["remaining"] is None
        assert row["reset_at"] is None
        assert row["probe_capability"]["kind"] == "catalog_only"
        assert row["probe_capability"]["reports_remaining"] is False
        assert row["probe_capability"]["reports_reset_at"] is False


def test_models_capacity_probe_all_runs_only_declared_safe_probes(
    tmp_path, monkeypatch
):
    from agent_runtime.cli.models import register_model_commands
    import subprocess
    import typer
    from rich.console import Console

    root = _copy_config_root(tmp_path)
    local_app = typer.Typer()
    register_model_commands(local_app, root, Console(width=1000))
    calls: list[tuple[str, ...]] = []

    def fake_run(command, **_kwargs):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout="logged in", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_dir = tmp_path / "capacity"
    result = runner.invoke(
        local_app,
        ["models", "capacity", "--run-dir", str(run_dir), "--probe", "all"],
    )

    assert result.exit_code == 0
    payload = yaml.safe_load(result.output)
    assert payload["probe_scope"] == "all_declared_safe_probes"
    assert len(payload["probe_results"]) == 6
    assert ("agy", "models") in calls
    assert ("grok", "models") in calls
    assert ("codex", "login", "status") in calls
    assert ("hermes", "auth", "status", "xai-oauth") in calls
    assert not any(call[:3] == ("hermes", "status", "--all") for call in calls)


def test_model_proposal_round_trip_on_temp_root(tmp_path):
    from agent_runtime.cli.models import _proposal_dir, register_model_commands
    import typer
    from rich.console import Console

    root = _copy_config_root(tmp_path)
    local_app = typer.Typer()
    register_model_commands(local_app, root, Console(width=120))

    proposed = runner.invoke(
        local_app,
        ["models", "propose", "--role", "Writer", "--cli", "claude_code", "--model", "deepseek_v4_flash"],
    )
    assert proposed.exit_code == 0
    data = yaml.safe_load(proposed.output)
    proposal_id = data["proposal_id"]
    profiles_before = (root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8")
    assert (_proposal_dir(root) / f"{proposal_id}.yml").exists()
    assert (root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8") == profiles_before

    applied = runner.invoke(local_app, ["models", "apply", "--proposal", proposal_id])
    assert applied.exit_code == 0
    proposal = yaml.safe_load((_proposal_dir(root) / f"{proposal_id}.yml").read_text(encoding="utf-8"))
    assert proposal["status"] == "applied"
    profiles = yaml.safe_load(
        (root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8")
    )
    writer = profiles["modes"][profiles["default_mode"]]["tiers"]["alter"]["writer"]
    assert writer["invocation_contract"] == "claude_writer"
    assert writer["capacity_route"] == "WriterFlash"


def test_model_proposal_can_update_all_output_tiers_atomically(tmp_path):
    from agent_runtime.cli.models import _proposal_dir, register_model_commands
    import typer
    from rich.console import Console

    root = _copy_config_root(tmp_path)
    local_app = typer.Typer()
    register_model_commands(local_app, root, Console(width=120))

    proposed = runner.invoke(
        local_app,
        [
            "models",
            "propose",
            "--role",
            "Writer",
            "--cli",
            "claude_code",
            "--model",
            "deepseek_v4_flash",
            "--all-tiers",
        ],
    )
    assert proposed.exit_code == 0
    proposal_id = yaml.safe_load(proposed.output)["proposal_id"]
    proposal = yaml.safe_load(
        (_proposal_dir(root) / f"{proposal_id}.yml").read_text(encoding="utf-8")
    )
    assert proposal["tiers"] == ["alter", "full", "performance", "low"]

    applied = runner.invoke(local_app, ["models", "apply", "--proposal", proposal_id])

    assert applied.exit_code == 0
    profiles = yaml.safe_load(
        (root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8")
    )
    tiers = profiles["modes"][profiles["default_mode"]]["tiers"]
    for tier in ("alter", "full", "performance", "low"):
        assert tiers[tier]["writer"]["default"] == "deepseek_v4_flash"
    assert tiers["alter"]["writer"]["capacity_route"] == "WriterFlash"
    assert tiers["full"]["writer"]["capacity_route"] == "WriterFlash"
    assert tiers["performance"]["writer"]["capacity_route"] == "WriterFlash"
    assert tiers["low"]["writer"]["capacity_route"] == "WriterLow"


def test_model_apply_recovers_if_proposal_receipt_write_is_interrupted(
    tmp_path, monkeypatch
):
    import agent_runtime.cli.models as model_cli
    import typer
    from rich.console import Console

    root = _copy_config_root(tmp_path)
    local_app = typer.Typer()
    model_cli.register_model_commands(local_app, root, Console(width=120))
    proposed = runner.invoke(
        local_app,
        [
            "models",
            "propose",
            "--role",
            "Writer",
            "--cli",
            "claude_code",
            "--model",
            "deepseek_v4_flash",
        ],
    )
    proposal_id = yaml.safe_load(proposed.output)["proposal_id"]
    proposal_path = model_cli._proposal_dir(root) / f"{proposal_id}.yml"
    real_write = model_cli._write_yaml
    call_count = 0

    def interrupted_write(path, data):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise OSError("simulated receipt interruption")
        real_write(path, data)

    monkeypatch.setattr(model_cli, "_write_yaml", interrupted_write)
    interrupted = runner.invoke(
        local_app,
        ["models", "apply", "--proposal", proposal_id],
    )
    assert interrupted.exit_code != 0
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "applying"

    monkeypatch.setattr(model_cli, "_write_yaml", real_write)
    recovered = runner.invoke(
        local_app,
        ["models", "apply", "--proposal", proposal_id],
    )

    assert recovered.exit_code == 0
    assert "recovered_from: applying" in recovered.output
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    assert proposal["status"] == "applied"


def test_catalog_model_proposal_and_apply_preserve_audited_entry(tmp_path):
    from agent_runtime.cli.models import _proposal_dir, register_model_commands
    import typer
    from rich.console import Console

    root = _copy_config_root(tmp_path)
    local_app = typer.Typer()
    register_model_commands(local_app, root, Console(width=120))
    entry_path = tmp_path / "new_model.yml"
    _write_yaml(
        entry_path,
        {
            "provider": "codex_cli_oauth",
            "runtime_provider": "codex-cli",
            "cli_provider": "codex",
            "model_id": "gpt-5.7-sol",
            "reasoning_effort": "high",
            "context_window": 300000,
            "capacity_pool": "codex_cli_agentic",
            "suitable_agents": ["artifact_producer"],
        },
    )

    proposed = runner.invoke(
        local_app,
        [
            "models",
            "catalog-propose",
            "--model-key",
            "codex_gpt_5_7_sol_high_cli_oauth",
            "--entry-file",
            str(entry_path),
        ],
    )
    assert proposed.exit_code == 0
    proposal_id = yaml.safe_load(proposed.output)["proposal_id"]
    catalog_before = (root / "config" / "model_catalog.yml").read_text(encoding="utf-8")

    applied = runner.invoke(
        local_app,
        ["models", "catalog-apply", "--proposal", proposal_id],
    )

    assert applied.exit_code == 0
    assert catalog_before != (root / "config" / "model_catalog.yml").read_text(
        encoding="utf-8"
    )
    catalog = yaml.safe_load(
        (root / "config" / "model_catalog.yml").read_text(encoding="utf-8")
    )
    entry = catalog["models"]["codex_gpt_5_7_sol_high_cli_oauth"]
    assert entry["model_id"] == "gpt-5.7-sol"
    assert entry["reasoning_effort"] == "high"
    proposal = yaml.safe_load(
        (_proposal_dir(root) / f"{proposal_id}.yml").read_text(encoding="utf-8")
    )
    assert proposal["status"] == "applied"
    assert proposal["entry_sha256"]


def test_model_proposal_rejects_forbidden_worker_and_contract_model_drift(tmp_path):
    from agent_runtime.cli.models import _proposal_dir, register_model_commands
    import typer
    from rich.console import Console

    root = _copy_config_root(tmp_path)
    local_app = typer.Typer()
    register_model_commands(local_app, root, Console(width=120))

    forbidden = runner.invoke(
        local_app,
        [
            "models",
            "propose",
            "--role",
            "Writer",
            "--cli",
            "qwen",
            "--model",
            "qwen3_7_max_dashscope",
        ],
    )
    assert forbidden.exit_code == 1
    assert "Protocol role binding rejected" in forbidden.output

    wrong_supervisor_model = runner.invoke(
        local_app,
        [
            "models",
            "propose",
            "--role",
            "Supervisor",
            "--cli",
            "codex",
            "--model",
            "deepseek_v4_pro",
        ],
    )
    assert wrong_supervisor_model.exit_code == 1
    assert "No governed capacity route matches" in wrong_supervisor_model.output
    assert list(_proposal_dir(root).glob("*.yml")) == []


def test_model_apply_revalidates_proposal_binding_before_mutation(tmp_path):
    from agent_runtime.cli.models import _proposal_dir, register_model_commands
    import typer
    from rich.console import Console

    root = _copy_config_root(tmp_path)
    local_app = typer.Typer()
    register_model_commands(local_app, root, Console(width=120))
    proposed = runner.invoke(
        local_app,
        ["models", "propose", "--role", "Writer", "--cli", "claude_code", "--model", "deepseek_v4_flash"],
    )
    proposal_id = yaml.safe_load(proposed.output)["proposal_id"]
    path = _proposal_dir(root) / f"{proposal_id}.yml"
    proposal = yaml.safe_load(path.read_text(encoding="utf-8"))
    proposal["cli_agent"] = "qwen"
    _write_yaml(path, proposal)
    profiles_before = (root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8")

    applied = runner.invoke(local_app, ["models", "apply", "--proposal", proposal_id])

    assert applied.exit_code == 1
    assert "Proposal no longer matches governed routing" in applied.output
    assert (root / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8") == profiles_before


def test_models_doctor_allows_balanced_qwen_plus_but_not_qwen_max_or_low_plus(tmp_path):
    from agent_runtime.cli.models import _doctor_issues

    root = tmp_path / "AgentLab"
    config = root / "config"
    config.mkdir(parents=True)
    _write_yaml(
        config / "agent_model_profiles.yml",
        {
            "modes": {
                "full_cli": {
                    "tiers": {
                        "performance": {
                            "interface_mapper": {
                                "default": "deepseek_v4_pro",
                                "fallback": "qwen3_6_plus_dashscope",
                            },
                            "tester_auditor": {
                                "default": "qwen3_7_max_dashscope",
                            },
                        },
                        "low": {
                            "writer": {
                                "default": "qwen3_6_plus_dashscope",
                            },
                            "verifier": {
                                "default": "qwen3_6_flash_dashscope",
                            },
                        },
                        "full": {
                            "prompt_engineer": {
                                "default": "qwen3_7_max_dashscope",
                            },
                        },
                    }
                }
            }
        },
    )

    issues = _doctor_issues(root)
    scopes = {issue["scope"] for issue in issues}

    assert "full_cli.performance.interface_mapper.fallback" not in scopes
    assert "full_cli.full.prompt_engineer.default" not in scopes
    assert scopes == {
        "full_cli.performance.tester_auditor.default",
        "full_cli.low.writer.default",
    }


def test_models_doctor_rejects_static_capacity_values_and_cooldown_guesses(tmp_path):
    from agent_runtime.cli.models import _doctor_issues

    root = _copy_config_root(tmp_path)
    capacity_path = root / "config" / "model_capacity.yml"
    capacity = yaml.safe_load(capacity_path.read_text(encoding="utf-8"))
    pool = capacity["pools"]["agy_gemini_observer"]
    pool["declared_windows"]["weekly"]["remaining"] = 17
    pool["exhaustion_cooldown_seconds"] = 18_000
    _write_yaml(capacity_path, capacity)

    issues = _doctor_issues(root)
    names = {issue["issue"] for issue in issues}

    assert "static_capacity_value_must_be_unknown" in names
    assert "static_exhaustion_cooldown_forbidden" in names


def test_models_doctor_rejects_route_contract_and_model_pool_drift(tmp_path):
    from agent_runtime.cli.models import _doctor_issues

    root = _copy_config_root(tmp_path)
    capacity_path = root / "config" / "model_capacity.yml"
    capacity = yaml.safe_load(capacity_path.read_text(encoding="utf-8"))
    capacity["routes"]["WriterFlash"]["invocation_contract"] = "not_registered"
    _write_yaml(capacity_path, capacity)

    catalog_path = root / "config" / "model_catalog.yml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["models"]["grok_4_5_hermes_oauth"]["capacity_pool"] = "wrong_pool"
    _write_yaml(catalog_path, catalog)

    issues = _doctor_issues(root)
    names = {issue["issue"] for issue in issues}

    assert "capacity_contract_missing" in names
    assert "capacity_model_pool_mismatch" in names


def test_pricing_authority_has_current_qwen_and_exact_xai_media_rows():
    pricing = yaml.safe_load(
        (ROOT / "config" / "model_pricing.yml").read_text(encoding="utf-8")
    )
    models = pricing["models"]

    assert models["qwen3.7-max"]["input_per_1m_usd"] == 1.65
    assert models["qwen3.7-max"]["output_per_1m_usd"] == 4.951
    assert models["qwen3.7-max"]["deployment_region"] == "cn-beijing"
    assert models["qwen3.7-max"]["deployment_tier"] == "china_first_tier"
    assert models["qwen3.6-plus"]["input_per_1m_usd"] == 0.276
    assert models["qwen3.6-plus"]["output_per_1m_usd"] == 1.651
    assert models["qwen3.6-plus"]["deployment_region"] == "cn-beijing"
    assert models["qwen3.6-plus"]["deployment_tier"] == "china_first_tier"
    assert models["qwen3.6-flash"]["input_per_1m_usd"] == 0.165
    assert models["qwen3.6-flash"]["output_per_1m_usd"] == 0.99
    assert models["qwen3.6-flash"]["deployment_region"] == "cn-beijing"
    assert models["qwen3.6-flash"]["deployment_tier"] == "china_first_tier"
    assert models["qwen3-coder-next"]["deployment_tier"] == "china_first_tier"
    assert models["qwen3-coder-next"]["input_per_1m_usd"] == 0.144
    assert models["qwen3-coder-next"]["output_per_1m_usd"] == 0.574
    assert models["qwen3-coder-plus"]["pricing_tier"] == "input_context_0_to_32k"
    assert models["qwen3-coder-plus"]["input_per_1m_usd"] == 0.574
    assert models["qwen3-coder-plus"]["output_per_1m_usd"] == 2.294

    image = models["grok-imagine-image-quality"]
    assert image["provider_model_id"] == "grok-imagine-image-quality"
    assert image["media_unit_prices_usd"] == {
        "input_image": 0.01,
        "output_image_1k": 0.05,
        "output_image_2k": 0.07,
    }
    video = models["grok-imagine-video-1.5"]
    assert video["provider_model_id"] == "grok-imagine-video-1.5"
    assert video["media_unit_prices_usd"] == {
        "input_image": 0.01,
        "output_video_480p_second": 0.08,
        "output_video_720p_second": 0.14,
        "output_video_1080p_second": 0.25,
    }

    catalog = yaml.safe_load(
        (ROOT / "config" / "model_catalog.yml").read_text(encoding="utf-8")
    )
    assert catalog["models"]["qwen3_6_plus_dashscope"]["pricing_key"] == "qwen3.6-plus"
    assert "pricing" not in catalog["models"]["qwen3_6_plus_dashscope"]
    providers = yaml.safe_load(
        (ROOT / "config" / "model_providers.yml").read_text(encoding="utf-8")
    )
    assert providers["providers"]["qwen"]["pricing_key"] == "qwen3.6-plus"


def test_models_doctor_rejects_duplicate_or_missing_pricing_evidence(tmp_path):
    from agent_runtime.cli.models import _doctor_issues

    root = _copy_config_root(tmp_path)
    pricing_path = root / "config" / "model_pricing.yml"
    pricing = yaml.safe_load(pricing_path.read_text(encoding="utf-8"))
    pricing["models"]["grok-imagine-video-1.5"]["provider_model_id"] = "stale-video-id"
    pricing["models"]["grok-imagine-video-1.5"]["media_unit_prices_usd"] = {}
    _write_yaml(pricing_path, pricing)

    backends_path = root / "config" / "media_generation_backends.yml"
    backends = yaml.safe_load(backends_path.read_text(encoding="utf-8"))
    backends["backends"]["hermes_grok_oauth"]["registered_generation_models"][
        "image"
    ] = ["unpriced-registered-image-model"]
    _write_yaml(backends_path, backends)

    catalog_path = root / "config" / "model_catalog.yml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["models"]["qwen3_6_plus_dashscope"]["pricing"] = {
        "currency": "USD",
        "input_per_m": 9.99,
    }
    _write_yaml(catalog_path, catalog)

    providers_path = root / "config" / "model_providers.yml"
    providers = yaml.safe_load(providers_path.read_text(encoding="utf-8"))
    providers["providers"]["qwen"]["notes"].append(
        "Stale duplicate price: $9.99/M input."
    )
    _write_yaml(providers_path, providers)

    issues = _doctor_issues(root)
    names = {issue["issue"] for issue in issues}

    assert "duplicate_numeric_pricing_outside_authority" in names
    assert "inline_numeric_provider_pricing_forbidden" in names
    assert "media_backend_pricing_missing" in names
    assert "media_backend_pricing_model_id_mismatch" in names
    assert "media_backend_unit_pricing_missing" in names


def test_models_doctor_current_pricing_graph_passes():
    from agent_runtime.cli.models import _doctor_issues

    assert _doctor_issues(ROOT) == []


def test_recommended_brain_topology_and_model_facts_match_current_roles():
    groups = yaml.safe_load(
        (ROOT / "config" / "hermes_brain_model_groups.yml").read_text(encoding="utf-8")
    )
    chain = groups["brain_layouts"]["recommended"]["brain_chain"]
    assert chain == {
        "supervisor": "deepseek_v4_pro",
        "writer": "gemini_3_6_flash_high_agy_oauth",
        "multimodal_observer": "gemini_3_6_flash_high_agy_oauth",
        "observer_fallback": "claude_sonnet_4_6_agy_oauth",
        "social_web_research": "grok_4_5_hermes_oauth",
        "artifact_producer": "codex_gpt_5_6_sol_medium_cli_oauth",
        "performance_narrative_planner": "gemini_3_6_flash_high_agy_oauth",
        "full_narrative_planner": "gemini_3_6_flash_high_agy_oauth",
        "independent_verifier": "deepseek_v4_flash",
    }

    catalog = yaml.safe_load(
        (ROOT / "config" / "model_catalog.yml").read_text(encoding="utf-8")
    )
    catalog_keys = set(catalog["models"])
    for provider in groups["providers"].values():
        assert set(provider.get("default_models") or []) <= catalog_keys
    for layout in groups["brain_layouts"].values():
        assert set(layout.get("examples") or []) <= catalog_keys
        assert set((layout.get("brain_chain") or {}).values()) <= catalog_keys

    grok = groups["providers"]["grok_xai"]
    assert grok["role"] == "social_web_research_and_registered_media_tool_orchestration"
    assert grok["direct_media_generation"] is False
    assert grok["audio_generation"] is False
    assert "registered_image_tool_orchestration" in grok["strengths"]
    assert "registered_video_tool_orchestration" in grok["strengths"]
    assert "image_generation" not in grok["strengths"]

    assert "context_window" not in catalog["models"]["grok_4_5_hermes_oauth"]

    providers_text = (ROOT / "config" / "model_providers.yml").read_text(encoding="utf-8")
    assert "$1.74/M输入, $3.48/M输出" not in providers_text


def test_governance_doctor_detects_legacy_and_multiple_current(tmp_path):
    root = _copy_config_root(tmp_path)
    project = root / "projects" / "NovelGen"
    (project / "foo_rebuild").mkdir(parents=True)
    _write_yaml(
        project / "project_artifact_index.yml",
        {
            "artifacts": [
                {"artifact_id": "bible", "status": "current", "production_path": "production/bible/main.yml"},
                {"artifact_id": "bible", "status": "current", "production_path": "v2_rebuild/main.yml"},
            ]
        },
    )

    result = run_governance_doctor(root, "NovelGen")

    assert result["status"] == "fail"
    assert any(issue["check"] == "legacy_fact_dir" for issue in result["issues"])
    assert any(issue["check"] == "single_current_artifact" for issue in result["issues"])
    assert any(issue["check"] == "current_formal_fact_root" for issue in result["issues"])
    assert result["migration_report"]["safe_by_default"] is True
    assert result["migration_report"]["legacy_directories"][0]["path"] == "projects/NovelGen/foo_rebuild"
    assert result["migration_report"]["current_artifact_groups"][0]["current_count"] == 2
    assert any(action["action_id"] == "dedupe_current_artifact_bible" for action in result["remediation_plan"])
    assert any(action["action_id"] == "retire_legacy_current_artifact_bible" for action in result["remediation_plan"])


def test_governance_doctor_reports_revision_migration_actions(tmp_path):
    root = _copy_config_root(tmp_path)
    run_dir = root / "projects" / "NovelGen" / "runs" / "task_revision"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("Please revise the character motive.", encoding="utf-8")

    result = run_governance_doctor(root, "NovelGen")

    assert result["status"] == "pass"
    assert result["migration_report"]["pending_revision_runs"] == [
        {
            "task_id": "task_revision",
            "path": "projects/NovelGen/runs/task_revision",
            "missing": "change_request.yml",
        }
    ]
    issue = next(item for item in result["issues"] if item["check"] == "revision_change_request")
    assert issue["command"].startswith("./agentlab.sh governance revision-intake --project NovelGen")
    assert any(action["action_id"] == "intake_revision_task_revision" for action in result["remediation_plan"])


def test_governance_doctor_write_report(tmp_path):
    import typer
    from rich.console import Console
    from agent_runtime.cli.governance import register_governance_commands

    root = _copy_config_root(tmp_path)
    (root / "projects" / "NovelGen").mkdir(parents=True)
    local_app = typer.Typer()
    register_governance_commands(local_app, root, Console(width=120))

    result = runner.invoke(local_app, ["governance", "doctor", "--project", "NovelGen", "--write-report"])

    assert result.exit_code == 0
    report_path = root / "projects" / "NovelGen" / "project_brain" / "governance_migration_report.yml"
    assert report_path.exists()
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert report["migration_report"]["safe_by_default"] is True


def test_revision_intake_builds_change_request_and_transition():
    change_request, transition = build_revision_intake("Crown_of_Ash", "task_1", "Revise role motive\nAdjust chapter 3 outline")

    assert change_request["change_items"][0]["text"] == "Revise role motive"
    body = transition["state_transition_proposal"]
    assert body["source_change_request"] == "change_request.yml"
    assert body["requires_conflict_check"] is True
    assert body["events"][0]["event_type"] == "propose_revision"


def test_revision_apply_merges_events_and_unblocks_dispatch(tmp_path):
    root = _copy_config_root(tmp_path)
    write_revision_intake(root, "Crown_of_Ash", "task_revision", "Revise role motive")

    pending = revision_dispatch_status(root, "Crown_of_Ash", "task_revision")
    validation = validate_revision(root, "Crown_of_Ash", "task_revision")

    assert pending["blocked"] is True
    assert validation["valid"] is True

    result = apply_revision(root, "Crown_of_Ash", "task_revision", accepted_by="pytest")
    ready = revision_dispatch_status(root, "Crown_of_Ash", "task_revision")

    assert result["applied"] is True
    assert result["knowledge_sync"]["status"] == "SYNCED"
    assert result["knowledge_sync"]["namespaces"] == [
        "project.Crown_of_Ash",
        "domain.longform_narrative",
    ]
    assert ready["blocked"] is False
    assert (
        root
        / "projects"
        / "Crown_of_Ash"
        / "project_brain"
        / "project_fact_events.jsonl"
    ).exists()
    assert (
        root / "projects" / "Crown_of_Ash" / "project_brain" / "revision_log.jsonl"
    ).exists()


def test_candidate_only_state_proposal_does_not_block_audit_dispatch(tmp_path):
    root = _copy_config_root(tmp_path)
    target = root / "projects" / "NovelGen" / "runs" / "task_audit"
    target.mkdir(parents=True)
    (target / "state_transition_proposal.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "candidate",
                "candidate_only": True,
                "production_modified": False,
                "requires_user_promotion": True,
                "events": [{"scope": "candidate_only", "event_type": "continuity_fix"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    dispatch = revision_dispatch_status(root, "NovelGen", "task_audit")

    assert dispatch == {
        "blocked": False,
        "reason": "candidate-only state proposal does not dispatch a revision",
    }


def test_unbounded_state_proposal_still_requires_change_request(tmp_path):
    root = _copy_config_root(tmp_path)
    target = root / "projects" / "NovelGen" / "runs" / "task_unbounded"
    target.mkdir(parents=True)
    (target / "state_transition_proposal.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "candidate",
                "candidate_only": True,
                "production_modified": False,
                "requires_user_promotion": True,
                "events": [{"event_type": "continuity_fix"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    dispatch = revision_dispatch_status(root, "NovelGen", "task_unbounded")

    assert dispatch["blocked"] is True
    assert dispatch["reason"] == (
        "state_transition_proposal.yml exists without change_request.yml"
    )


def test_revision_conflict_checker_detects_snapshot_fact_conflict(tmp_path):
    root = _copy_config_root(tmp_path)
    brain = root / "projects" / "NovelGen" / "project_brain"
    append_project_fact_events(
        brain,
        [
            {
                "event_type": "create",
                "target_kind": "entity",
                "target_type": "character",
                "target_id": "hero",
                "to_status": "active",
                "facts": {"motive": "revenge"},
                "evidence_refs": ["chapter_01.md"],
            }
        ],
    )
    snapshot = rebuild_project_fact_snapshot(brain, project="NovelGen")
    proposal = {
        "events": [
            {
                "event_type": "revise",
                "target_kind": "entity",
                "target_type": "character",
                "target_id": "hero",
                "to_status": "active",
                "facts": {"motive": "mercy"},
                "evidence_refs": ["change_request.yml"],
            }
        ]
    }

    result = check_revision_conflicts(snapshot, proposal)

    assert result["valid"] is False
    assert "conflicts with current snapshot" in result["conflicts"][0]["message"]


def test_pending_revision_blocks_coder_role_session(tmp_path):
    root = _copy_config_root(tmp_path)
    write_revision_intake(root, "NovelGen", "task_revision", "Revise role motive")

    blocked = build_role_session(root, "Coder", "codex", project="NovelGen", task_id="task_revision")
    apply_revision(root, "NovelGen", "task_revision", accepted_by="pytest")
    allowed = build_role_session(root, "Coder", "codex", project="NovelGen", task_id="task_revision")

    assert blocked["binding"]["allowed"] is False
    assert "revision governance blocks Coder dispatch" in blocked["binding"]["reason"]
    assert allowed["binding"]["allowed"] is True


def test_pending_revision_blocks_execute_pipeline_direct_call(tmp_path):
    root = _copy_config_root(tmp_path)
    write_revision_intake(root, "NovelGen", "task_revision", "Revise role motive")

    result = run_full_pipeline(root, "NovelGen", "task_revision", dry_run=False, fake_provider=False, max_steps=1)

    assert result["success"] is False
    assert result["blocked_type"] == "revision_governance"
