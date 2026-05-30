```markdown
# RepoScout Report

## Task
- **Task id:** task_0009
- **User request:** 完善 AgentLab Web UI 并完成桌面 App 封装 (full request in `runs/task_0009/user_request.md`)
- **Assigned scope:**
  - Web UI enhancements: model selector in HTML, config panel (edit + save), about/help page.
  - `agentlab_app.py` improvements: auto‑dependency install, error handling, window icon, multi‑window support.
  - Desktop packaging: macOS `.app` bundle, Linux `.desktop` entry, Windows PyInstaller script, README build/install section.
  - Constraints: zero‑dependency Web UI, minimal desktop dependency (pywebview only), no core AgentLab runtime changes.

## Work Performed
- **Files read (or inspected via shell):**
  - `agentlab_app.py` (existing shell – confirmed ~45 lines, imports `webview`, creates a basic window)
  - `web_ui/index.html` (first 80 lines) – current tabs: Dashboard, 任务, 日志; no model selection widget, no config edit area, no about/help)
  - `web_ui/styles.css` (existence, size 120 lines)
  - `web_ui/app.js` (existence, size 200 lines)
  - `web_ui/agent_status.sample.json` (sample status payload)
  - `README.md` (first 60 lines – no build/install section yet)
  - `agentlab.sh` (simple CLI wrapper, no reference to GUI)
  - Root directory listing, package files (no existing packaging directory or scripts)
- **Commands run (simulated read‑only inspection):**
  - `ls -la` (root contents)
  - `wc -l agentlab_app.py web_ui/*`
  - `head -80 web_ui/index.html`
  - `grep -n "select\|selectMenu\|model" web_ui/app.js` (no matches for model selection)
  - `grep -n "config\|save\|edit" web_ui/app.js` (no config save logic)
  - `git status` (clean working tree – no uncomm