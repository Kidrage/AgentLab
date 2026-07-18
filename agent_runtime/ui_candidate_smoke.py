"""Local smoke checks for run-local Web UI candidate artifacts."""

from __future__ import annotations

import json
import contextlib
import http.server
import shutil
import socketserver
import subprocess
import tempfile
import threading
import struct
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_WEB_UI_RUN = "task_live_code_ui_app_json_binding_20260707"
DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _default_web_ui_dir(root: Path) -> Path:
    return root / "projects" / "AgentLab" / "runs" / DEFAULT_WEB_UI_RUN / "artifacts" / "web_ui"


def _report_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _node_harness(app_js: str, status_json: str) -> str:
    return f"""
const vm = require('vm');
const appSource = {json.dumps(app_js)};
const statusData = {status_json};
const sections = {{}};
const requiredIds = [
  'workflow-actions',
  'action-ledger',
  'production-packs',
  'lifecycle',
  'selected-detail',
  'evidence-ledger',
  'provider-health',
  'project-memory'
];
for (const id of requiredIds) {{
  sections[id] = {{ innerHTML: '' }};
}}
const document = {{
  getElementById(id) {{
    if (!sections[id]) {{
      sections[id] = {{ innerHTML: '' }};
    }}
    return sections[id];
  }},
  addEventListener(event, callback) {{
    if (event === 'DOMContentLoaded') {{
      globalThis.__domReady = callback;
    }}
  }}
}};
let fetchedPath = null;
async function fetch(path) {{
  fetchedPath = path;
  return {{
    async json() {{
      return statusData;
    }}
  }};
}}
const console = {{ warn() {{}}, log() {{}}, error() {{}} }};
vm.runInNewContext(appSource, {{ document, fetch, console, JSON, Object, globalThis }});
Promise.resolve(globalThis.__domReady()).then(() => {{
  const rendered = Object.fromEntries(Object.entries(sections).map(([key, value]) => [key, value.innerHTML]));
  const missing = requiredIds.filter((id) => !rendered[id] || rendered[id].length < 10);
  const hasExpectedContent =
    rendered['production-packs'].includes('code_factory') &&
    rendered['lifecycle'].includes('INIT_TASK') &&
    rendered['workflow-actions'].includes('configured') &&
    rendered['action-ledger'].includes('idle') &&
    rendered['selected-detail'].includes('INIT_TASK') &&
    rendered['evidence-ledger'].includes('implementation_report') &&
    rendered['provider-health'].includes('deepseek') &&
    rendered['project-memory'].includes('07_DEVELOPMENT_LOG.md');
  process.stdout.write(JSON.stringify({{
    status: missing.length === 0 && hasExpectedContent ? 'pass' : 'fail',
    fetchedPath,
    missing,
    hasExpectedContent,
    renderedLengths: Object.fromEntries(Object.entries(rendered).map(([key, value]) => [key, value.length])),
  }}));
}}).catch((error) => {{
  process.stdout.write(JSON.stringify({{ status: 'fail', error: String(error) }}));
  process.exitCode = 1;
}});
"""


def _interaction_harness(app_js: str, status_json: str) -> str:
    return f"""
const vm = require('vm');
const appSource = {json.dumps(app_js)};
const statusData = {status_json};
const sections = {{}};
const requiredIds = [
  'workflow-actions',
  'action-ledger',
  'production-packs',
  'lifecycle',
  'selected-detail',
  'evidence-ledger',
  'provider-health',
  'project-memory'
];
for (const id of requiredIds) {{
  sections[id] = {{ innerHTML: '' }};
}}
const document = {{
  getElementById(id) {{
    if (!sections[id]) {{
      sections[id] = {{ innerHTML: '' }};
    }}
    return sections[id];
  }},
  addEventListener(event, callback) {{
    if (event === 'DOMContentLoaded') {{
      globalThis.__domReady = callback;
    }}
  }}
}};
let fetchedPath = null;
async function fetch(path) {{
  fetchedPath = path;
  return {{
    async json() {{
      return statusData;
    }}
  }};
}}
const console = {{ warn() {{}}, log() {{}}, error() {{}} }};
vm.runInNewContext(appSource, {{ document, fetch, console, JSON, Object, Array, globalThis }});
Promise.resolve(globalThis.__domReady()).then(() => {{
  const initialState = globalThis.AgentLabDashboard.getDashboardInteractionState();
  const filteredState = globalThis.AgentLabDashboard.setPackFilter('blocked');
  const selectedState = globalThis.AgentLabDashboard.selectLifecycleNode('VALIDATION');
  const rendered = Object.fromEntries(Object.entries(sections).map(([key, value]) => [key, value.innerHTML]));
  const checks = {{
    fetchedStatusJson: fetchedPath === './status.sample.json',
    initialShowsAllPacks: initialState.visiblePackIds.includes('code_factory') && initialState.visiblePackIds.includes('media_series_production'),
    blockedFilterWorks: filteredState.packFilter === 'blocked' && filteredState.visiblePackIds.length === 1 && filteredState.visiblePackIds[0] === 'media_series_production',
    lifecycleSelectionWorks: selectedState.selectedNode === 'VALIDATION' && rendered['selected-detail'].includes('VALIDATION'),
    openEvidenceGatesTracked: selectedState.openEvidenceGates.includes('ui_interaction_workflow') && selectedState.openEvidenceGates.includes('grok_media_live'),
    workflowActionsRendered: rendered['workflow-actions'].includes('blocked 1'),
  }};
  process.stdout.write(JSON.stringify({{
    status: Object.values(checks).every(Boolean) ? 'pass' : 'fail',
    checks,
    initialState,
    filteredState,
    selectedState,
    renderedLengths: Object.fromEntries(Object.entries(rendered).map(([key, value]) => [key, value.length])),
  }}));
}}).catch((error) => {{
  process.stdout.write(JSON.stringify({{ status: 'fail', error: String(error) }}));
  process.exitCode = 1;
}});
"""


def run_web_ui_candidate_smoke(root: Path, web_ui_dir: Path | None = None) -> dict[str, Any]:
    """Execute the candidate dashboard JS against a minimal DOM/fetch harness."""
    root = root.resolve()
    web_ui_dir = (web_ui_dir or _default_web_ui_dir(root)).resolve()
    required = {
        "index_html": web_ui_dir / "index.html",
        "styles_css": web_ui_dir / "styles.css",
        "app_js": web_ui_dir / "app.js",
        "status_json": web_ui_dir / "status.sample.json",
    }
    missing = [_report_path(root, path) for path in required.values() if not path.exists()]
    if missing:
        return {
            "status": "fail",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "missing": missing,
            "checks": [],
        }

    checks: list[dict[str, Any]] = []
    try:
        status_data = json.loads(required["status_json"].read_text(encoding="utf-8"))
        checks.append({"id": "status_json_parse", "status": "pass"})
    except Exception as exc:
        return {
            "status": "fail",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "missing": [],
            "checks": [{"id": "status_json_parse", "status": "fail", "error": str(exc)}],
        }

    index_text = required["index_html"].read_text(encoding="utf-8")
    section_ids = [
        "workflow-actions",
        "action-ledger",
        "production-packs",
        "lifecycle",
        "selected-detail",
        "evidence-ledger",
        "provider-health",
        "project-memory",
    ]
    missing_sections = [section_id for section_id in section_ids if f'id="{section_id}"' not in index_text]
    checks.append({
        "id": "html_section_contract",
        "status": "pass" if not missing_sections else "fail",
        "missing_sections": missing_sections,
    })

    node = shutil.which("node")
    if not node:
        checks.append({"id": "dom_execution", "status": "blocked", "reason": "node not found"})
        return {
            "status": "blocked",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "missing": [],
            "checks": checks,
        }

    app_js = required["app_js"].read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="agentlab-ui-smoke-") as tmp:
        harness = Path(tmp) / "ui_smoke.js"
        harness.write_text(_node_harness(app_js, json.dumps(status_data)), encoding="utf-8")
        proc = subprocess.run(
            [node, str(harness)],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    try:
        dom_result = json.loads(proc.stdout or "{}")
    except Exception:
        dom_result = {
            "status": "fail",
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }
    checks.append({"id": "dom_execution", **dom_result})
    status = "pass" if all(check.get("status") == "pass" for check in checks) else "fail"
    if any(check.get("status") == "blocked" for check in checks):
        status = "blocked"
    return {
        "status": status,
        "web_ui_dir": _report_path(root, web_ui_dir),
        "missing": [],
        "checks": checks,
    }


def run_web_ui_interaction_smoke(root: Path, web_ui_dir: Path | None = None) -> dict[str, Any]:
    """Exercise dashboard operator interactions in a minimal DOM harness."""
    root = root.resolve()
    web_ui_dir = (web_ui_dir or _default_web_ui_dir(root)).resolve()
    required = {
        "app_js": web_ui_dir / "app.js",
        "status_json": web_ui_dir / "status.sample.json",
    }
    missing = [_report_path(root, path) for path in required.values() if not path.exists()]
    if missing:
        return {
            "status": "fail",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "missing": missing,
            "checks": [],
        }
    node = shutil.which("node")
    if not node:
        return {
            "status": "blocked",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "missing": [],
            "checks": [{"id": "interaction_execution", "status": "blocked", "reason": "node not found"}],
        }
    try:
        status_data = json.loads(required["status_json"].read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "fail",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "missing": [],
            "checks": [{"id": "status_json_parse", "status": "fail", "error": str(exc)}],
        }
    app_js = required["app_js"].read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="agentlab-ui-interaction-") as tmp:
        harness = Path(tmp) / "ui_interaction_smoke.js"
        harness.write_text(_interaction_harness(app_js, json.dumps(status_data)), encoding="utf-8")
        proc = subprocess.run(
            [node, str(harness)],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    try:
        interaction_result = json.loads(proc.stdout or "{}")
    except Exception:
        interaction_result = {
            "status": "fail",
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }
    return {
        "status": interaction_result.get("status", "fail"),
        "web_ui_dir": _report_path(root, web_ui_dir),
        "missing": [],
        "checks": [{"id": "interaction_execution", **interaction_result}],
    }


def _ui_run_dir(root: Path) -> Path:
    return root / "projects" / "AgentLab" / "runs" / DEFAULT_WEB_UI_RUN


def _append_ui_action_ledger(ledger_path: Path, action: dict[str, Any]) -> dict[str, Any]:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger_path.exists():
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        except Exception:
            ledger = {}
    else:
        ledger = {}
    actions = ledger.get("actions", [])
    if not isinstance(actions, list):
        actions = []
    entry = {
        "id": f"ui_action_{len(actions) + 1:04d}",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "scope": "candidate_run_local",
        "production_modified": False,
        "action": action,
    }
    actions.append(entry)
    ledger = {
        "schema_version": 1,
        "artifact": "ui_action_ledger.json",
        "status": "candidate",
        "candidate_only": True,
        "production_modified": False,
        "actions": actions,
    }
    ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return entry


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - local smoke URL only
        return json.loads(response.read().decode("utf-8"))


def run_web_ui_api_smoke(root: Path, web_ui_dir: Path | None = None) -> dict[str, Any]:
    """Exercise a run-local backing API write into the candidate action ledger."""
    root = root.resolve()
    web_ui_dir = (web_ui_dir or _default_web_ui_dir(root)).resolve()
    run_dir = _ui_run_dir(root)
    ledger_path = run_dir / "ui_action_ledger.json"
    if not (web_ui_dir / "index.html").exists():
        return {
            "status": "fail",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "reason": "index.html missing",
        }

    class ApiHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            return

        def do_POST(self) -> None:  # noqa: N802 - stdlib hook
            if self.path != "/api/actions":
                self.send_error(404)
                return
            length = int(self.headers.get("content-length", "0"))
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self.send_error(400)
                return
            entry = _append_ui_action_ledger(ledger_path, payload)
            body = json.dumps(
                {
                    "status": "recorded",
                    "ledger": _report_path(root, ledger_path),
                    "entry_id": entry["id"],
                    "production_modified": False,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    action = {
        "actionType": "record_validation_review",
        "selectedNode": "VALIDATION",
        "packFilter": "blocked",
        "visiblePackIds": ["media_series_production"],
        "openEvidenceGates": ["ui_interaction_workflow", "grok_media_live"],
    }
    with contextlib.ExitStack() as stack:
        previous_cwd = Path.cwd()
        import os

        os.chdir(web_ui_dir)
        stack.callback(os.chdir, previous_cwd)
        server = ReusableTCPServer(("127.0.0.1", 0), ApiHandler)
        stack.callback(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stack.callback(server.shutdown)
        port = server.server_address[1]
        response = _post_json(f"http://127.0.0.1:{port}/api/actions", action)

    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    actions = ledger.get("actions", []) if isinstance(ledger.get("actions"), list) else []
    latest = actions[-1] if actions else {}
    checks = [
        {
            "id": "api_response_recorded",
            "status": "pass" if response.get("status") == "recorded" and response.get("production_modified") is False else "fail",
            "response": response,
        },
        {
            "id": "ledger_written_candidate_only",
            "status": "pass"
            if ledger.get("candidate_only") is True
            and ledger.get("production_modified") is False
            and latest.get("action", {}).get("actionType") == "record_validation_review"
            else "fail",
            "ledger_path": _report_path(root, ledger_path),
            "actions_count": len(actions),
            "latest_entry": latest,
        },
    ]
    return {
        "status": "pass" if all(check.get("status") == "pass" for check in checks) else "fail",
        "web_ui_dir": _report_path(root, web_ui_dir),
        "ledger_path": _report_path(root, ledger_path),
        "checks": checks,
    }


def _find_chrome() -> str | None:
    if Path(DEFAULT_CHROME).exists():
        return DEFAULT_CHROME
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chrome")


def _browser_expected_content(dom: str) -> dict[str, bool]:
    return {
        "production_pack": "code_factory" in dom,
        "lifecycle": "INIT_TASK" in dom and "SUPERVISOR_PLAN" in dom,
        "evidence": "implementation_report" in dom,
        "provider": "deepseek" in dom and "codex" in dom,
        "memory": "07_DEVELOPMENT_LOG.md" in dom and "08_WORKER_DIALOGUE_LOG.md" in dom,
    }


def run_web_ui_browser_smoke(root: Path, web_ui_dir: Path | None = None) -> dict[str, Any]:
    """Render the candidate in headless Chrome and inspect the post-JS DOM."""
    root = root.resolve()
    web_ui_dir = (web_ui_dir or _default_web_ui_dir(root)).resolve()
    chrome = _find_chrome()
    if not chrome:
        return {
            "status": "blocked",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "reason": "Chrome/Chromium executable not found",
        }
    if not (web_ui_dir / "index.html").exists():
        return {
            "status": "fail",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "reason": "index.html missing",
        }

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            return

    with contextlib.ExitStack() as stack:
        previous_cwd = Path.cwd()
        import os

        os.chdir(web_ui_dir)
        stack.callback(os.chdir, previous_cwd)
        server = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
        stack.callback(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stack.callback(server.shutdown)
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/index.html"
        proc = subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--virtual-time-budget=3000",
                "--dump-dom",
                url,
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    dom = proc.stdout or ""
    sections = ["production-packs", "lifecycle", "evidence-ledger", "provider-health", "project-memory"]
    expected = _browser_expected_content(dom)
    missing_sections = [section for section in sections if f'id="{section}"' not in dom]
    status = "pass" if proc.returncode == 0 and not missing_sections and all(expected.values()) else "fail"
    return {
        "status": status,
        "web_ui_dir": _report_path(root, web_ui_dir),
        "browser": chrome,
        "returncode": proc.returncode,
        "missing_sections": missing_sections,
        "expected_content": expected,
        "dom_length": len(dom),
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


def _png_scanline_channels(color_type: int) -> int | None:
    return {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)


def _unfilter_png_row(filter_type: int, row: bytearray, previous: bytes, bpp: int) -> bytes:
    if filter_type == 0:
        return bytes(row)
    if filter_type == 1:
        for i in range(len(row)):
            left = row[i - bpp] if i >= bpp else 0
            row[i] = (row[i] + left) & 0xFF
        return bytes(row)
    if filter_type == 2:
        for i in range(len(row)):
            row[i] = (row[i] + previous[i]) & 0xFF
        return bytes(row)
    if filter_type == 3:
        for i in range(len(row)):
            left = row[i - bpp] if i >= bpp else 0
            up = previous[i]
            row[i] = (row[i] + ((left + up) // 2)) & 0xFF
        return bytes(row)
    if filter_type == 4:
        for i in range(len(row)):
            left = row[i - bpp] if i >= bpp else 0
            up = previous[i]
            up_left = previous[i - bpp] if i >= bpp else 0
            predictor = left + up - up_left
            pa = abs(predictor - left)
            pb = abs(predictor - up)
            pc = abs(predictor - up_left)
            prior = left if pa <= pb and pa <= pc else up if pb <= pc else up_left
            row[i] = (row[i] + prior) & 0xFF
        return bytes(row)
    raise ValueError(f"unsupported PNG filter type: {filter_type}")


def analyze_png_pixels(path: Path) -> dict[str, Any]:
    """Return small visual-health metrics for an 8-bit non-interlaced PNG."""
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"status": "fail", "reason": "not a PNG"}
    offset = 8
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        chunk = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _compression, _filter, interlace = struct.unpack(">IIBBBBB", chunk)
        elif chunk_type == b"IDAT":
            idat.extend(chunk)
        elif chunk_type == b"IEND":
            break
    if not width or not height or bit_depth != 8 or interlace != 0:
        return {
            "status": "fail",
            "reason": "unsupported PNG format",
            "width": width,
            "height": height,
            "bit_depth": bit_depth,
            "color_type": color_type,
            "interlace": interlace,
        }
    channels = _png_scanline_channels(int(color_type))
    if channels is None:
        return {"status": "fail", "reason": f"unsupported color type: {color_type}"}
    raw = zlib.decompress(bytes(idat))
    stride = int(width) * channels
    previous = bytes(stride)
    pos = 0
    sampled: list[tuple[int, int, int]] = []
    non_white = 0
    non_black = 0
    total = int(width) * int(height)
    step_x = max(1, int(width) // 64)
    step_y = max(1, int(height) // 64)
    for y in range(int(height)):
        filter_type = raw[pos]
        pos += 1
        row = _unfilter_png_row(filter_type, bytearray(raw[pos:pos + stride]), previous, channels)
        pos += stride
        previous = row
        if y % step_y != 0:
            continue
        for x in range(0, int(width), step_x):
            idx = x * channels
            if channels == 1:
                rgb = (row[idx], row[idx], row[idx])
            else:
                rgb = (row[idx], row[idx + 1], row[idx + 2])
            sampled.append(rgb)
            if rgb != (255, 255, 255):
                non_white += 1
            if rgb != (0, 0, 0):
                non_black += 1
    unique_colors = len(set(sampled))
    sampled_count = len(sampled)
    return {
        "status": "pass" if unique_colors >= 8 and non_white > 0 and non_black > 0 else "fail",
        "width": width,
        "height": height,
        "sampled_pixels": sampled_count,
        "unique_sampled_colors": unique_colors,
        "non_white_sampled_pixels": non_white,
        "non_black_sampled_pixels": non_black,
        "file_size": path.stat().st_size,
    }


def run_web_ui_visual_smoke(
    root: Path,
    web_ui_dir: Path | None = None,
    screenshot_path: Path | None = None,
    viewport: tuple[int, int] = (1280, 900),
) -> dict[str, Any]:
    """Capture a headless Chrome screenshot and run a simple pixel-health check."""
    root = root.resolve()
    web_ui_dir = (web_ui_dir or _default_web_ui_dir(root)).resolve()
    chrome = _find_chrome()
    if not chrome:
        return {
            "status": "blocked",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "reason": "Chrome/Chromium executable not found",
        }
    if not (web_ui_dir / "index.html").exists():
        return {
            "status": "fail",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "reason": "index.html missing",
        }
    screenshot_path = screenshot_path or (web_ui_dir.parent.parent / "ui_visual_smoke.png")
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            return

    with contextlib.ExitStack() as stack:
        previous_cwd = Path.cwd()
        import os

        os.chdir(web_ui_dir)
        stack.callback(os.chdir, previous_cwd)
        server = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
        stack.callback(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stack.callback(server.shutdown)
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/index.html"
        width, height = viewport
        proc = subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"--window-size={width},{height}",
                "--virtual-time-budget=3000",
                f"--screenshot={screenshot_path}",
                url,
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    if proc.returncode != 0 or not screenshot_path.exists():
        return {
            "status": "fail",
            "web_ui_dir": _report_path(root, web_ui_dir),
            "browser": chrome,
            "screenshot_path": _report_path(root, screenshot_path),
            "returncode": proc.returncode,
            "reason": "screenshot command failed or did not create an image",
            "stderr_tail": (proc.stderr or "")[-2000:],
        }
    pixel_report = analyze_png_pixels(screenshot_path)
    status = "pass" if pixel_report.get("status") == "pass" else "fail"
    return {
        "status": status,
        "web_ui_dir": _report_path(root, web_ui_dir),
        "browser": chrome,
        "screenshot_path": _report_path(root, screenshot_path),
        "viewport": {"width": viewport[0], "height": viewport[1]},
        "returncode": proc.returncode,
        "pixel_report": pixel_report,
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


def run_web_ui_responsive_smoke(root: Path, web_ui_dir: Path | None = None) -> dict[str, Any]:
    """Run visual smoke checks at desktop and mobile viewport sizes."""
    root = root.resolve()
    run_dir = root / "projects" / "AgentLab" / "runs" / DEFAULT_WEB_UI_RUN
    viewports = {
        "desktop": (1280, 900),
        "mobile": (390, 844),
    }
    results: dict[str, Any] = {}
    for name, viewport in viewports.items():
        results[name] = run_web_ui_visual_smoke(
            root,
            web_ui_dir=web_ui_dir,
            screenshot_path=run_dir / f"ui_responsive_{name}.png",
            viewport=viewport,
        )
    status = "pass" if all(item.get("status") == "pass" for item in results.values()) else "fail"
    if any(item.get("status") == "blocked" for item in results.values()):
        status = "blocked"
    return {
        "status": status,
        "web_ui_dir": _report_path(root, (web_ui_dir or _default_web_ui_dir(root)).resolve()),
        "viewports": results,
        "checks": [
            {
                "id": name,
                "status": item.get("status"),
                "screenshot_path": item.get("screenshot_path"),
                "pixel_report": item.get("pixel_report"),
            }
            for name, item in results.items()
        ],
    }


def write_web_ui_visual_smoke(
    root: Path,
    out: Path,
    web_ui_dir: Path | None = None,
    screenshot_path: Path | None = None,
) -> dict[str, Any]:
    report = run_web_ui_visual_smoke(root, web_ui_dir=web_ui_dir, screenshot_path=screenshot_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def write_web_ui_responsive_smoke(
    root: Path,
    out: Path,
    web_ui_dir: Path | None = None,
) -> dict[str, Any]:
    report = run_web_ui_responsive_smoke(root, web_ui_dir=web_ui_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def write_web_ui_browser_smoke(root: Path, out: Path, web_ui_dir: Path | None = None) -> dict[str, Any]:
    report = run_web_ui_browser_smoke(root, web_ui_dir=web_ui_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def write_web_ui_candidate_smoke(root: Path, out: Path, web_ui_dir: Path | None = None) -> dict[str, Any]:
    report = run_web_ui_candidate_smoke(root, web_ui_dir=web_ui_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def write_web_ui_interaction_smoke(root: Path, out: Path, web_ui_dir: Path | None = None) -> dict[str, Any]:
    report = run_web_ui_interaction_smoke(root, web_ui_dir=web_ui_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def write_web_ui_api_smoke(root: Path, out: Path, web_ui_dir: Path | None = None) -> dict[str, Any]:
    report = run_web_ui_api_smoke(root, web_ui_dir=web_ui_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
