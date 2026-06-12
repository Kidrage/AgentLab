# AgentLab P0.1 Pipeline Integration

P0.1 wires the P0 safety modules into the task pipeline so GitHub repository
analysis defaults to API-first evidence instead of implicit cloning.

## Supported

- Repo analysis / repo_profile requests with GitHub URLs generate `repo_manifest.json` (or `repo_manifests/*.json`) before lifecycle execution.
- `resource_ledger.yml` records `clone_performed=false`, `clone_allowed=false`, `full_clone_allowed=false`, and `build_allowed=false` for repo_profile.
- `stage_context.yml` records manifest paths and repo_profile access mode for downstream agents and artifact gates.
- `command_runner.run_logged_command()` evaluates high-cost repo commands with CloneGuard before subprocess execution.
- Cost ledger updates refresh `cost_summary.md` and always write `budget_gate_decision.yml`.
- Artifact gate checks repository/file/clone/command claims against manifest/resource/execution evidence.

## Not Supported

- AnySearch integration.
- CodeGraph integration.
- MAVIS / 3E workflow.
- Multimodal model gateway.
- LiteLLM Proxy deployment.
- Treating ChatGPT/Codex subscriptions as API calls.

## Next Reserved Steps

- P1-A AnySearch skill adapter.
- P1-B CodeGraph repo indexer.
- P1-C MAVIS-style 3E review workflow.
- P2 multimodal model gateway.
- P3 external IDE executor / optional LiteLLM gateway.