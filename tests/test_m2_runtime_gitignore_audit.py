"""Tests for gitignore audit in agent_runtime.runtime_hygiene.gitignore_audit."""

from pathlib import Path
from agent_runtime.runtime_hygiene.gitignore_audit import audit_gitignore, REQUIRED_RULES

def test_audit_gitignore_missing_file(tmp_path):
    report = audit_gitignore(tmp_path)
    data = report.to_dict()
    
    assert len(data["missing_rules"]) == len(REQUIRED_RULES)
    assert any("does not exist" in w for w in data["warnings"])

def test_audit_gitignore_partial_rules(tmp_path):
    gitignore = tmp_path / ".gitignore"
    # Write only a few rules
    rules_present = [".agents/", "*.log", ".env"]
    gitignore.write_text("\n".join(rules_present) + "\n", encoding="utf-8")
    
    report = audit_gitignore(tmp_path)
    data = report.to_dict()
    
    # Missing rules should not include the present ones
    for rule in rules_present:
        assert rule not in data["missing_rules"]
        
    # The others should be missing
    for rule in REQUIRED_RULES:
        if rule not in rules_present:
            assert rule in data["missing_rules"]

def test_audit_gitignore_all_rules(tmp_path):
    gitignore = tmp_path / ".gitignore"
    # Write all required rules and some comments/extra rules
    content = "# Gitignore for testing\n"
    content += "\n".join(REQUIRED_RULES) + "\n"
    content += "extra_rule/\n"
    
    gitignore.write_text(content, encoding="utf-8")
    
    report = audit_gitignore(tmp_path)
    data = report.to_dict()
    
    assert len(data["missing_rules"]) == 0
    assert len(data["warnings"]) == 0
