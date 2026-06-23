"""Audition tasks definitions and mock expectations for AgentLab workers."""

from pathlib import Path
from typing import Tuple


class AuditionTask:
    def __init__(self, task_type: str, role: str, description: str) -> None:
        self.task_type = task_type
        self.role = role
        self.description = description

    def verify(self, stdout: str, sandbox_path: Path) -> bool:
        """Verify if the execution stdout matches expectations."""
        # Baseline checks for valid execution outputs
        if not stdout or "error" in stdout.lower() or "failed" in stdout.lower():
            return False
        return True

    def get_mock_output(self, worker_id: str) -> tuple[str, float, float]:
        """Return simulated execution output, cost, and latency for mock runs."""
        # Returns: (stdout, cost_usd, latency_s)
        base_cost = 0.05
        base_latency = 1.5
        
        # Simulate different costs/latencies per worker
        if worker_id in ("claude_code", "codex", "aider"):
            base_cost = 0.15
            base_latency = 4.5
        elif worker_id == "bl":
            base_cost = 0.08
            base_latency = 2.0
        elif worker_id in ("rg", "pytest", "ruff", "git"):
            base_cost = 0.0
            base_latency = 0.2

        if self.task_type == "repo_search_task":
            return (
                "Found class calculate_total in mock_repo/main.py:1\nFound format_currency in utils.py:1",
                base_cost,
                base_latency
            )
        elif self.task_type == "interface_mapping_task":
            return (
                "Class: calculate_total (args: items)\nClass: format_currency (args: val)",
                base_cost,
                base_latency
            )
        elif self.task_type == "small_patch_task":
            return (
                "Successfully applied patch to main.py\n+ return sum(items) * 1.0",
                base_cost,
                base_latency
            )
        elif self.task_type == "test_runner_task":
            return (
                "============================= test session starts ==============================\ntests/test_main.py . [100%]\n============================== 1 passed in 0.03s ===============================",
                base_cost,
                base_latency
            )
        elif self.task_type == "lint_review_task":
            return (
                "All checks passed. No violations found.",
                base_cost,
                base_latency
            )
        elif self.task_type == "handoff_generation_task":
            return (
                "# Supervisor Handoff\n- Coder: modify main.py\n- Verification: run pytest",
                base_cost,
                base_latency
            )
        elif self.task_type == "research_summary_task":
            return (
                "Summary of repository architecture: main.py calculates total, utils.py formats currency.",
                base_cost,
                base_latency
            )
        elif self.task_type == "archive_task":
            return (
                "Successfully archived 4 project outputs.",
                base_cost,
                base_latency
            )
        
        return "Generic task completed successfully.", base_cost, base_latency


# Default built-in task templates for each role
AUDITION_TASKS = {
    "supervisor": AuditionTask("handoff_generation_task", "Supervisor", "Generate task handoff directive"),
    "reposcout": AuditionTask("repo_search_task", "RepoScout", "Search for calculations inside python modules"),
    "interface_mapper": AuditionTask("interface_mapping_task", "InterfaceMapper", "Scan functions arguments and types"),
    "researcher": AuditionTask("research_summary_task", "Researcher", "Summarize structural definitions"),
    "prompt_engineer": AuditionTask("handoff_generation_task", "PromptEngineer", "Construct prompt packages for Coder"),
    "coder": AuditionTask("small_patch_task", "Coder", "Modify summing calculation to support multiplier"),
    "tester_auditor": AuditionTask("test_runner_task", "TesterAuditor", "Run test assertions in the sandbox"),
    "verifier": AuditionTask("lint_review_task", "Verifier", "Analyze codebase style and violations"),
    "archivist": AuditionTask("archive_task", "Archivist", "Perform task packaging and archive artifacts")
}


def get_task_for_role(role: str) -> AuditionTask:
    role_key = role.lower().replace("_", "").replace("-", "")
    # Normalize keys in mapping
    normalized_tasks = {k.replace("_", "").replace("-", ""): v for k, v in AUDITION_TASKS.items()}
    return normalized_tasks.get(role_key, AUDITION_TASKS["coder"])
