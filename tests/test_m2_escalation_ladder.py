"""Tests for escalation ladder state transitions."""

from agent_runtime.execution_economy.escalation_ladder import EscalationLadder

def test_escalation_ladder():
    ladder = EscalationLadder()
    
    assert ladder.get_escalation_target("initial") == "deterministic_scan"
    assert ladder.get_escalation_target("if_patch_needed") == "single_cli_coder"
    assert ladder.get_escalation_target("if_tests_fail") == "cached_failure_analyzer"
    assert ladder.get_escalation_target("invalid_trigger") == "stop_or_ask_user"
