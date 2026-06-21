# AgentLab Worker Discovery & Doctor Report

**Discovered 9 / 21 available local workers.**

## Worker Discovery Table

| Worker ID | Display Name | Category | Installed | Version | Authenticated | Cost | Risk | Approval Req. |
|---|---|---|---|---|---|---|---|---|
| `claude_code` | Claude Code | `coding_agent` | ✅ Yes | 2.1.185 | ⚠️ No | high | high | True |
| `codex` | Codex Code | `coding_agent` | ✅ Yes | 0.135.0-alpha.1 | ❓ Unknown | high | high | True |
| `aider` | Aider | `coding_agent` | ❌ No | N/A | ⚠️ No | high | high | True |
| `hermes` | Hermes CLI | `planning_agent` | ✅ Yes | 0.17.0 | 🔑 Yes | medium | high | True |
| `qwen` | Qwen CLI | `planning_agent` | ❌ No | N/A | ⚠️ No | medium | medium | True |
| `gemini` | Gemini CLI | `planning_agent` | ❌ No | N/A | ⚠️ No | medium | medium | True |
| `openclaw` | OpenClaw Operator | `frontdesk_agent` | ✅ Yes | 2026.6.9 | ⚠️ No | medium | medium | True |
| `agy` | Antigravity CLI | `frontdesk_agent` | ✅ Yes | 1.0.10 | ⚠️ No | medium | medium | True |
| `bl` | Bailian CLI | `multimodal_cloud_tool` | ✅ Yes | 1.4.0 | 🔑 Yes | medium | medium | True |
| `rg` | Ripgrep | `deterministic_repo_tool` | ❌ No | N/A | ⚠️ No | free | low | False |
| `git` | Git VCS | `vcs_tool` | ✅ Yes | 2.37.1 | 🔑 Yes | free | medium | False |
| `ast_grep` | ast-grep | `deterministic_ast_tool` | ❌ No | N/A | ⚠️ No | free | low | False |
| `sg` | ast-grep (sg) | `deterministic_ast_tool` | ❌ No | N/A | ⚠️ No | free | low | False |
| `pytest` | Pytest | `test_runner` | ✅ Yes | 7.4.0 | 🔑 Yes | free | medium | False |
| `ruff` | Ruff Linter/Formatter | `linter` | ❌ No | N/A | ⚠️ No | free | low | False |
| `eslint` | ESLint | `linter` | ❌ No | N/A | ⚠️ No | free | low | False |
| `mypy` | Mypy Type Checker | `linter` | ❌ No | N/A | ⚠️ No | free | low | False |
| `npm` | NPM | `shell_tool` | ✅ Yes | 10.9.8 | 🔑 Yes | free | medium | False |
| `pnpm` | PNPM | `shell_tool` | ❌ No | N/A | ⚠️ No | free | medium | False |
| `uv` | UV Package Manager | `shell_tool` | ❌ No | N/A | ⚠️ No | free | medium | False |
| `docker` | Docker Container Tool | `container_tool` | ❌ No | N/A | ⚠️ No | free | high | True |

## Installed Worker Details

### Claude Code (`claude_code`)
- **Command**: `claude`
- **Category**: `coding_agent`
- **Version**: `2.1.185`
- **Authenticated**: `no`
- **Best For**: repo_level_coding, architecture_reasoning, large_refactor
- **Avoid For**: deterministic_search, cheap_lint, secret_handling

### Codex Code (`codex`)
- **Command**: `codex`
- **Category**: `coding_agent`
- **Version**: `0.135.0-alpha.1`
- **Authenticated**: `unknown`
- **Best For**: refactoring, documentation
- **Avoid For**: interactive_debugging

### Hermes CLI (`hermes`)
- **Command**: `hermes`
- **Category**: `planning_agent`
- **Version**: `0.17.0`
- **Authenticated**: `yes`
- **Best For**: multi_agent_planning, supervision
- **Avoid For**: simple_file_edits

### OpenClaw Operator (`openclaw`)
- **Command**: `openclaw`
- **Category**: `frontdesk_agent`
- **Version**: `2026.6.9`
- **Authenticated**: `no`

### Antigravity CLI (`agy`)
- **Command**: `agy`
- **Category**: `frontdesk_agent`
- **Version**: `1.0.10`
- **Authenticated**: `no`

### Bailian CLI (`bl`)
- **Command**: `bl`
- **Category**: `multimodal_cloud_tool`
- **Version**: `1.4.0`
- **Authenticated**: `yes`
- **Best For**: paid_generation, image_processing, multimodal

### Git VCS (`git`)
- **Command**: `git`
- **Category**: `vcs_tool`
- **Version**: `2.37.1`
- **Authenticated**: `yes`

### Pytest (`pytest`)
- **Command**: `pytest`
- **Category**: `test_runner`
- **Version**: `7.4.0`
- **Authenticated**: `yes`

### NPM (`npm`)
- **Command**: `npm`
- **Category**: `shell_tool`
- **Version**: `10.9.8`
- **Authenticated**: `yes`
