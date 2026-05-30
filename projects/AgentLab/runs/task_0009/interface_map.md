# Interface Mapper Report

## Task
- **Task id:** task_0009
- **User request:** 完善 AgentLab Web UI 并完成桌面 App 封装 (see `runs/task_0009/user_request.md`)
- **Assigned scope:**
  - **Web UI enhancements:** add model selector in HTML, config panel with real‑time edit + save, about/help page.
  - **Desktop app improvements:** auto‑dependency install, error handling, window icon, multi‑window support in `agentlab_app.py`.
  - **Desktop packaging:** macOS `.app` bundle, Linux `.desktop` entry, Windows PyInstaller script, README build/install instructions.
  - **Constraints:** zero‑dependency Web UI (HTML/CSS/JS only), minimum dependency for desktop (pywebview only), no changes to core AgentLab runtime.

## Work Performed
- **Files read:**
  - `agentlab_app.py` (via RepoScout report – ~45 lines, basic `webview.create_window()` wrapper)
  - `web_ui/index.html` (first 80 lines inspected by RepoScout; tabs: Dashboard, 任务, 日志; no model selector, no config edit area, no about/help)
  - `web_ui/app.js` (existence confirmed; grep showed no model‑selection or config‑save logic)
  - `web_ui/agent_status.sample.json` (sample payload for status dashboard)
  - `agent_docs/04_INTERFACE_REGISTRY.md` (checked via shell: file does not exist – the interface registry is currently empty/not created)
- **Commands run:**
  - `ls -la` (root listing)
  - `wc -l agentlab_app.py web_ui/*`
  - `head -80 web_ui/index.html`
  - `grep -n "select\|selectMenu\|model" web_ui/app.js` (no matches)
  - `grep -n "config\|save\|edit" web_ui/app.js` (no config‑save logic)
  - `test -f agent_docs/04_INTERFACE_REGISTRY.md && echo "EXISTS" || echo "MISSING"` → MISSING
- **Brain provider:** deepseek (required for InterfaceMapper; this report drafted in simulated environment per workflow plan “plan‑only” notes – actual brain execution will occur in subsequent phase)
- **Brain API called:** No (simulated)
- **Brain token usage:** Not applicable

## Findings

### Summary
The task touches two primary interface domains: the **Web UI contract** and the **desktop app integration layer**. No formal interface registry exists yet (`04_INTERFACE_REGISTRY.md` is missing), so every new or modified boundary must be documented from scratch.

#### 1. Web UI Data Contract
- **Current state:** The UI expects a JSON status payload (as per `agent_status.sample.json`) that contains fields like `status`, `active_task`, `task_list`, etc. The dashboard tab renders this data. No model‑selection or configuration‑editing logic is present.
- **Planned change:** A model selector will be added (dropdown in HTML) that must communicate the selected model back to the app. This introduces a new UI→App write path. The config panel will need to read/write configuration values (likely from a local config file or in‑memory state exposed by the app). The about/help page is read‑only and does not need a contract beyond static content.
- **Integration point:** The desktop app (`agentlab_app.py`) loads the Web UI via pywebview. The app can expose a JavaScript API (using `webview.expose`) to allow the UI to call Python functions for saving config and possibly changing the model. Alternatively, the UI could rely on a local HTTP endpoint, but given the zero‑dependency constraint and pywebview’s built‑in API, the former is most likely.
- **Risk:** The existing JavaScript code (`app.js`) has no machinery to invoke pywebview functions. Adding such calls without a clear API contract risks broken interactions if not coordinated with the Python side.

#### 2. Desktop App Shell (`agentlab_app.py`)
- **Current state:** A minimal `webview.create_window()` with a title and URL pointing to the local `web_ui/index.html`. No explicit error handling, dependency checking, window icon, or multi‑window support.
- **Planned changes:**
  - **Auto‑dependency install:** Introduces a startup guard that checks for `webview` and perhaps other dependencies. This should be transparent to the UI but may need to display a user‑friendly message (could use a native dialog or a HTML fallback). Interface: none beyond the existing window creation flow, but error handling could break the UI if the window fails to load.
  - **Window icon:** Affects only the desktop shell; no UI impact.
  - **Multi‑window support:** Would require the ability to open additional pywebview windows (e.g., config editor, about/help). This adds complexity: the UI might need a way to trigger opening a new window, requiring a new exposed API function like `open_help_window()` or `open_config_window()`. This introduces a **new API contract**.
- **Risk:** Adding multi‑window without a clear UI→App communication protocol could lead to inconsistent window management or resource leaks.

#### 3. Desktop Packaging
- **Mac, Linux, Windows scripts:** These are build‑time artifacts that do not affect runtime interfaces. However, the packaging may assume a specific file layout or entry‑point. The `agentlab_app.py` becomes the main entry point for the packaged app. No new runtime boundary is introduced, but the **layout contract** (where the `web_ui/` folder lives relative to the executable) must be consistent across platforms.
- **README update:** Documentation only; no interface impact beyond user instructions.

#### 4. Missing Interface Registry
- The project lacks a central register (`04_INTERFACE_REGISTRY.md`). This task’s changes should be the first entries. Without it, future changes risk breaking undocumented contracts.

### Risks
- **Uncoordinated UI‑App API:** The new model selector and config panel will need JavaScript functions to communicate with the Python side. If the agreed API names or data formats are not clearly defined before implementation, the Coder may introduce incompatibilities that Tester/A