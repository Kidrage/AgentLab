# AgentLab Worker Invocation Contract Report

## Contract Validation Overview

| Worker ID | Display Name | Command | Style | Template Valid | Safe Probe Status | Error Class |
|---|---|---|---|---|---|---|
| `hermes` | Hermes CLI | `hermes` | True | ✅ Yes | ✅ Passed | `none` |
| `claude_code` | Claude Code | `claude` | True | ✅ Yes | ✅ Passed | `none` |
| `bl` | Bailian CLI | `bl` | True | ✅ Yes | ✅ Passed | `none` |
| `aider` | Aider | `aider` | True | ✅ Yes | ⚠️ Skipped | `binary_missing` |
| `codex` | Codex Code | `codex` | True | ✅ Yes | ✅ Passed | `none` |
| `openclaw` | OpenClaw Operator | `openclaw` | True | ✅ Yes | ✅ Passed | `none` |
| `git` | Git VCS | `git` | True | ✅ Yes | ✅ Passed | `none` |

## Detailed Contracts
### Hermes CLI (`hermes`)
- **Command**: `hermes`
- **Template**: `hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}, perform the requested AgentLab role work, and return a concise markdown report with findings, actions taken, verification, and blockers."`
- **Template Valid**: True
- **Safe Probe Status**: passed

### Claude Code (`claude_code`)
- **Command**: `claude`
- **Template**: `claude -p "{prompt}"`
- **Template Valid**: True
- **Safe Probe Status**: passed

### Bailian CLI (`bl`)
- **Command**: `bl`
- **Template**: `bl chat -p "{prompt}"`
- **Template Valid**: True
- **Safe Probe Status**: passed

### Aider (`aider`)
- **Command**: `aider`
- **Template**: `aider --message "{prompt}"`
- **Template Valid**: True
- **Safe Probe Status**: skipped
- **Probe Error Class**: `binary_missing`

### Codex Code (`codex`)
- **Command**: `codex`
- **Template**: `codex --task "{prompt}"`
- **Template Valid**: True
- **Safe Probe Status**: passed

### OpenClaw Operator (`openclaw`)
- **Command**: `openclaw`
- **Template**: `openclaw run --prompt "{prompt}"`
- **Template Valid**: True
- **Safe Probe Status**: passed

### Git VCS (`git`)
- **Command**: `git`
- **Template**: `git {args}`
- **Template Valid**: True
- **Safe Probe Status**: passed
