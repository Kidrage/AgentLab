# CCS (Claude Code Switch) Usage and Safety

AgentLab supports `ccs` as the execution backend for the `claude_code` worker.

## Execution Priority
1. **`ccs`** is the preferred command for Claude Code Switch users.
2. The legacy **`claude`** command remains supported and will act as a fallback if `ccs` is absent.

## Safety & Permissions
1. The `claude_code` worker is inherently **high-risk** and is **disabled by default**. It requires explicit user approval and manual enablement.
2. Normal execution profiles **do not skip permissions**. You will always be prompted by Claude Code.
3. **Dangerous headless mode** (`--allow-dangerously-skip-permissions`) is strictly isolated and **explicit opt-in only**.
4. To execute the dangerous headless mode, you must enable the explicitly trusted profile (`trusted_headless_cli`) and set the environment gate:
   ```bash
   export AGENTLAB_ALLOW_DANGEROUS_CCS=1
   ```

## Testing
AgentLab tests use internal mocking. Automated tests **do not execute** real `ccs` or `claude` binaries, preserving local environment safety.
