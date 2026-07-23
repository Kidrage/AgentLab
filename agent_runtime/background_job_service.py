"""Long-lived local service for one durable AgentLab background job."""

from __future__ import annotations

import argparse
from pathlib import Path

from agent_runtime.background_job_controller import run_controller_loop


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    result = run_controller_loop(
        args.root.resolve(),
        project=args.project,
        job_id=args.job_id,
        poll_seconds=args.poll_seconds,
    )
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
