#!/usr/bin/env python3
"""Compile a raw prompt into a deterministic AgentLab MissionContract.

This S1-B CLI is intentionally small and local-only.  It delegates to the
TaskCompiler API, writes exactly one MissionContract YAML file, and prints a
short JSON summary suitable for smoke tests or future orchestration layers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime.brain.mission_contract import write_mission_contract  # noqa: E402
from agent_runtime.brain.task_compiler import TaskCompilationError, compile_task_packet  # noqa: E402


def _read_prompt(args: argparse.Namespace) -> str:
    """Read prompt text from --prompt or --prompt-file with clear precedence."""

    if args.prompt and args.prompt_file:
        raise TaskCompilationError(
            [
                {
                    "field": "prompt",
                    "message": "use either --prompt or --prompt-file, not both",
                    "code": "mutually_exclusive",
                }
            ]
        )
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        return prompt_path.read_text(encoding="utf-8")
    return args.prompt or ""


def _output_path(raw_output: str | None) -> Path:
    """Resolve CLI output semantics to the mission_contract.yml path."""

    if not raw_output:
        return Path.cwd() / "mission_contract.yml"
    path = Path(raw_output)
    if path.suffix in {".yml", ".yaml"}:
        return path
    return path / "mission_contract.yml"


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser without side effects."""

    parser = argparse.ArgumentParser(
        description="Compile a raw prompt into an AgentLab MissionContract YAML file."
    )
    parser.add_argument("--task-id", default=None, help="Optional mission/task id to store in the contract.")
    parser.add_argument("--project", default=None, help="Optional project name used by deterministic fallback ids.")
    parser.add_argument("--prompt", default=None, help="Raw user prompt to compile.")
    parser.add_argument("--prompt-file", default=None, help="UTF-8 text file containing the raw user prompt.")
    parser.add_argument(
        "--output",
        default="mission_contract.yml",
        help="Output YAML path, or a directory where mission_contract.yml will be written.",
    )
    return parser


def summary_for_result(output_path: Path, result) -> dict[str, object]:
    """Build a stable JSON-serializable summary for CLI stdout."""

    contract = result.contract
    return {
        "task_id": contract.mission_id,
        "task_type": str(contract.task_type),
        "required_capabilities_count": len(contract.required_capabilities),
        "required_artifacts_count": len(contract.required_artifacts),
        "acceptance_gates_count": len(contract.acceptance_gates),
        "human_approval_required": contract.human_approval.required,
        "output_path": str(output_path),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint; returns process code instead of raising raw tracebacks."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        prompt = _read_prompt(args)
        result = compile_task_packet(prompt, task_id=args.task_id, project=args.project)
        output_path = _output_path(args.output)
        write_mission_contract(result.contract, output_path)
        print(json.dumps(summary_for_result(output_path, result), ensure_ascii=False, sort_keys=True))
        return 0
    except TaskCompilationError as exc:
        print(
            json.dumps(
                {"status": "error", "errors": exc.errors},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "errors": [
                        {
                            "field": "filesystem",
                            "message": str(exc),
                            "code": "io_error",
                        }
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())