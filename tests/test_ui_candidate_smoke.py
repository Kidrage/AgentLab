from __future__ import annotations

from pathlib import Path

import json
import struct
import sys
import zlib
from typer.testing import CliRunner

from agent_runtime.run_task import app
from agent_runtime import ui_candidate_smoke
from agent_runtime.ui_candidate_smoke import (
    _append_ui_action_ledger,
    analyze_png_pixels,
    run_web_ui_browser_smoke,
    run_web_ui_candidate_smoke,
    run_web_ui_interaction_smoke,
    run_web_ui_responsive_smoke,
    run_web_ui_visual_smoke,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_WEB_UI_DIR = ROOT / "tests" / "fixtures" / "ui_candidate"
runner = CliRunner()


def test_web_ui_candidate_smoke_executes_dom_fetch_contract() -> None:
    report = run_web_ui_candidate_smoke(ROOT, FIXTURE_WEB_UI_DIR)

    assert report["status"] == "pass"
    dom = next(check for check in report["checks"] if check["id"] == "dom_execution")
    assert dom["status"] == "pass"
    assert dom["fetchedPath"] == "./status.sample.json"
    assert dom["hasExpectedContent"] is True
    assert set(dom["renderedLengths"]) == {
        "workflow-actions",
        "action-ledger",
        "production-packs",
        "lifecycle",
        "selected-detail",
        "evidence-ledger",
        "provider-health",
        "project-memory",
    }


def test_web_ui_candidate_smoke_cli_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "ui_candidate_smoke_report.json"

    result = runner.invoke(
        app,
        [
            "web-ui-candidate-smoke",
            "--web-ui-dir",
            str(FIXTURE_WEB_UI_DIR),
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "pass"


def test_web_ui_interaction_smoke_exercises_operator_workflow() -> None:
    report = run_web_ui_interaction_smoke(ROOT, FIXTURE_WEB_UI_DIR)

    assert report["status"] == "pass"
    interaction = next(check for check in report["checks"] if check["id"] == "interaction_execution")
    assert interaction["status"] == "pass"
    assert interaction["checks"]["blockedFilterWorks"] is True
    assert interaction["checks"]["lifecycleSelectionWorks"] is True
    assert interaction["filteredState"]["visiblePackIds"] == ["media_series_production"]
    assert interaction["selectedState"]["selectedNode"] == "VALIDATION"


def test_web_ui_interaction_smoke_cli_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "ui_interaction_smoke_report.json"

    result = runner.invoke(
        app,
        [
            "web-ui-interaction-smoke",
            "--web-ui-dir",
            str(FIXTURE_WEB_UI_DIR),
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "pass"


def test_ui_action_ledger_append_is_candidate_only(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ui_action_ledger.json"

    entry = _append_ui_action_ledger(
        ledger_path,
        {
            "actionType": "record_validation_review",
            "selectedNode": "VALIDATION",
        },
    )

    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert entry["scope"] == "candidate_run_local"
    assert entry["production_modified"] is False
    assert ledger["candidate_only"] is True
    assert ledger["production_modified"] is False
    assert ledger["actions"][0]["action"]["actionType"] == "record_validation_review"


def test_web_ui_api_smoke_cli_writes_report_with_stub(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "ui_candidate_smoke", ui_candidate_smoke)

    def fake_write(root, out, web_ui_dir=None):
        report = {
            "status": "pass",
            "ledger_path": str(tmp_path / "ui_action_ledger.json"),
            "checks": [{"id": "api_response_recorded", "status": "pass"}],
        }
        out.write_text(json.dumps(report), encoding="utf-8")
        return report

    monkeypatch.setattr(ui_candidate_smoke, "write_web_ui_api_smoke", fake_write)
    out = tmp_path / "ui_api_smoke_report.json"

    result = runner.invoke(app, ["web-ui-api-smoke", "--out", str(out)])

    assert result.exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "pass"


def test_browser_smoke_reports_blocked_when_chrome_missing(monkeypatch) -> None:
    monkeypatch.setattr(ui_candidate_smoke, "_find_chrome", lambda: None)

    report = run_web_ui_browser_smoke(ROOT)

    assert report["status"] == "blocked"
    assert report["reason"] == "Chrome/Chromium executable not found"


def test_browser_expected_content_contract() -> None:
    dom = """
    <section id="production-packs">code_factory</section>
    <section id="lifecycle">INIT_TASK SUPERVISOR_PLAN</section>
    <section id="evidence-ledger">implementation_report</section>
    <section id="provider-health">deepseek codex</section>
    <section id="project-memory">07_DEVELOPMENT_LOG.md 08_CODEX_DIALOGUE_LOG.md</section>
    """

    assert all(ui_candidate_smoke._browser_expected_content(dom).values())


def _write_test_png(path: Path) -> None:
    width = 16
    height = 16
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row.extend(((x * 17) % 256, (y * 17) % 256, ((x + y) * 11) % 256, 255))
        rows.append(b"\x00" + bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        import binascii

        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_png_pixel_analyzer_detects_nonblank_image(tmp_path: Path) -> None:
    png = tmp_path / "sample.png"
    _write_test_png(png)

    report = analyze_png_pixels(png)

    assert report["status"] == "pass"
    assert report["width"] == 16
    assert report["height"] == 16
    assert report["unique_sampled_colors"] >= 8


def test_visual_smoke_reports_blocked_when_chrome_missing(monkeypatch) -> None:
    monkeypatch.setattr(ui_candidate_smoke, "_find_chrome", lambda: None)

    report = run_web_ui_visual_smoke(ROOT)

    assert report["status"] == "blocked"
    assert report["reason"] == "Chrome/Chromium executable not found"


def test_visual_smoke_cli_writes_blocked_report_when_chrome_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "ui_candidate_smoke", ui_candidate_smoke)
    monkeypatch.setattr(ui_candidate_smoke, "_find_chrome", lambda: None)
    out = tmp_path / "ui_visual_smoke_report.json"
    screenshot = tmp_path / "ui_visual_smoke.png"

    result = runner.invoke(
        app,
        ["web-ui-visual-smoke", "--out", str(out), "--screenshot", str(screenshot)],
    )

    assert result.exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "blocked"


def test_responsive_smoke_aggregates_desktop_and_mobile(monkeypatch, tmp_path: Path) -> None:
    def fake_visual(root, web_ui_dir=None, screenshot_path=None, viewport=(1280, 900)):
        return {
            "status": "pass",
            "screenshot_path": str(screenshot_path),
            "viewport": {"width": viewport[0], "height": viewport[1]},
            "pixel_report": {
                "status": "pass",
                "width": viewport[0],
                "height": viewport[1],
                "unique_sampled_colors": 16,
            },
        }

    monkeypatch.setattr(ui_candidate_smoke, "run_web_ui_visual_smoke", fake_visual)

    report = run_web_ui_responsive_smoke(ROOT)

    assert report["status"] == "pass"
    assert set(report["viewports"]) == {"desktop", "mobile"}
    assert report["viewports"]["desktop"]["viewport"]["width"] == 1280
    assert report["viewports"]["mobile"]["viewport"]["width"] == 390


def test_responsive_smoke_cli_writes_blocked_report_when_chrome_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "ui_candidate_smoke", ui_candidate_smoke)
    monkeypatch.setattr(ui_candidate_smoke, "_find_chrome", lambda: None)
    out = tmp_path / "ui_responsive_smoke_report.json"

    result = runner.invoke(app, ["web-ui-responsive-smoke", "--out", str(out)])

    assert result.exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "blocked"
    assert set(data["viewports"]) == {"desktop", "mobile"}
