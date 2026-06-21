"""Tests for command template validation logic."""

from agent_runtime.workers.command_template_validator import validate_template

def test_validate_template_valid():
    template = 'claude -p "{prompt}"'
    valid, errors = validate_template(template, ["prompt"])
    assert valid is True
    assert len(errors) == 0

def test_validate_template_missing_placeholder():
    template = 'claude -p "static text"'
    valid, errors = validate_template(template, ["prompt"])
    assert valid is False
    assert any("missing" in err for err in errors)

def test_validate_template_unquoted_placeholder():
    template = 'claude -p {prompt}'
    valid, errors = validate_template(template, ["prompt"])
    assert valid is False
    assert any("quoted" in err for err in errors)

def test_validate_template_allow_unquoted():
    template = 'git {args}'
    valid, errors = validate_template(template, ["args"], allow_unquoted_placeholders=True)
    assert valid is True
    assert len(errors) == 0
