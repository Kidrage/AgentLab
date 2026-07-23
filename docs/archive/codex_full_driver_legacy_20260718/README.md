# Retired Codex Full-Driver Materials

These documents and templates preserve the pre-2026-07-18 design in which one
Codex session could emulate an entire AgentLab route.

They are historical evidence only. AgentLab does not load templates from this
directory and `config/execution_modes.yml` forbids new full-driver dispatch.
Current tasks use AgentLab-owned routing plus one scoped role session per
assignment. The useful parts of the old design were absorbed as follows:

- preflight and edit scope: `DRIVER_PROTOCOL.md` and task packets;
- role outputs: active templates registered by `config/agent_registry.yml`;
- lifecycle and validation: production-pack role contracts and deterministic gates;
- handoff/resume: run-local state and `handoff_packet.yml` compatibility helpers;
- audit independence: `config/agent_role_bindings.yml` and production pack policy.

Do not move these files back into `agent_templates/` or active docs. Historical
task plans containing `codex_full_driver` remain readable but cannot be newly
dispatched.
