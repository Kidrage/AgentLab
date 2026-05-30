#!/usr/bin/env python3
"""AgentLab Desktop App — native window wrapping the Web UI.

Start the backend server and open a system webview window.
Works as a standalone desktop application.

Requirements (auto-installed on first run):
    pip install webview
"""

import os
import sys
import subprocess
import threading
import time
from pathlib import Path

AGENTLAB_ROOT = Path(os.getenv("AGENTLAB_ROOT", Path(__file__).resolve().parent))


def start_backend(port: int = 8765):
    """Launch the web_ui server in a background thread."""
    os.environ["AGENTLAB_PORT"] = str(port)
    server_path = AGENTLAB_ROOT / "web_ui" / "server.py"

    def run():
        subprocess.run(
            [sys.executable, str(server_path)],
            cwd=str(AGENTLAB_ROOT),
            capture_output=True,
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    # Give the server a moment to start
    time.sleep(1)
    return thread


def main():
    import webview

    port = int(os.getenv("AGENTLAB_PORT", "8765"))
    url = f"http://localhost:{port}"

    print(f"  AgentLab Desktop App")
    print(f"  → 后端服务: localhost:{port}")
    print(f"  → Web UI: {url}")
    print()

    # Start backend
    start_backend(port)

    # Open native window
    webview.create_window(
        title="AgentLab — AI Agent 任务流管理平台",
        url=url,
        width=1280,
        height=900,
        min_size=(900, 600),
        resizable=True,
        fullscreen=False,
    )
    webview.start()


if __name__ == "__main__":
    main()