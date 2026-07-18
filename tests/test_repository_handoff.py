from __future__ import annotations

from pathlib import Path
import subprocess

from typer.testing import CliRunner

from agent_runtime.repository_handoff import (
    MANUAL_NOTES_END,
    MANUAL_NOTES_START,
    discover_handoff,
    scan_repository,
    update_handoffs,
)
from agent_runtime.run_task import app


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "sample"
    root.mkdir()
    (root / "src").mkdir()
    (root / "docs").mkdir()
    (root / "media").mkdir()
    (root / "node_modules" / "package").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "docs" / "paper.md").write_text("# Paper\n", encoding="utf-8")
    (root / "media" / "cover.png").write_bytes(b"\x89PNG\r\n")
    (root / "media" / "voice.wav").write_bytes(b"RIFF")
    (root / "node_modules" / "package" / "index.js").write_text("ignored\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "AgentLab Tests")
    _git(root, "add", "src", "docs", "media")
    _git(root, "commit", "-m", "initial")
    return root


def test_safe_inventory_covers_modalities_without_dependency_cache(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    snapshot = scan_repository(root)

    assert snapshot["scan"]["content_bulk_read"] is False
    assert snapshot["scan"]["symlink_directories_followed"] is False
    assert snapshot["category_counts"]["code"] == 1
    assert snapshot["category_counts"]["literature"] == 1
    assert snapshot["category_counts"]["image"] == 1
    assert snapshot["category_counts"]["audio"] == 1
    assert all("node_modules" not in path for values in snapshot["category_examples"].values() for path in values)


def test_inventory_excludes_deleted_tracked_paths(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "src" / "main.py").unlink()

    snapshot = scan_repository(root)

    assert snapshot["category_counts"].get("code", 0) == 0
    assert all(
        path != "src/main.py"
        for values in snapshot["category_examples"].values()
        for path in values
    )


def test_update_writes_only_canonical_handoff_and_preserves_notes(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    shared = tmp_path / "shared-memory"
    first = update_handoffs(root, shared)

    root_handoff = root / "PROJECT_HANDOFF.md"
    local = root / ".agentlab" / "HandOff.md"
    compatible = root / "agent_docs" / "HandOff.md"
    mirror = shared / first["repository_id"] / "HandOff.md"
    assert first["handoff_paths"] == [str(root_handoff)]
    assert first["canonical_handoff_path"] == str(root_handoff)
    assert first["shared_copy_written"] is False
    assert root_handoff.is_file()
    assert not local.exists() and not compatible.exists() and not mirror.exists()
    content = root_handoff.read_text(encoding="utf-8")
    assert f"Working root: `{root}`" not in content
    assert "Working root: `.`" in content
    for heading in (
        "## Repository Identity",
        "## Current State",
        "## Project Progress Dashboard",
        "## Active Work and Pending Items",
        "## Directory Routes",
        "## Data and File Structure",
        "## Change History",
        "## Related Repositories",
    ):
        assert heading in content

    root_handoff.write_text(content.replace(
        "- Add durable decisions, constraints, or cross-agent context here.",
        "- Durable manual decision.",
    ), encoding="utf-8")
    (root / "src" / "new.py").write_text("VALUE = 1\n", encoding="utf-8")
    update_handoffs(root, shared)
    refreshed = root_handoff.read_text(encoding="utf-8")
    assert "Durable manual decision" in refreshed
    assert "src/new.py" in refreshed


def test_update_writes_shared_copy_only_when_explicitly_requested(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    shared = tmp_path / "shared-memory"

    result = update_handoffs(root, shared, write_shared_copy=True)

    mirror = shared / result["repository_id"] / "HandOff.md"
    assert result["shared_copy_written"] is True
    assert result["shared_copy_reason"] == "explicit_request"
    assert mirror.is_file()
    assert set(result["handoff_paths"]) == {
        str(root / "PROJECT_HANDOFF.md"),
        str(mirror),
    }


def test_discovery_supports_legacy_handoff_name(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    root.mkdir()
    legacy = root / "HANDOFF.md"
    legacy.write_text("# Legacy\n", encoding="utf-8")
    assert discover_handoff(root) == legacy


def test_discovery_prefers_canonical_handoff_over_legacy_aliases(tmp_path: Path) -> None:
    root = tmp_path / "mixed"
    root.mkdir()
    canonical = root / "PROJECT_HANDOFF.md"
    legacy = root / ".agentlab" / "HandOff.md"
    legacy.parent.mkdir()
    canonical.write_text("# Canonical\n", encoding="utf-8")
    legacy.write_text("# Legacy\n", encoding="utf-8")

    assert discover_handoff(root) == canonical


def test_update_imports_legacy_notes_without_rewriting_legacy_alias(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    shared = tmp_path / "shared-memory"
    legacy = root / ".agentlab" / "HandOff.md"
    legacy.parent.mkdir()
    legacy.write_text(
        "\n".join(
            [
                "# Legacy",
                MANUAL_NOTES_START,
                "- Preserved legacy decision.",
                MANUAL_NOTES_END,
            ]
        ),
        encoding="utf-8",
    )

    result = update_handoffs(root, shared)

    assert result["source_handoff_path"] == str(legacy)
    assert result["legacy_handoff_paths"] == [str(legacy)]
    assert legacy.read_text(encoding="utf-8").startswith("# Legacy")
    assert "Preserved legacy decision" in (root / "PROJECT_HANDOFF.md").read_text(
        encoding="utf-8"
    )


def test_repository_handoff_cli_reports_missing_then_writes(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    shared = tmp_path / "memory"
    runner = CliRunner()

    status = runner.invoke(app, ["repository-handoff", "--repo", str(root), "--shared-memory-root", str(shared)])
    assert status.exit_code == 0, status.output
    assert "status: missing" in status.output
    assert "rerun with --write" in status.output

    write = runner.invoke(app, [
        "repository-handoff", "--repo", str(root), "--shared-memory-root", str(shared), "--write",
    ])
    assert write.exit_code == 0, write.output
    assert "status: updated" in write.output
    assert (root / "PROJECT_HANDOFF.md").is_file()
    assert not (root / ".agentlab" / "HandOff.md").exists()
    assert not shared.exists()

    shared_write = runner.invoke(app, [
        "repository-handoff",
        "--repo",
        str(root),
        "--shared-memory-root",
        str(shared),
        "--write",
        "--shared-copy",
    ])
    assert shared_write.exit_code == 0, shared_write.output
    assert "shared_copy_written: true" in shared_write.output
