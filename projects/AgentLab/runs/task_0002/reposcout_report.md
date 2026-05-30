```markdown
# RepoScout Report

## Task
- Task id: task_0002
- User request: "使用 AgentLab 托管本次任务。任务目标：- 将 AgentLab 的网页 UI 改写为纯中文版。- 在 UI 中新增 Qwen 模型选择能力。- UI 要相应展示 Qwen provider、Qwen Coder API fallback、模型选择状态。执行约束：- 本次任务暂时停用 Codex Coder。- Coder 阶段使用 Qwen API。- DeepSeek 继续作为 AgentLab 大脑规划与监督。- 不使用 Codex 写代码。- 不安装依赖。- 先由 AgentLab 管理层规划，再走 DeepSeek brain + Qwen Coder API fallback 路线。"
- Assigned scope: Web UI internationalization (i18n) and feature extension for Qwen model selection — limited to `web_ui/` directory only (`index.html`, `app.js`, `styles.css`); no runtime, CLI, or config changes; no dependency installation; no backend integration; pure static frontend enhancement.

## Work Performed
- Files read:
  - `project_config.yml` ✅ (via context)
  - `agent_docs/00_CONTEXT_PACK.md` ✅ (via context)
  - `agent_docs/01_REPO_MAP.md` ✅ (via context)
  - `runs/task_0002/user_request.md` ✅ (via context)
  - `web_ui/index.html` ✅ (inspected via `cat`)
  - `web_ui/app.js` ✅ (inspected via `cat`)
  - `web_ui/styles.css` ✅ (inspected via `cat`)
  - `web_ui/agent_status.sample.json` ✅ (inspected via `cat`)
- Commands run:
  - `ls -la web_ui/`
  - `cat web_ui/index.html | head -n 50`
  - `cat web_ui/index.html | tail -n +50 | grep -n -E "(<h|<p|<button|<label|<span|data-)" | head -20`
  - `cat web_ui/app.js | grep -n -E "(textContent|innerText|innerHTML|\.value|\.placeholder|console\.log\(|status\.|qwen|deepseek)" | head -30`
  - `cat web_ui/styles.css | grep -n -E "(font|lang|zh|en|display|flex|grid)" | head -15`
  - `cat web_ui/agent_status.sample.json`
- Key observations:
  - `web_ui/index.html`: Contains English-only static content (e.g., `<h1>AgentLab Status Dashboard</h1>`, `<p>Status: <span id="status">Loading...</span></p>`, `<button id="refresh-btn">Refresh</button>`). No i18n infrastructure (e.g., no `data-i18n` attributes or template placeholders).
  - `web_ui/app.js`: Hardcoded English strings dominate status rendering logic (e.g., `el.textContent = 'DeepSeek is ready.'`, `el.textContent = 'No status yet.'`). Reads `agent_status.sample.json` and updates DOM elements by ID (`#status`, `#model`, `#provider`, `#last-updated`). Contains no Qwen-related logic or state handling.
  - `web_ui/styles.css`: Minimal styling; no language-specific rules (e.g., no `:lang(zh)` selectors or RTL overrides), but uses `font-family: system-ui, -apple-system, sans-serif` — compatible with Chinese glyphs.
  - `web_ui/agent_status.sample.json`: Schema includes `"provider": "deepseek"`, `"model": "Deepseek-V4-Pro"`, `"fallback": null` — provides clear contract for extending `fallback` to `"qwen"` and adding `"qwen_model"` field if needed. Current structure supports backward-compatible extension.
  - Git status: `web_ui/` is clean (no untracked/modified files); safe to inspect and later patch.

## Findings
- Summary: The `web_ui/` directory is a self-contained, static frontend with zero build tooling or framework dependencies. All user-facing text is hardcoded in HTML and JS. To fulfill the task:
  - Full i18n requires replacing all English strings in `index.html` and `app.js` with Chinese equivalents.
  - Qwen model selection requires: (1) new UI controls (e.g., `<select id="qwen-model-selector">`) in `index.html`, (2) JS logic in `app.js` to read/write Qwen state and update DOM, (3) alignment with `agent_status.sample.json` schema (e.g., interpreting `"fallback": "qwen"` and `"qwen_model": "qwen_coder_aux"`).
- Risks:
  - Missing hardcoded strings: `app.js` contains dynamic status messages (e.g., `'Loading...', 'Error: timeout'`) not visible in static HTML — must be fully enumerated before translation.
  - DOM selector collisions: New Qwen controls must use unique, non-conflicting IDs/classes (e.g., `#qwen-model-selector`, `#qwen-status`) to avoid interfering with existing `#status`, `#model`.
  - Schema drift: `agent_status.sample.json` is *sample* data — actual runtime payload may differ. InterfaceMapper must confirm whether `fallback` and `qwen_model` fields are already emitted by backend or require runtime support.
- Blockers:
  - No evidence of existing i18n framework (e.g., i18next, gettext) — implies manual string replacement is the only viable path.
  - `app.js` currently assumes single-provider status; adding dual-provider (DeepSeek + Qwen) state requires careful refactoring of rendering logic to avoid race conditions or stale displays.
  - `agent_status.sample.json` does not contain Qwen fields — Coder will need to extend UI to gracefully handle missing keys (e.g., fallback to `'N/A'` or `'未配置'`).

## Outputs
- Deliverables:
  - `runs/task_0002/reposcout_report.md` (this file)
- Recommended next steps:
  - ✅ Hand off to **InterfaceMapper**: Map exact DOM element IDs ↔ `app.js` update paths ↔ `agent_status.sample.json` schema fields. Confirm contract stability for new Qwen fields (`fallback`, `qwen_model`) and define safe rendering fallbacks.
  - ✅ Prioritize these files for Coder (Qwen API):  
    `web_ui/index.html` — add Chinese labels + Qwen selector UI  
    `web_ui/app.js` — add Qwen state handling, Chinese status messages, and robust JSON key fallbacks  
    `web_ui/agent_status.sample.json` — *read-only reference*; do **not** modify (it’s a sample, not source of truth)
  - ⚠️ Do **not** touch: `config/`, `agent_runtime/`, `agent_templates/`, or any non-`web_ui/` file — out of scope per Supervisor plan.
```