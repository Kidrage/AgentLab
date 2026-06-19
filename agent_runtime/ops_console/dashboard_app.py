"""Optional S11 ASGI dashboard app factory.

The CLI exposes this through a dry-run launch plan. Importing this module must not
start a server or bind a network port.
"""

from __future__ import annotations

from pathlib import Path

from .status_api import build_ops_console_snapshot

try:
    from fastapi import FastAPI
except Exception:  # pragma: no cover - optional dependency fallback
    FastAPI = None  # type: ignore[assignment]


def create_app(root: Path | None = None):
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed; use ops-console-status for CLI snapshot mode")
    repo_root = root or Path(__file__).resolve().parents[2]
    app = FastAPI(title="AgentLab Ops Console", version="s11-read-only")

    @app.get("/api/status")
    def status() -> dict:
        return build_ops_console_snapshot(repo_root, project="AgentLab")

    return app


app = create_app() if FastAPI is not None else None
