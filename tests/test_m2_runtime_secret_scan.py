"""Tests for secret scanner in agent_runtime.runtime_hygiene.secret_scan."""

from pathlib import Path
from agent_runtime.runtime_hygiene.secret_scan import scan_secrets

def test_scan_secrets_detects_keys(tmp_path):
    # Create files containing keys
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    
    # Python file with an API key
    py_file = src_dir / "app.py"
    py_file.write_text("openai_key = 'sk-abcdefghijklmnopqrstuvwxyz1234567890'\n", encoding="utf-8")
    
    # Env file
    env_file = tmp_path / ".env"
    env_file.write_text("MY_SECRET=sk-ant-1234567890123456789012345678901234567890\n", encoding="utf-8")
    
    # Generic secret
    config_file = src_dir / "config.yml"
    config_file.write_text("db_password: 'supersecretpassword123'\n", encoding="utf-8")
    
    report = scan_secrets(tmp_path)
    data = report.to_dict()
    
    findings = data["findings"]
    assert len(findings) >= 3
    
    patterns = [f["pattern_matched"] for f in findings]
    assert "OpenAI API Key" in patterns
    assert "Anthropic API Key" in patterns
    assert "Generic Assignment Secret" in patterns
    
    # Verify snippets are redacted
    for finding in findings:
        assert "sk-abcdef" not in finding["snippet_redacted"]
        assert "supersecretpassword" not in finding["snippet_redacted"]

def test_scan_secrets_ignores_placeholders(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    
    py_file = src_dir / "app.py"
    py_file.write_text("openai_key = 'your_api_key_here'\npassword = 'dummy_password'\n", encoding="utf-8")
    
    report = scan_secrets(tmp_path)
    data = report.to_dict()
    
    assert len(data["findings"]) == 0

def test_scan_secrets_ignores_non_scannable_files(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    
    # A .bin file that contains a matching string but should be ignored
    bin_file = src_dir / "app.bin"
    bin_file.write_text("sk-abcdefghijklmnopqrstuvwxyz1234567890\n", encoding="utf-8")
    
    report = scan_secrets(tmp_path)
    data = report.to_dict()
    
    assert len(data["findings"]) == 0

def test_scan_secrets_does_not_follow_symlinks(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    
    # Symlink directory to avoid traversal recursion loops
    linked_dir = tmp_path / "linked"
    linked_dir.mkdir()
    (linked_dir / "secret.py").write_text("openai_key = 'sk-abcdefghijklmnopqrstuvwxyz1234567890'\n", encoding="utf-8")
    
    # Symlink linked_dir under src_dir
    sym_dir = src_dir / "sym_dir"
    sym_dir.symlink_to(linked_dir, target_is_directory=True)
    
    report = scan_secrets(tmp_path)
    data = report.to_dict()
    
    # Since secret.py is inside linked/ (scanned directly) and sym_dir/ (should not be followed):
    # Wait, linked/ is not ignored, so it is scanned. But if we check sym_dir/, it should not be scanned a second time via symlink.
    # Let's write a file inside a directory outside the root, and symlink it.
    # Create outside dir
    outside_dir = tmp_path.parent / "outside_dir"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "secret.py").write_text("openai_key = 'sk-abcdefghijklmnopqrstuvwxyz1234567890'\n", encoding="utf-8")
    
    # Symlink outside_dir under src_dir
    sym_outside = src_dir / "sym_outside"
    sym_outside.symlink_to(outside_dir, target_is_directory=True)
    
    report = scan_secrets(tmp_path)
    data = report.to_dict()
    
    # findings should only find the one in linked/secret.py, not the one in outside_dir via symlink!
    # Wait, the number of findings under src/sym_outside should be 0.
    files = [f["file"] for f in data["findings"]]
    for f in files:
        assert "sym_outside" not in f
