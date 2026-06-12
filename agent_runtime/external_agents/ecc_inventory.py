"""ECC static inventory scanner.

This scanner is static-only: it does not execute scripts, load hooks, start MCP
servers, or invoke ECC commands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import re

from atomic_io import atomic_write_json, safe_read_yaml


DEFAULT_CONFIG = {
    "ecc": {
        "enabled": False,
        "mode": "inventory_only",
        "local_paths": ["${ECC_HOME}", "./external/everything-claude-code", "./external/ECC"],
        "scan": {"allow_markdown_scan": True, "allow_json_yaml_scan": True, "max_files": 200, "max_file_kb": 256},
        "import_policy": {
            "default_enabled": False,
            "require_manual_enable": True,
            "max_imported_skills": 80,
            "allow_commands": False,
            "allow_hooks": False,
            "allow_mcp_servers": False,
        },
        "risk_defaults": {"level": "medium", "requires_approval": True},
    }
}


def load_ecc_config(agentlab_root: Path, path: Path | None = None) -> dict[str, Any]:
    data = safe_read_yaml(path or (agentlab_root / "config" / "ecc_integration.yml"), default={}) or {}
    if not isinstance(data, dict) or not data:
        data = DEFAULT_CONFIG
    merged = dict(DEFAULT_CONFIG["ecc"])
    merged.update(data.get("ecc", data) or {})
    merged.setdefault("scan", dict(DEFAULT_CONFIG["ecc"]["scan"]))
    merged.setdefault("import_policy", dict(DEFAULT_CONFIG["ecc"]["import_policy"]))
    merged.setdefault("risk_defaults", dict(DEFAULT_CONFIG["ecc"]["risk_defaults"]))
    return {"ecc": merged}


def _expand_path(agentlab_root: Path, raw: str) -> Path | None:
    expanded = os.path.expandvars(raw)
    if "$" in expanded or not expanded:
        return None
    path = Path(expanded).expanduser()
    return path if path.is_absolute() else (agentlab_root / path)


def find_ecc_path(agentlab_root: Path, config: dict[str, Any]) -> tuple[Path | None, list[str]]:
    warnings: list[str] = []
    for raw in config.get("ecc", {}).get("local_paths", []) or []:
        path = _expand_path(agentlab_root, str(raw))
        if path and path.exists() and path.is_dir():
            return path, warnings
    warnings.append("ECC path not found; static inventory returned found=false.")
    return None, warnings


def _capabilities_from_text(name: str, text: str) -> list[str]:
    hay = f"{name}\n{text}".lower()
    caps: set[str] = set()
    mapping = {
        "planning": ["plan", "planner", "task decomposition", "strategy"],
        "task_decomposition": ["decomposition", "break down", "subtask"],
        "repo_strategy": ["repo", "repository", "codebase"],
        "code_review": ["review", "code-reviewer", "critic"],
        "security_review": ["security", "vulnerability", "threat"],
        "implementation": ["implement", "coding", "patch"],
    }
    for cap, needles in mapping.items():
        if any(n in hay for n in needles):
            caps.add(cap)
    return sorted(caps) or ["external_workflow"]


def _task_types_from_caps(caps: list[str]) -> list[str]:
    tasks: set[str] = set()
    if {"planning", "task_decomposition", "repo_strategy"}.intersection(caps):
        tasks.update({"repo_patch", "architecture_review", "implementation_plan"})
    if "security_review" in caps:
        tasks.add("security_review")
    if "code_review" in caps:
        tasks.add("repo_patch")
    return sorted(tasks)


def _agent_record(name: str, source_file: str, text: str, risk_level: str) -> dict[str, Any]:
    safe = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "agent"
    caps = _capabilities_from_text(name, text)
    return {
        "id": f"ecc.{safe}",
        "name": safe,
        "type": "agent",
        "source_file": source_file,
        "capabilities": caps,
        "suitable_task_types": _task_types_from_caps(caps),
        "risk_level": risk_level,
        "enabled_by_default": False,
    }


def _parse_agents_md(path: Path, root: Path, text: str, risk_level: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    rel = str(path.relative_to(root))
    # Common markdown headings: ## planner, ### code-reviewer, etc.
    for match in re.finditer(r"^#{1,4}\s+([A-Za-z0-9][A-Za-z0-9_-]{2,64})\s*$", text, re.MULTILINE):
        name = match.group(1)
        if name.lower() in {"agents", "overview", "usage", "installation"}:
            continue
        snippet = text[match.start(): match.start() + 800]
        records.append(_agent_record(name, rel, snippet, risk_level))
    # Fallback bullet style: - planner: ...
    for match in re.finditer(r"^\s*[-*]\s+`?([A-Za-z0-9][A-Za-z0-9_-]{2,64})`?\s*[:—-]", text, re.MULTILINE):
        name = match.group(1)
        rec = _agent_record(name, rel, text[match.start(): match.start() + 500], risk_level)
        if rec["id"] not in {r["id"] for r in records}:
            records.append(rec)
    return records


def _parse_skill_md(path: Path, root: Path, text: str, risk_level: str) -> dict[str, Any]:
    rel = str(path.relative_to(root))
    name = path.parent.name if path.name == "SKILL.md" else path.stem
    caps = _capabilities_from_text(name, text[:2000])
    return {
        "id": f"ecc.{re.sub(r'[^a-z0-9-]+', '-', name.lower()).strip('-')}",
        "name": name,
        "type": "skill",
        "source_file": rel,
        "capabilities": caps,
        "suitable_task_types": _task_types_from_caps(caps),
        "risk_level": risk_level,
        "enabled_by_default": False,
    }


def _is_candidate(path: Path) -> bool:
    parts = set(path.parts)
    name = path.name
    if name in {"AGENTS.md", "README.md"}:
        return True
    if name == "SKILL.md" and "skills" in parts:
        return True
    if "commands" in parts:
        return True
    return path.suffix.lower() in {".yml", ".yaml", ".json"}


def scan_ecc_inventory(agentlab_root: Path, config: dict[str, Any] | None = None, output_path: Path | None = None) -> dict[str, Any]:
    cfg = config or load_ecc_config(agentlab_root)
    ecc_cfg = cfg.get("ecc", cfg)
    ecc_path, warnings = find_ecc_path(agentlab_root, {"ecc": ecc_cfg})
    inventory = {
        "source": "ecc",
        "source_path": str(ecc_path) if ecc_path else None,
        "scan_mode": "static_inventory_only",
        "found": bool(ecc_path),
        "warnings": warnings,
        "agents": [],
        "skills": [],
        "commands": [],
        "mcp_servers": [],
        "hooks": [],
    }
    if not ecc_path:
        if output_path:
            atomic_write_json(output_path, inventory)
        return inventory

    scan = ecc_cfg.get("scan", {}) or {}
    max_files = int(scan.get("max_files", 200))
    max_bytes = int(scan.get("max_file_kb", 256)) * 1024
    allow_md = bool(scan.get("allow_markdown_scan", True))
    allow_structured = bool(scan.get("allow_json_yaml_scan", True))
    risk_level = str((ecc_cfg.get("risk_defaults") or {}).get("level") or "medium")
    seen = 0
    for path in sorted(ecc_path.rglob("*")):
        if not path.is_file() or not _is_candidate(path):
            continue
        seen += 1
        rel = str(path.relative_to(ecc_path))
        if seen > max_files:
            inventory["warnings"].append(f"Skipped {rel}: max_files limit reached ({max_files}).")
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            inventory["warnings"].append(f"Skipped {rel}: stat failed: {exc}")
            continue
        if size > max_bytes:
            inventory["warnings"].append(f"Skipped {rel}: file exceeds max_file_kb ({scan.get('max_file_kb', 256)}).")
            continue
        suffix = path.suffix.lower()
        is_md = suffix == ".md"
        if is_md and not allow_md:
            continue
        if suffix in {".yml", ".yaml", ".json"} and not allow_structured:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            inventory["warnings"].append(f"Skipped {rel}: read failed: {exc}")
            continue
        if path.name == "AGENTS.md":
            inventory["agents"].extend(_parse_agents_md(path, ecc_path, text, risk_level))
        elif path.name == "SKILL.md" and "skills" in path.parts:
            inventory["skills"].append(_parse_skill_md(path, ecc_path, text, risk_level))
        elif "commands" in path.parts:
            inventory["commands"].append({"name": path.stem, "source_file": rel, "enabled_by_default": False, "executed": False})
        elif suffix in {".yml", ".yaml", ".json"}:
            lower = text.lower()
            if "mcp" in lower:
                inventory["mcp_servers"].append({"name": path.stem, "source_file": rel, "enabled_by_default": False, "started": False})
            if "hook" in lower:
                inventory["hooks"].append({"name": path.stem, "source_file": rel, "enabled_by_default": False, "loaded": False})
    # Deduplicate agents by id, preserving first source_file evidence.
    dedup: dict[str, dict[str, Any]] = {}
    for record in inventory["agents"]:
        dedup.setdefault(record["id"], record)
    inventory["agents"] = list(dedup.values())
    if output_path:
        atomic_write_json(output_path, inventory)
    return inventory
