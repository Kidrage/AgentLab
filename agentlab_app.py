#!/usr/bin/env python3
"""AgentLab Desktop App — native window wrapping the Web UI.

Start the backend server and open a system webview window.
Works as a standalone desktop application.

Requirements (auto-installed on first run):
    pip install webview  (macOS: also requires pyobjc; Linux: also requires python3-gi)
"""

from __future__ import annotations

import os
import sys
import subprocess
import time
import signal
import platform
from pathlib import Path

AGENTLAB_ROOT = Path(os.getenv("AGENTLAB_ROOT", Path(__file__).resolve().parent))

# ──────────── dependency auto-install ────────────
REQUIRED_PACKAGES = {
    "webview": "pywebview>=4.0",
}
SYSTEM = platform.system()


def _pip_install(package_spec: str) -> bool:
    """Install a package via pip. Returns True on success."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", "--no-deps", package_spec],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except Exception:
        return False


def ensure_dependencies() -> list[str]:
    """Check and install required packages. Returns list of installed packages."""
    installed = []
    for module_name, pip_spec in REQUIRED_PACKAGES.items():
        try:
            __import__(module_name)
        except ImportError:
            print(f"  安装依赖: {pip_spec} ...")
            if _pip_install(pip_spec):
                installed.append(pip_spec)
                print(f"    OK {pip_spec} 安装成功")
            else:
                print(f"    FAIL {pip_spec} 安装失败，请手动执行: pip install {pip_spec}")
        else:
            pass  # already installed
    return installed


# ──────────── window icon ────────────
def _get_icon_path() -> str | None:
    """Return path to an icon file, or None if not found."""
    candidates = [
        AGENTLAB_ROOT / "web_ui" / "icon.png",
        AGENTLAB_ROOT / "assets" / "icon.png",
        AGENTLAB_ROOT / "icon.png",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    # Try generating a simple icon with Pillow
    try:
        from PIL import Image
        icon_path = AGENTLAB_ROOT / "web_ui" / "icon.png"
        if not icon_path.exists():
            img = Image.new("RGBA", (256, 256), (37, 99, 235, 255))
            icon_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(icon_path))
        return str(icon_path)
    except ImportError:
        pass
    return None


# ──────────── backend server ────────────
_backend_process = None  # type: subprocess.Popen | None


def start_backend(port: int = 8765) -> subprocess.Popen | None:
    """Launch the web_ui server. Returns the Popen handle or None."""
    global _backend_process
    os.environ["AGENTLAB_PORT"] = str(port)
    server_path = AGENTLAB_ROOT / "web_ui" / "server.py"

    if not server_path.exists():
        print(f"  FAIL 后端服务文件不存在: {server_path}")
        return None

    try:
        preexec = os.setsid if SYSTEM != "Windows" else None
        _backend_process = subprocess.Popen(
            [sys.executable, str(server_path)],
            cwd=str(AGENTLAB_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=preexec,
        )
        time.sleep(0.8)
        if _backend_process.poll() is not None:
            stderr_out = ""
            if _backend_process.stderr:
                stderr_out = _backend_process.stderr.read().decode(errors="ignore")
            print(f"  FAIL 后端启动失败: {stderr_out[:300]}")
            return None
        return _backend_process
    except Exception as exc:
        print(f"  FAIL 后端启动异常: {exc}")
        return None


def stop_backend():
    """Gracefully stop the backend server."""
    global _backend_process
    if _backend_process is None:
        return
    try:
        if SYSTEM == "Windows":
            _backend_process.terminate()
        else:
            os.killpg(os.getpgid(_backend_process.pid), signal.SIGTERM)
        _backend_process.wait(timeout=5)
    except Exception:
        try:
            _backend_process.kill()
        except Exception:
            pass
    _backend_process = None


def _signal_handler(signum, frame):
    """Handle interrupt signals."""
    stop_backend()
    webview_cleanup()
    sys.exit(0)


# ──────────── webview cleanup ────────────
_webview_windows: list = []


def webview_cleanup():
    """Close all webview windows."""
    global _webview_windows
    for win in _webview_windows:
        try:
            win.destroy()
        except Exception:
            pass
    _webview_windows.clear()


# ──────────── multi-window support ────────────
def open_secondary_window(url: str, title: str = "AgentLab"):
    """Open a secondary webview window (e.g., for help/docs)."""
    try:
        import webview
        win = webview.create_window(
            title=title,
            url=url,
            width=900,
            height=700,
            min_size=(600, 400),
            resizable=True,
        )
        _webview_windows.append(win)
        return win
    except Exception as exc:
        print(f"  FAIL 无法打开辅助窗口: {exc}")
        return None


# ──────────── main ────────────
def main():
    print("AgentLab Desktop App")
    print(f"  系统: {SYSTEM}")
    print(f"  AgentLab 根目录: {AGENTLAB_ROOT}")
    print()

    # Auto-install dependencies
    ensure_dependencies()

    # Register signal handlers
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Start backend
    port = int(os.getenv("AGENTLAB_PORT", "8765"))
    print(f"  启动后端服务 (端口 {port})...")
    proc = start_backend(port)
    if proc is None:
        print("  FAIL 后端服务启动失败，请手动运行:")
        print(f"    python3 web_ui/server.py")
        # Fallback: open in native browser
        url = f"http://localhost:{port}"
        print(f"  尝试打开浏览器: {url}")
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
        print("  按 Ctrl+C 退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  已退出")
            stop_backend()
        return

    url = f"http://localhost:{port}"
    print(f"  -> Web UI: {url}")
    print()

    # Get icon path
    icon_path = _get_icon_path()
    if icon_path:
        print(f"  窗口图标: {icon_path}")

    try:
        import webview

        # Main window
        win = webview.create_window(
            title="AgentLab - AI Agent 任务流管理平台",
            url=url,
            width=1280,
            height=900,
            min_size=(900, 600),
            resizable=True,
            fullscreen=False,
        )
        _webview_windows.append(win)

        print("  AgentLab Desktop 已启动，关闭窗口即可退出")
        webview.start(gui=None, debug=False)
    except Exception as exc:
        print(f"  FAIL webview 启动失败: {exc}")
        print(f"  请确保已安装 pywebview: pip install pywebview")
        # Fallback to browser
        try:
            import webbrowser
            print(f"  在浏览器中打开: {url}")
            webbrowser.open(url)
            print("  按 Ctrl+C 退出")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  已退出")
    finally:
        stop_backend()
        webview_cleanup()
        print("  AgentLab Desktop 已关闭")


if __name__ == "__main__":
    main()