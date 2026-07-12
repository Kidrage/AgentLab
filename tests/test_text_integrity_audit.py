from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_text_integrity", ROOT / "scripts" / "audit_text_integrity.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_text_integrity"] = module
    spec.loader.exec_module(module)
    return module


def test_audit_detects_large_single_line_python(tmp_path: Path) -> None:
    module = _load_audit_module()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    bad = scripts / "bad.py"
    bad.write_text("x = '" + "a" * 1500 + "'\n", encoding="utf-8")
    audits = module.run_audit(tmp_path)
    assert any(a.path == "scripts/bad.py" and a.suspicious_single_line for a in audits)


def test_audit_skips_venv_cache_and_generated(tmp_path: Path) -> None:
    module = _load_audit_module()
    bad_dir = tmp_path / ".venv" / "lib"
    bad_dir.mkdir(parents=True)
    (bad_dir / "bad.py").write_text("x = '" + "a" * 1500 + "'\n", encoding="utf-8")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "bad.py").write_text("x = '" + "a" * 1500 + "'\n", encoding="utf-8")
    audits = module.run_audit(tmp_path)
    assert audits == []


def test_audit_uses_git_visible_files_and_skips_ignored_runtime(tmp_path: Path) -> None:
    module = _load_audit_module()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / ".gitignore").write_text("docs/ignored.md\n", encoding="utf-8")
    (docs / "visible.md").write_text("# Visible\n", encoding="utf-8")
    (docs / "ignored.md").write_text("# Ignored\n", encoding="utf-8")

    audits = module.run_audit(tmp_path)
    paths = {audit.path for audit in audits}

    assert "docs/visible.md" in paths
    assert "docs/ignored.md" not in paths


def test_skill_discovery_config_disabled() -> None:
    import yaml
    data = yaml.safe_load((ROOT / "config" / "skill_discovery.yml").read_text(encoding="utf-8"))
    assert data["enabled"] is False
    assert data["allow_network"] is False
    assert data["auto_import"] is False
    assert data["auto_promote"] is False



def test_audit_detects_large_single_line_yaml(tmp_path: Path) -> None:
    module = _load_audit_module()
    config = tmp_path / "config"
    config.mkdir()
    bad = config / "bad.yml"
    bad.write_text("items: [" + ", ".join(["x"] * 600) + "]\n", encoding="utf-8")
    audits = module.run_audit(tmp_path)
    assert any(a.path == "config/bad.yml" and a.suspicious_single_line for a in audits)


def test_audit_detects_large_single_line_markdown(tmp_path: Path) -> None:
    module = _load_audit_module()
    docs = tmp_path / "docs"
    docs.mkdir()
    bad = docs / "BAD.md"
    bad.write_text("# Title " + "word " * 400 + "\n", encoding="utf-8")
    audits = module.run_audit(tmp_path)
    assert any(a.path == "docs/BAD.md" and a.suspicious_single_line for a in audits)


def test_audit_allows_long_markdown_table_row(tmp_path: Path) -> None:
    module = _load_audit_module()
    docs = tmp_path / "docs"
    docs.mkdir()
    table = docs / "MATRIX.md"
    table.write_text(
        "# Matrix\n\n"
        "| Name | Detail |\n"
        "|---|---|\n"
        f"| worker | {'x' * 1500} |\n"
        "\nFooter.\n",
        encoding="utf-8",
    )

    audits = module.run_audit(tmp_path)

    assert any(
        audit.path == "docs/MATRIX.md" and not audit.suspicious_single_line
        for audit in audits
    )


def test_audit_detects_local_absolute_path_leak(tmp_path: Path) -> None:
    module = _load_audit_module()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    bad = scripts / "leak.py"
    local_path = "/" + "Users" + "/someone/Desktop/AgentLab"
    bad.write_text(f"p = {local_path!r}\n", encoding="utf-8")

    audits = module.run_audit(tmp_path)

    assert any(
        audit.path == "scripts/leak.py"
        and audit.suspicious_single_line
        and "local absolute" in audit.issue_summary
        for audit in audits
    )


def test_repo_hygiene_source_is_not_flagged_by_audit(tmp_path: Path) -> None:
    module = _load_audit_module()
    target = tmp_path / "agent_runtime" / "project_ops" / "repo_hygiene.py"
    target.parent.mkdir(parents=True)
    source = ROOT / "agent_runtime" / "project_ops" / "repo_hygiene.py"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    audits = module.run_audit(tmp_path)

    assert audits
    assert all(
        not audit.suspicious_single_line
        and not audit.future_import_after_code
        and "local absolute" not in audit.issue_summary
        for audit in audits
        if audit.path == "agent_runtime/project_ops/repo_hygiene.py"
    )


def test_audit_detects_future_import_after_real_code(tmp_path: Path) -> None:
    module = _load_audit_module()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    bad = scripts / "bad_future.py"
    bad.write_text(
        "x = 1\nfrom __future__ import annotations\n",
        encoding="utf-8",
    )

    audits = module.run_audit(tmp_path)

    assert any(
        audit.path == "scripts/bad_future.py"
        and audit.future_import_after_code
        and "appears after code" in audit.issue_summary
        for audit in audits
    )


def test_audit_allows_future_import_after_multiline_module_docstring(tmp_path: Path) -> None:
    module = _load_audit_module()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    good = scripts / "good_future.py"
    good.write_text(
        '"""Module summary.\n\nMore detail.\n"""\n\n'
        "from __future__ import annotations\n\n"
        "x: int = 1\n",
        encoding="utf-8",
    )

    audits = module.run_audit(tmp_path)

    assert any(
        audit.path == "scripts/good_future.py"
        and not audit.suspicious_single_line
        and not audit.future_import_after_code
        for audit in audits
    )
