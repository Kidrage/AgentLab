#!/usr/bin/env python3
"""Entrypoint for the versioned local-69/cloud-250 workspace synchronizer."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from cloud_workspace_sync import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
