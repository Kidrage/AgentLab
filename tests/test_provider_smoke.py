from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.provider_smoke import build_provider_smoke_report
from agent_runtime.run_task import app
from agent_runtime.schemas import LLMCallResult


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_provider_smoke_dry_run_reports_config_without_secret_values() -> None:
    report = build_provider_smoke_report(ROOT, provider="deepseek", model_override="deepseek-v4-flash", live=False)

    assert report["report_type"] == "agentlab_provider_smoke"
    assert report["provider"] == "deepseek"
    assert report["status"] in {"configured", "blocked"}
    assert report["model"] == "deepseek-v4-flash"
    assert report["model_override"] == "deepseek-v4-flash"
    assert report["api_key_value_rendered"] is False
    rendered = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
    assert "sk-" not in rendered


def test_provider_smoke_cli_writes_yaml_report(tmp_path: Path) -> None:
    out = tmp_path / "provider_smoke.yml"

    result = runner.invoke(app, ["provider-smoke", "--provider", "deepseek", "--model", "deepseek-v4-flash", "--out", str(out)])

    assert out.exists()
    report = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert report["report_type"] == "agentlab_provider_smoke"
    assert report["provider"] == "deepseek"
    assert report["model"] == "deepseek-v4-flash"
    if report["status"] == "blocked":
        assert result.exit_code == 1
    else:
        assert result.exit_code == 0


def test_provider_smoke_reports_usage_metadata_for_empty_completed_response(monkeypatch) -> None:
    observed: dict[str, str] = {}
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-provider-key")

    def fake_generate_text(settings, model_providers, messages, *, agent_name=""):
        observed["agent_name"] = agent_name
        return LLMCallResult(
            provider=settings.provider,
            model=settings.model,
            content="",
            input_tokens=9,
            output_tokens=0,
            total_tokens=9,
            raw_usage={"prompt_tokens": 9, "completion_tokens": 0, "total_tokens": 9, "finish_reason": "stop"},
        )

    monkeypatch.setattr("llm_provider.generate_text", fake_generate_text)

    report = build_provider_smoke_report(ROOT, provider="deepseek", model_override="deepseek-v4-flash", live=True)

    assert report["status"] == "warn"
    assert report["reason"] == "provider_connected_but_unexpected_content"
    assert report["content_present"] is False
    assert report["input_tokens"] == 9
    assert report["output_tokens"] == 0
    assert report["total_tokens"] == 9
    assert report["finish_reason"] == "stop"
    assert "finish_reason" in report["raw_usage_keys"]
    assert observed["agent_name"] == "ProviderSmoke"


def test_provider_smoke_pass_omits_empty_error_and_reason(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-provider-key")

    def fake_generate_text(settings, model_providers, messages, *, agent_name=""):
        return LLMCallResult(
            provider=settings.provider,
            model=settings.model,
            content="AGENTLAB_PROVIDER_SMOKE_OK",
            input_tokens=7,
            output_tokens=4,
            total_tokens=11,
            raw_usage={"finish_reason": "stop"},
        )

    monkeypatch.setattr("llm_provider.generate_text", fake_generate_text)

    report = build_provider_smoke_report(ROOT, provider="deepseek", model_override="deepseek-v4-flash", live=True)

    assert report["status"] == "pass"
    assert report["content_present"] is True
    assert "error" not in report
    assert "reason" not in report
