# AgentLab CLI Entrypoint Bootstrap

Authority: `_shared/AGENT_PROTOCOL.md`

This bootstrap installs project-local entrypoint files and reliable wrappers for
recognized local agent CLIs. It is meant for first entry into a new AgentLab
workspace.

## Commands

Scan recognized configurable CLIs:

```bash
./agentlab.sh cli-entrypoint-scan
```

Plan bootstrap:

```bash
./agentlab.sh cli-entrypoint-bootstrap
```

Write project-local entrypoints and wrappers:

```bash
./agentlab.sh cli-entrypoint-bootstrap --write
```

Validate installed entrypoints and wrappers:

```bash
./agentlab.sh cli-entrypoint-doctor
```

## Generated Local Files

Entrypoint files are project-local and ignored by Git:

```text
.agy/AGENTLAB_ENTRYPOINT.md
.claude/AGENTLAB_ENTRYPOINT.md
.hermes/AGENTLAB_ENTRYPOINT.md
.codex/AGENTLAB_ENTRYPOINT.md
.qwen/AGENTLAB_ENTRYPOINT.md
```

Wrappers are also local runtime files:

```text
.agentlab/cli_entrypoints/wrappers/frontdesk/<agent>-agentlab
.agentlab/cli_entrypoints/wrappers/workers/<agent>-role-agentlab
```

## Strong Path

The entrypoint files are advisory because each external CLI decides which
project files it auto-reads. The wrappers are the reliable path. A compliant
wrapper must:

- run `./agentlab.sh protocol-doctor`
- generate `frontdesk-session` or `role-session`
- run `role-doctor` for role workers
- pass the generated packet to the external CLI

## Safety

Bootstrap only updates AgentLab managed blocks in project-local files. It does
not edit user-global `~/.claude`, `~/.hermes`, `~/.agy`, or similar directories.
