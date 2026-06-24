"""Tests for role coalescing logic."""

from agent_runtime.execution_economy.role_coalescing import coalesce_roles

def test_coalesce_roles():
    roles = ["Supervisor", "PromptEngineer", "Coder", "RepoScout"]

    # Small task should coalesce Supervisor/PromptEngineer/Coder into one packet
    packets = coalesce_roles(roles, task_size="small")

    # Should result in:
    # 1. coalesced_coder_packet with Supervisor, PromptEngineer, Coder
    # 2. single_reposcout_packet with RepoScout (which maps to rg)
    assert len(packets) == 2
    packet_ids = [p.coalesced_packet_id for p in packets]
    assert "coalesced_coder_packet" in packet_ids
    assert "single_reposcout_packet" in packet_ids

    coder_packet = next(p for p in packets if p.coalesced_packet_id == "coalesced_coder_packet")
    assert set(coder_packet.roles) == {"Supervisor", "PromptEngineer", "Coder"}
    assert coder_packet.selected_worker == "claude_code"
