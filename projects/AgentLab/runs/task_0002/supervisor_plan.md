```markdown
# Supervisor Report

## Task
- Task id: task_0002
- User request: "使用 AgentLab 托管本次任务。任务目标：- 将 AgentLab 的网页 UI 改写为纯中文版。- 在 UI 中新增 Qwen 模型选择能力。- UI 要相应展示 Qwen provider、Qwen Coder API fallback、模型选择状态。执行约束：- 本次任务暂时停用 Codex Coder。- Coder 阶段使用 Qwen API。- DeepSeek 继续作为 AgentLab 大脑规划与监督。- 不使用 Codex 写代码。- 不安装依赖。- 先由 AgentLab 管理层规划，再走 DeepSeek brain + Qwen Coder API fallback 路线。"
- Assigned scope: Web UI internationalization (i18n) and feature extension for Qwen model selection — limited to `web_ui/` directory only (`index.html`, `app.js`, `styles.css`); no runtime, CLI, or config changes; no dependency installation; no backend integration; pure static frontend enhancement.

## Work Performed
- Files read:
  - `project_config.yml` ✅
  - `agent_docs/00_CONTEXT_PACK.md` ✅
  - `agent_docs/01_REPO_MAP.md` ✅
  - `config/execution_policy.yml` ✅
  - `runs/task_0002/user_request.md` ✅
- Commands run: none (plan-only phase)
- Brain provider: DeepSeek-V4-Pro (via `env:LLM_PROVIDER:deepseek`)
- Brain API called: no — *planning phase only; this report is the pre-execution contract*
- Brain token usage: unavailable (manual estimation not triggered; no API call made)
- Key observations:
  - User explicitly disabled Codex Coder and mandated Qwen API fallback for implementation — this activates `deepseek_brain_qwen_coder_api` mode per `execution_policy.yml`.
  - UI scope is strictly bounded: `web_ui/index.html`, `web_ui/app.js`, `web_ui/styles.css`. No other files are in scope.
  - “Pure Chinese” requirement implies full i18n of all user-facing strings, including status labels, buttons, tooltips, and error messages — but *no translation of code identifiers, comments, or technical metadata*.
  - Qwen model selection must be non-intrusive: it must coexist with existing DeepSeek status display, preserve data contracts (e.g., `agent_status.sample.json` schema), and avoid breaking `app.js` rendering logic.
  - Critical interface boundary: `app.js` ↔ `index.html` ↔ `agent_status.sample.json`. InterfaceMapper will verify contract stability before Coder edits.

## Findings
- Summary: This is an interface-sensitive frontend task requiring precise i18n and controlled feature injection. All changes are confined to static web assets. No runtime logic, build tooling, or external dependencies are involved.
- Risks:
  - Hardcoded English strings scattered across `index.html` and `app.js` may be missed during scanning → mitigated by RepoScout + InterfaceMapper double-coverage.
  - Qwen state display could conflict with existing DeepSeek status rendering if DOM selectors or update logic overlap → mitigated by InterfaceMapper contract review.
  - `agent_status.sample.json` is referenced as a *future service-compatible payload* — its schema must remain unchanged; only UI interpretation may evolve.
- Blockers:
  - DeepSeek API must be available to execute planning (Supervisor, RepoScout, InterfaceMapper, Tester/Auditor, Archivist). If unavailable, workflow pauses per `execution_policy.yml`.
  - Qwen API access credentials and endpoint configuration are *not provided* in context → Coder phase will require explicit user approval before API invocation (per `coder_policy.quota_fallback`).
  - No `qwen_coder_aux` model profile loaded in current context — will be validated at Coder handoff.

## Route
- Task size: medium
- Agents included: Supervisor → RepoScout → InterfaceMapper → Coder → TesterAuditor → Archivist
- Agents skipped:
  - Researcher: not needed — no external facts, pricing, laws, or vendor docs required (Qwen capability is already declared in config; no API spec research needed at this stage).
  - CodexPromptGenerator: excluded per routing rationale and `skipped_agents` list; not required for Qwen API fallback path.
- Routing rationale: Selected `interface_sensitive_task` route per `config/routing_rules.yml` and user’s explicit UI boundary changes (i18n + new model selector). RepoScout confirms file relevance; InterfaceMapper validates DOM/data contract integrity before editing; Coder uses Qwen API (not Codex) per user mandate; Archivist required for medium+ tasks to update `04_INTERFACE_REGISTRY.md` and `07_DEVELOPMENT_LOG.md`.
- Coder backend: qwen_api_patch_proposal (explicitly mandated; Codex disabled)

## Token Budget
| Phase | Est. Input | Est. Output | Est. Total | Warn At | Stop At | Actual | Variance | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Intake and clarification | 2500 | 1200 | 3700 | 3330 | 4255 | unavailable | — | Pre-execution plan only |
| RepoScout repository scan | 5200 | 2600 | 7800 | 7020 | 8970 | unavailable | — | Will scan `web_ui/` only |
| Interface mapping, if needed | 4200 | 2200 | 6400 | 5760 | 7359 | unavailable | — | Focus: DOM IDs, event handlers, JSON schema alignment |
| Coder implementation or patch proposal | 6200 | 3600 | 9800 | 8820 | 11270 | unavailable | — | Qwen API fallback; outputs `patch_proposal.diff`, `files_to_change.yml` |
| Tester/Auditor validation | 4200 | 2600 | 6800 | 6120 | 7819 | unavailable | — | Validates HTML render + JS behavior via local browser check & diff audit |
| Archivist update | 2600 | 1200 | 3800 | 3420 | 4370 | unavailable | — | Updates `04_INTERFACE_REGISTRY.md`, `07_DEVELOPMENT_LOG.md`, `08_CODEX_DIALOGUE_LOG.md` (as record of Qwen use) |

## Outputs
- Deliverables:
  - `runs/task_0002/supervisor_plan.md` (this report)
  - `runs/task_0002/reposcout_report.md`
  - `runs/task_0002/interface_map.md`
  - `runs/task_0002/implementation_report.md` (Qwen-generated patch + risk log)
  - `runs/task_0002/validation_report.md` + `audit_report.md`
  - `runs/task_0002/archive_update.md`
- Recommended next steps:
  1. ✅ Confirm DeepSeek API availability — if missing, pause and generate `USER_DECISION_REQUIRED.md`.
  2. ✅ Run RepoScout on `web_ui/` to identify all translatable strings and Qwen-relevant DOM elements.
  3. ✅ Run InterfaceMapper to lock `index.html` ↔ `app.js` ↔ `agent_status.sample.json` contracts.
  4. ✅ Hand off to Coder with Qwen API fallback enabled — await `patch_proposal.diff` and `files_to_change.yml`.
  5. ✅ Validate locally (no build step required — static HTML/JS only).
  6. ✅ Archive updates to project memory *only after validation passes*.
```