# AgentLab Runtime Hygiene Report

## Verdict: WARNING

## Layout Overview
- **AgentLab Root**: `/HOME`
- **Profiles Dir**: `.agents/profiles`
- **Workspaces Dir**: `.agents/workspaces`
- **Bridges Dir**: `.agents/bridges`
- **Logs Dir**: `.agents/logs`
- **Runtime Dir**: `.agents/runtime`

### Profiles
| Name | Path | Exists | Symlink | Git Tracked | Risk Flags |
|---|---|---|---|---|---|
| claude | .agents/profiles/claude | False | False | False | none |
| codex | .agents/profiles/codex | False | False | False | none |
| qwen | .agents/profiles/qwen | False | False | False | none |
| hermes | .agents/profiles/hermes | False | False | False | none |
| gemini | .agents/profiles/gemini | False | False | False | none |
| bailian | .agents/profiles/bailian | False | False | False | none |
| openclaw | .agents/profiles/openclaw | False | False | False | none |

### Workspaces
| Name | Path | Exists | Symlink | Git Tracked | Cleanable | Risk Flags |
|---|---|---|---|---|---|---|
| claude | .agents/workspaces/claude | False | False | False | True | none |
| codex | .agents/workspaces/codex | False | False | False | True | none |
| qwen | .agents/workspaces/qwen | False | False | False | True | none |
| hermes | .agents/workspaces/hermes | False | False | False | True | none |
| openclaw | .agents/workspaces/openclaw | False | False | False | True | none |
| generic_cli | .agents/workspaces/generic_cli | False | False | False | True | none |

## Symlink Audit
| Path | Target | Valid | Outside | Absolute | Risk Flags |
|---|---|---|---|---|---|
| .qwen | /HOME | True | False | True | absolute_path_symlink |
| .gemini | /HOME | True | False | True | absolute_path_symlink |
| .claude | /HOME | True | False | True | absolute_path_symlink |
| .codex | /HOME | True | False | True | absolute_path_symlink |
| .claude.json | /HOME | True | False | True | absolute_path_symlink |
| .hermes | /HOME | True | False | True | absolute_path_symlink |

## Gitignore Audit
All required rules exist in .gitignore.

## Secret Scan
| File | Line | Pattern | Snippet (Redacted) |
|---|---|---|---|
| config/model_providers.yml | 140 | Generic Assignment Secret | `    api_key: env:AGENTLAB_LOCAL_API_KEY:********` |
| scripts/p1_acceptance_check.py | 116 | Generic Assignment Secret | `        "Task summary: local fake repo only. GITHUB_TOKEN=******** sk_test_should_not_render",` |
| agent_runtime/ingestion/github_reader.py | 110 | Generic Assignment Secret | `    token = ********("GITHUB_TOKEN")` |
| agent_runtime/search/anysearch_adapter.py | 39 | Generic Assignment Secret | `        self.api_key = ********(self.api_key_env)` |
| agent_runtime/.env | 4 | OpenAI API Key | `DEEPSEEK_API_KEY=********` |
| agent_runtime/.env | 4 | Generic Assignment Secret | `DEEPSEEK_API_KEY=********` |
| agent_runtime/.env | 9 | OpenAI API Key | `QWEN_API_KEY=********` |
| agent_runtime/.env | 9 | Generic Assignment Secret | `QWEN_API_KEY=********` |
| agent_runtime/.env | 12 | OpenAI API Key | `DASHSCOPE_API_KEY=********` |
| agent_runtime/.env | 12 | Generic Assignment Secret | `DASHSCOPE_API_KEY=********` |
| agent_runtime/llm_provider.py | 56 | Generic Assignment Secret | `    api_key = ********(provider_config.get("api_key"), "")` |
| agent_runtime/llm_provider.py | 149 | Generic Assignment Secret | `    api_key = ********(model_providers, settings.provider)` |
| agent_runtime/run_task.py | 4044 | Generic Assignment Secret | `    api_key = ********(cfg.get("api_key"), "")` |
| agent_runtime/truenas_sync.py | 91 | Generic Assignment Secret | `    password = ********("AGENTLAB_TRUENAS_PASSWORD", "").strip()` |
| agent_runtime/webhook_dispatcher.py | 189 | Generic Assignment Secret | `        secret = ********(endpoint.get("secret_env", ""))` |

## Warnings Logged
- Symlink /HOME uses absolute path target: /HOME
- Symlink /HOME uses absolute path target: /HOME
- Symlink /HOME uses absolute path target: /HOME
- Symlink /HOME uses absolute path target: /HOME
- Symlink /HOME uses absolute path target: /HOME
- Symlink /HOME uses absolute path target: /HOME
- Potential secret leak (Generic Assignment Secret) in model_providers.yml:140
- Potential secret leak (Generic Assignment Secret) in p1_acceptance_check.py:116
- Potential secret leak (Generic Assignment Secret) in github_reader.py:110
- Potential secret leak (Generic Assignment Secret) in anysearch_adapter.py:39
- Potential secret leak (OpenAI API Key) in .env:4
- Potential secret leak (Generic Assignment Secret) in .env:4
- Potential secret leak (OpenAI API Key) in .env:9
- Potential secret leak (Generic Assignment Secret) in .env:9
- Potential secret leak (OpenAI API Key) in .env:12
- Potential secret leak (Generic Assignment Secret) in .env:12
- Potential secret leak (Generic Assignment Secret) in llm_provider.py:56
- Potential secret leak (Generic Assignment Secret) in llm_provider.py:149
- Potential secret leak (Generic Assignment Secret) in run_task.py:4044
- Potential secret leak (Generic Assignment Secret) in truenas_sync.py:91
- Potential secret leak (Generic Assignment Secret) in webhook_dispatcher.py:189
