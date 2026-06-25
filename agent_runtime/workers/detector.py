"""Detector to discover and scan local workers."""

from pathlib import Path
from typing import Optional, List
from agent_runtime.workers.worker_card import WorkerCard, WorkerCategory
from agent_runtime.workers.command_probe import probe_command
from agent_runtime.workers.version_probe import probe_version
from agent_runtime.workers.auth_probe import probe_auth

DEFAULT_CANDIDATES = [
    # Coding Agents
    {
        "worker_id": "claude_code",
        "display_name": "Claude Code",
        "command_candidates": ["ccs", "claude"],
        "command": "ccs",
        "category": WorkerCategory.CODING_AGENT,
        "cost_tier": "high",
        "risk_level": "high",
        "default_enabled": False,
        "approval_required": True,
        "best_for": ["repo_level_coding", "architecture_reasoning", "large_refactor"],
        "avoid_for": ["deterministic_search", "cheap_lint", "secret_handling"],
    },
    {
        "worker_id": "codex",
        "display_name": "Codex Code",
        "command": "codex",
        "category": WorkerCategory.CODING_AGENT,
        "cost_tier": "high",
        "risk_level": "high",
        "default_enabled": False,
        "approval_required": True,
        "best_for": ["refactoring", "documentation"],
        "avoid_for": ["interactive_debugging"],
    },
    {
        "worker_id": "aider",
        "display_name": "Aider",
        "command": "aider",
        "category": WorkerCategory.CODING_AGENT,
        "cost_tier": "high",
        "risk_level": "high",
        "default_enabled": False,
        "approval_required": True,
        "best_for": ["git_integrated_coding"],
        "avoid_for": ["planning"],
    },
    # Planning / Brain Agents
    {
        "worker_id": "hermes",
        "display_name": "Hermes CLI",
        "command": "hermes",
        "category": WorkerCategory.PLANNING_AGENT,
        "cost_tier": "medium",
        "risk_level": "high",
        "default_enabled": False,
        "approval_required": True,
        "best_for": ["multi_agent_planning", "supervision"],
        "avoid_for": ["simple_file_edits"],
    },
    {
        "worker_id": "qwen",
        "display_name": "Qwen CLI",
        "command": "qwen",
        "category": WorkerCategory.PLANNING_AGENT,
        "cost_tier": "medium",
        "risk_level": "medium",
        "default_enabled": False,
        "approval_required": True,
    },
    {
        "worker_id": "gemini",
        "display_name": "Gemini CLI",
        "command": "gemini",
        "category": WorkerCategory.PLANNING_AGENT,
        "cost_tier": "medium",
        "risk_level": "medium",
        "default_enabled": False,
        "approval_required": True,
    },
    # Frontdesk / Gateway
    {
        "worker_id": "openclaw",
        "display_name": "OpenClaw Operator",
        "command": "openclaw",
        "category": WorkerCategory.FRONTDESK_AGENT,
        "cost_tier": "medium",
        "risk_level": "medium",
        "default_enabled": False,
        "approval_required": True,
    },
    {
        "worker_id": "agy",
        "display_name": "Antigravity CLI",
        "command": "agy",
        "category": WorkerCategory.FRONTDESK_AGENT,
        "cost_tier": "medium",
        "risk_level": "medium",
        "default_enabled": False,
        "approval_required": True,
    },
    # Multimodal / Cloud
    {
        "worker_id": "bl",
        "display_name": "Bailian CLI",
        "command": "bl",
        "category": WorkerCategory.MULTIMODAL_CLOUD_TOOL,
        "cost_tier": "medium",
        "risk_level": "medium",
        "default_enabled": False,
        "approval_required": True,
        "best_for": ["paid_generation", "image_processing", "multimodal"],
    },
    # Deterministic Repo / AST Tools
    {
        "worker_id": "rg",
        "display_name": "Ripgrep",
        "command": "rg",
        "category": WorkerCategory.DETERMINISTIC_REPO_TOOL,
        "cost_tier": "free",
        "risk_level": "low",
        "default_enabled": True,
        "approval_required": False,
    },
    {
        "worker_id": "git",
        "display_name": "Git VCS",
        "command": "git",
        "category": WorkerCategory.VCS_TOOL,
        "cost_tier": "free",
        "risk_level": "medium",
        "default_enabled": True,
        "approval_required": False,
    },
    {
        "worker_id": "ast_grep",
        "display_name": "ast-grep",
        "command": "ast-grep",
        "category": WorkerCategory.DETERMINISTIC_AST_TOOL,
        "cost_tier": "free",
        "risk_level": "low",
        "default_enabled": True,
        "approval_required": False,
    },
    # Testing & Linting
    {
        "worker_id": "pytest",
        "display_name": "Pytest",
        "command": "pytest",
        "category": WorkerCategory.TEST_RUNNER,
        "cost_tier": "free",
        "risk_level": "medium",
        "default_enabled": True,
        "approval_required": False,
    },
    {
        "worker_id": "ruff",
        "display_name": "Ruff Linter/Formatter",
        "command": "ruff",
        "category": WorkerCategory.LINTER,
        "cost_tier": "free",
        "risk_level": "low",
        "default_enabled": True,
        "approval_required": False,
    },
    {
        "worker_id": "eslint",
        "display_name": "ESLint",
        "command": "eslint",
        "category": WorkerCategory.LINTER,
        "cost_tier": "free",
        "risk_level": "low",
        "default_enabled": True,
        "approval_required": False,
    },
    {
        "worker_id": "mypy",
        "display_name": "Mypy Type Checker",
        "command": "mypy",
        "category": WorkerCategory.LINTER,
        "cost_tier": "free",
        "risk_level": "low",
        "default_enabled": True,
        "approval_required": False,
    },
    # Shell & Container
    {
        "worker_id": "npm",
        "display_name": "NPM",
        "command": "npm",
        "category": WorkerCategory.SHELL_TOOL,
        "cost_tier": "free",
        "risk_level": "medium",
        "default_enabled": True,
        "approval_required": False,
    },
    {
        "worker_id": "pnpm",
        "display_name": "PNPM",
        "command": "pnpm",
        "category": WorkerCategory.SHELL_TOOL,
        "cost_tier": "free",
        "risk_level": "medium",
        "default_enabled": True,
        "approval_required": False,
    },
    {
        "worker_id": "uv",
        "display_name": "UV Package Manager",
        "command": "uv",
        "category": WorkerCategory.SHELL_TOOL,
        "cost_tier": "free",
        "risk_level": "medium",
        "default_enabled": True,
        "approval_required": False,
    },
    {
        "worker_id": "docker",
        "display_name": "Docker Container Tool",
        "command": "docker",
        "category": WorkerCategory.CONTAINER_TOOL,
        "cost_tier": "free",
        "risk_level": "high",
        "default_enabled": False,
        "approval_required": True,
    },
]

def scan_workers() -> list[WorkerCard]:
    """Scan and probe all default candidates on the system."""
    cards = []
    for c in DEFAULT_CANDIDATES:
        actual_command = c["command"]
        installed = False
        
        if "command_candidates" in c:
            for cmd in c["command_candidates"]:
                if probe_command(cmd):
                    actual_command = cmd
                    installed = True
                    break
        else:
            installed = probe_command(actual_command)

        version = probe_version(actual_command) if installed else None
        authenticated = probe_auth(c["worker_id"]) if installed else "no"
        
        # High risk workers default to approval_required = True
        approval_required = c.get("approval_required", True)
        if c.get("risk_level") == "high":
            approval_required = True
            
        card = WorkerCard(
            worker_id=c["worker_id"],
            display_name=c["display_name"],
            command=actual_command,
            installed=installed,
            version=version,
            authenticated=authenticated,
            category=c["category"],
            cost_tier=c.get("cost_tier", "medium"),
            risk_level=c.get("risk_level", "medium"),
            default_enabled=c.get("default_enabled", False),
            approval_required=approval_required,
            best_for=c.get("best_for", []),
            avoid_for=c.get("avoid_for", []),
            notes=c.get("notes", []),
        )
        cards.append(card)
    return cards
