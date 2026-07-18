# Retired Runtime Adapters

The archived Aider adapter specification described a standalone invocation-plan
builder that was no longer imported by AgentLab. The corresponding
`agent_runtime/aider_adapter.py`, its permanently empty workflow-plan field, and
the duplicate `agents_def.py` role table were removed on 2026-07-18.

Aider itself remains a registered, scoped Coder worker in
`config/worker_invocation_contracts.yml` and `config/agent_role_bindings.yml`.
It uses the same AgentLab role-session, evidence, and validation boundary as
other workers; there is no second Aider-specific route authority.
