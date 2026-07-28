# CCS (Claude Code Switch) Usage and Safety

AgentLab supports `ccs` as the execution backend for the `claude_code` worker.

## Execution Priority
1. **`ccs`** is the preferred command for Claude Code Switch users.
2. The legacy **`claude`** command remains supported and will act as a fallback if `ccs` is absent.

## Safety & Permissions
1. The `claude_code` worker is inherently **high-risk** and is **disabled by default**. It requires explicit user approval and manual enablement.
2. Normal execution profiles **do not skip permissions**. You will always be prompted by Claude Code.
3. AgentLab has no configured dangerous headless profile.
   `--allow-dangerously-skip-permissions` is rejected by profile validation.

## Testing
AgentLab tests use internal mocking. Automated tests **do not execute** real `ccs` or `claude` binaries, preserving local environment safety.
