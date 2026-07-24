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
| config/model_providers.yml | 168 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| .env | 1 | OpenAI API Key | `[FULLY_REDACTED]` |
| .env | 1 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| scripts/p1_acceptance_check.py | 116 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/ingestion/github_reader.py | 110 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/config_center/validator.py | 40 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/config_center/renderer.py | 54 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/config_center/renderer.py | 64 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/config_center/resolver.py | 78 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/config_center/resolver.py | 87 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/config_center/resolver.py | 169 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/narrative/production/live_revision_preflight.py | 209 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/narrative/production/revision_attempts.py | 275 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/narrative/jobs/identity.py | 56 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/narrative/jobs/identity.py | 68 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/search/anysearch_adapter.py | 39 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/.env | 4 | OpenAI API Key | `[FULLY_REDACTED]` |
| agent_runtime/.env | 4 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/.env | 9 | OpenAI API Key | `[FULLY_REDACTED]` |
| agent_runtime/.env | 9 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/.env | 12 | OpenAI API Key | `[FULLY_REDACTED]` |
| agent_runtime/.env | 12 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/.env | 15 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/.env | 16 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/.env | 17 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/media_backend_adapter.py | 1830 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/provider_smoke.py | 38 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/llm_provider.py | 50 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/llm_provider.py | 166 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/run_task.py | 4596 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/truenas_sync.py | 91 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/background_job_controller.py | 438 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/background_job_controller.py | 557 | Generic Assignment Secret | `[FULLY_REDACTED]` |
| agent_runtime/webhook_dispatcher.py | 189 | Generic Assignment Secret | `[FULLY_REDACTED]` |

## Warnings Logged
- Symlink /HOME uses absolute path target: /HOME
- Symlink /HOME uses absolute path target: /HOME
- Symlink /HOME uses absolute path target: /HOME
- Symlink /HOME uses absolute path target: /HOME
- Symlink /HOME uses absolute path target: /HOME
- Symlink /HOME uses absolute path target: /HOME
- Potential secret leak (Generic Assignment Secret) in model_providers.yml:168
- Potential secret leak (OpenAI API Key) in .env:1
- Potential secret leak (Generic Assignment Secret) in .env:1
- Potential secret leak (Generic Assignment Secret) in p1_acceptance_check.py:116
- Potential secret leak (Generic Assignment Secret) in github_reader.py:110
- Potential secret leak (Generic Assignment Secret) in validator.py:40
- Potential secret leak (Generic Assignment Secret) in renderer.py:54
- Potential secret leak (Generic Assignment Secret) in renderer.py:64
- Potential secret leak (Generic Assignment Secret) in resolver.py:78
- Potential secret leak (Generic Assignment Secret) in resolver.py:87
- Potential secret leak (Generic Assignment Secret) in resolver.py:169
- Potential secret leak (Generic Assignment Secret) in live_revision_preflight.py:209
- Potential secret leak (Generic Assignment Secret) in revision_attempts.py:275
- Potential secret leak (Generic Assignment Secret) in identity.py:56
- Potential secret leak (Generic Assignment Secret) in identity.py:68
- Potential secret leak (Generic Assignment Secret) in anysearch_adapter.py:39
- Potential secret leak (OpenAI API Key) in .env:4
- Potential secret leak (Generic Assignment Secret) in .env:4
- Potential secret leak (OpenAI API Key) in .env:9
- Potential secret leak (Generic Assignment Secret) in .env:9
- Potential secret leak (OpenAI API Key) in .env:12
- Potential secret leak (Generic Assignment Secret) in .env:12
- Potential secret leak (Generic Assignment Secret) in .env:15
- Potential secret leak (Generic Assignment Secret) in .env:16
- Potential secret leak (Generic Assignment Secret) in .env:17
- Potential secret leak (Generic Assignment Secret) in media_backend_adapter.py:1830
- Potential secret leak (Generic Assignment Secret) in provider_smoke.py:38
- Potential secret leak (Generic Assignment Secret) in llm_provider.py:50
- Potential secret leak (Generic Assignment Secret) in llm_provider.py:166
- Potential secret leak (Generic Assignment Secret) in run_task.py:4596
- Potential secret leak (Generic Assignment Secret) in truenas_sync.py:91
- Potential secret leak (Generic Assignment Secret) in background_job_controller.py:438
- Potential secret leak (Generic Assignment Secret) in background_job_controller.py:557
- Potential secret leak (Generic Assignment Secret) in webhook_dispatcher.py:189
