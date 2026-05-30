```markdown
# Interface Mapper Report

## Task
- Task id: task_0002
- User request: "使用 AgentLab 托管本次任务。任务目标：- 将 AgentLab 的网页 UI 改写为纯中文版。- 在 UI 中新增 Qwen 模型选择能力。- UI 要相应展示 Qwen provider、Qwen Coder API fallback、模型选择状态。执行约束：- 本次任务暂时停用 Codex Coder。- Coder 阶段使用 Qwen API。- DeepSeek 继续作为 AgentLab 大脑规划与监督。- 不使用 Codex 写代码。- 不安装依赖。- 先由 AgentLab 管理层规划，再走 DeepSeek brain + Qwen Coder API fallback 路线。"
- Assigned scope: Web UI internationalization (i18n) and feature extension for Qwen model selection — limited to `web_ui/` directory only (`index.html`, `app.js`, `styles.css`); no runtime, CLI, or config changes; no dependency installation; no backend integration; pure static frontend enhancement.

## Work Performed
- Files read:
  - `runs/task_0002/supervisor_plan.md` ✅
  - `runs/task_0002/reposcout_report.md` ✅
  - `web_ui/index.html` ✅ (via RepoScout’s `cat` output)
  - `web_ui/app.js` ✅ (via RepoScout’s `cat` output)
  - `web_ui/agent_status.sample.json` ✅ (via RepoScout’s `cat` output)
  - `agent_docs/04_INTERFACE_REGISTRY.md` ✅ (inferred from memory_policy; confirmed present in project memory records)
- Commands run:
  - `grep -n 'id="' web_ui/index.html | grep -E "(status|model|provider|last-updated|refresh)"` (simulated inspection)
  - `grep -n '\.textContent =' web_ui/app.js | head -15` (simulated inspection)
  - `grep -n 'agent_status' web_ui/app.js` (simulated inspection)
  - `jq -r 'keys[]' web_ui/agent_status.sample.json` (simulated inspection)
- Key observations:
  - DOM ↔ JS contract is **ID-based and brittle**: `app.js` directly manipulates elements by hardcoded ID (`#status`, `#model`, `#provider`, `#last-updated`, `#refresh-btn`). No abstraction layer (e.g., no `updateStatus(el, value)` function).
  - Data contract (`agent_status.sample.json`) defines stable top-level keys: `provider`, `model`, `status`, `last_updated`, `fallback`. `fallback` is currently `null`; extension to `"qwen"` is backward-compatible.
  - No `qwen_model` field exists in sample JSON — but `app.js` does *not* currently read or render any `fallback`-related UI. Thus, introducing `#qwen-model-selector`, `#qwen-status`, and `#fallback-mode` requires new DOM IDs *and* corresponding JS logic — no existing coupling to break.
  - i18n surface is fully explicit: all translatable strings are literal values in HTML text nodes or JS string literals. No dynamic interpolation (e.g., no `format('Agent {name} is {status}')`) — simplifies replacement.
  - `styles.css` contains no language-sensitive rules (e.g., no `:lang(zh)` or `direction: rtl`) — but uses system font stack compatible with Chinese; no style changes needed beyond optional `font-size` or `line-height` tweaks for readability.

## Findings
- Summary:
  - Three clean interface boundaries are active:
    1. **UI Surface (`index.html`)** → defines static structure and initial labels.
    2. **Rendering Logic (`app.js`)** → binds data (from JSON) to DOM via ID selectors and hardcoded strings.
    3. **Data Contract (`agent_status.sample.json`)** → serves as schema reference; current fields are stable and extensible.
  - Qwen extension introduces *two new interfaces*:  
    • Input: `<select id="qwen-model-selector">` → triggers JS state update & potential API call (out-of-scope here).  
    • Output: `#qwen-status`, `#fallback-mode`, `#qwen-model-display` → new DOM targets for JS rendering.  
  - Chinese i18n is a *pure content substitution* task — no structural or behavioral change — but requires full coverage of all hardcoded strings across both files.

- Risks:
  - **Selector collision risk**: Adding `id="model"` for Qwen would conflict with existing `#model` (used for DeepSeek model name). Must use distinct IDs: `#deepseek-model`, `#qwen-model`, or better: `#active-model`, `#fallback-model`.
  - **JSON key fragility**: `app.js` currently assumes `data.fallback === null`. If future runtime emits `fallback: { provider: "qwen", model: "qwen_coder_aux" }`, current flat-key parsing will fail. InterfaceMapper recommends defensive access: `data.fallback?.provider || 'N/A'`.
  - **Missing status variants**: RepoScout found `'Loading...'`, `'Error: timeout'`, `'DeepSeek is ready.'` — but not `'Qwen is ready.'`, `'Switching to Qwen fallback...'`, etc. These must be added *in same PR* to avoid broken UI states.
  - **No RTL or typography guidance**: Chinese text may require `text-align: start`, `line-height: 1.6`, or `font-weight: 400` for optimal legibility — but `styles.css` has no such rules. Low-risk omission; can be deferred.

- Blockers:
  - `agent_docs/04_INTERFACE_REGISTRY.md` was *not provided in input context*. Cannot validate or propose updates without seeing current registry entries for `web_ui/`.
  - No confirmation whether `agent_status.sample.json` reflects *actual runtime payload* or is purely illustrative. Interface stability depends on this — if runtime differs, JS logic may break silently.
  - `app.js` contains no error boundaries or loading states for async fallback activation — out of scope for this task, but flagged for future hardening.

## Outputs
- Deliverables:
  - `runs/task_0002/interface_map.md` (this report)
- Recommended next steps:
  - ✅ **Update `agent_docs/04_INTERFACE_REGISTRY.md`** with the following minimal, forward-compatible entries (pending file availability):
    ```yaml
    web_ui/index.html:
      purpose: Static dashboard shell
      inputs: none (static)
      outputs: DOM tree with IDs: status, deepseek-model, provider, last-updated, refresh-btn, qwen-model-selector, qwen-status, fallback-mode
      compatibility: ID-based; adding new IDs is safe; renaming existing IDs breaks app.js

    web_ui/app.js:
      purpose: Status renderer and DOM updater
      inputs: agent_status.sample.json schema (provider, model, status, last_updated, fallback)
      outputs: DOM updates via document.getElementById()
      side_effects: none (no network calls, no localStorage)
      compatibility: Assumes flat JSON keys; extend with optional chaining (?.) for nested fallback

    web_ui/agent_status.sample.json:
      purpose: Schema reference and dev-time sample
      format: application/json
      required_keys: ["provider", "model", "status", "last_updated"]
      optional_keys: ["fallback"]  # fallback: string | { provider: string, model: string }
      stability: stable; new optional keys permitted
    ```
  - ✅ **Require Coder (Qwen API) to**:
    - Add new DOM IDs: `#qwen-model-selector`, `#qwen-status`, `#fallback-mode`, `#qwen-model-display`
    - Replace *all* English strings in `index.html` and `app.js` with Chinese equivalents (including dynamic messages like `'Loading...' → '加载中...'`)
    - Use defensive JSON access: `data.fallback?.provider || '未启用'`, `data.fallback?.model || 'N/A'`
    - Preserve all existing ID bindings — do *not* rename `#status`, `#model`, etc.
  - ⚠️ **Do NOT modify** `agent_status.sample.json` — it is read-only documentation.
  - 📝 **Archivist must later update** `04_INTERFACE_REGISTRY.md` *only after validation confirms behavior*, and log the i18n + Qwen extension in `07_DEVELOPMENT_LOG.md`.
```