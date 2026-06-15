from __future__ import annotations

import importlib.util
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


def test_skill_discovery_config_disabled() -> None:
    import yaml
    data = yaml.safe_load((ROOT / "config" / "skill_discovery.yml").read_text(encoding="utf-8"))
    assert data["enabled"] is False
    assert data["allow_network"] is False
    assert data["auto_import"] is False
    assert data["auto_promote"] is False
