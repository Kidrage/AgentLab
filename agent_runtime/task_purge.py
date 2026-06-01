"""AgentLab Task Purge Module — 任务归档清理 + 项目文档生成

提供自动归档与清理功能，维护项目长期健康度：
1. 归档完成的任务至 `archive/` 目录
2. 清理超过保留期限的临时任务
3. 支持保留标记（keep: true）
4. 生成项目专属文档（开发流程、使用说明、CHANGELOG）
5. 对应 Archivist Agent (T5归档层) bulk 文档整合模式
"""

from __future__ import annotations

import shutil
import time
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_dir(agentlab_root: Path, project: str) -> Path:
    return agentlab_root / "projects" / project


def _runs_dir(agentlab_root: Path, project: str) -> Path:
    return _project_dir(agentlab_root, project) / "runs"


def auto_archive_tasks(
    agentlab_root: Path,
    project: str,
    keep_days: int = 7,
    *,
    dry_run: bool = False,
) -> list[dict]:
    """自动归档已完成任务

    Returns list of dicts with task_id, action, reason.
    """
    runs_d = _runs_dir(agentlab_root, project)
    if not runs_d.exists():
        return []

    archive_base = _project_dir(agentlab_root, project) / "archive"
    results = []
    now = time.time()

    for task_dir in sorted(runs_d.iterdir()):
        if not task_dir.is_dir() or task_dir.name.startswith("."):
            continue

        task_id = task_dir.name
        state_yml = task_dir / "state.yml"
        age_days = -1

        # Read state to determine task status
        status = "unknown"
        completed_at = None
        keep_flag = False
        if state_yml.exists():
            try:
                state = yaml.safe_load(state_yml.read_text(encoding="utf-8")) or {}
                status = state.get("status", "unknown")
                completed_at = state.get("completed_at")
                keep_flag = state.get("keep", False)
                if completed_at:
                    try:
                        completed_dt = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
                        age_days = (now - completed_dt.timestamp()) / 86400
                    except (ValueError, TypeError):
                        pass
            except Exception:
                pass

        # Check keep flag
        if keep_flag:
            results.append({
                "task_id": task_id,
                "action": "skip",
                "reason": "keep flag set",
            })
            continue

        # Determine action
        if status == "completed" and age_days > keep_days:
            action = "archive"
            reason = f"completed, age={age_days:.1f}d > keep_days={keep_days}"
        elif status == "completed":
            action = "skip"
            reason = f"completed but age={age_days:.1f}d <= keep_days={keep_days}"
        else:
            action = "skip"
            reason = f"status={status}"

        if action == "archive":
            if not dry_run:
                archive_path = archive_base / task_id
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(task_dir), str(archive_path))
            results.append({
                "task_id": task_id,
                "action": "archive",
                "reason": reason,
                "status": status,
                "age_days": round(age_days, 1),
            })
        else:
            results.append({
                "task_id": task_id,
                "action": action,
                "reason": reason,
                "status": status,
            })

    return results


def generate_project_documentation(
    agentlab_root: Path,
    project: str,
) -> dict:
    """生成项目专属文档（开发流程、使用说明、CHANGELOG）

    整合所有完成任务的 implementation_report 和 user_request，
    生成项目级别的文档文件。

    Returns dict with generated file paths and summaries.
    """
    proj_d = _project_dir(agentlab_root, project)
    doc_dir = proj_d / "docs"
    doc_dir.mkdir(parents=True, exist_ok=True)

    runs_d = _runs_dir(agentlab_root, project)
    generated = {}

    # ── 收集所有任务信息 ──────────────────────────────────────────────

    task_summaries: list[dict] = []
    for task_dir in sorted(runs_d.iterdir()) if runs_d.exists() else []:
        if not task_dir.is_dir() or task_dir.name.startswith("."):
            continue

        info = {"task_id": task_dir.name, "title": "", "summary": "", "files_changed": []}

        # Read user request
        user_req = task_dir / "user_request.md"
        if user_req.exists():
            lines = user_req.read_text(encoding="utf-8").split("\n")[:20]
            info["title"] = next((l.strip("# ").strip() for l in lines if l.startswith("#")), task_dir.name)
            info["summary"] = next((l.strip() for l in lines if l.strip() and not l.startswith("#")), "")

        # Read implementation report
        impl = task_dir / "implementation_report.md"
        if impl.exists():
            text = impl.read_text(encoding="utf-8")
            for line in text.split("\n"):
                if line.startswith("|") and "|" in line[1:]:
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if len(parts) >= 1 and parts[0] not in ("File", "---"):
                        info["files_changed"].append(parts[0])

        # Read state
        state_yml = task_dir / "state.yml"
        if state_yml.exists():
            try:
                state = yaml.safe_load(state_yml.read_text(encoding="utf-8")) or {}
                info["status"] = state.get("status", "unknown")
                info["route"] = state.get("route", [])
            except Exception:
                pass

        task_summaries.append(info)

    # ── 生成开发流程文档 ──────────────────────────────────────────────

    dev_lines = [
        f"# {project} 开发流程文档",
        "",
        f"> 自动生成于 {_utc_now()}  |  Archivist (T5)",
        "",
        "## 项目概述",
        "",
        f"本项目共完成 {len(task_summaries)} 个任务。以下为各任务的开发记录汇总。",
        "",
        "---",
        "",
        "## 任务列表",
        "",
    ]

    for ts in task_summaries:
        dev_lines.append(f"### {ts['task_id']}: {ts.get('title', '无标题')}")
        dev_lines.append("")
        dev_lines.append(f"- **状态**: {ts.get('status', 'unknown')}")
        dev_lines.append(f"- **概述**: {ts.get('summary', '无描述')}")
        route = ts.get("route", [])
        if route:
            dev_lines.append(f"- **路由**: {' → '.join(route)}")
        changed = ts.get("files_changed", [])
        if changed:
            dev_lines.append(f"- **变更文件**: {', '.join(changed[:10])}")
        dev_lines.append("")

    dev_path = doc_dir / "development_process.md"
    dev_path.write_text("\n".join(dev_lines), encoding="utf-8")
    generated["development_process.md"] = f"{len(task_summaries)} tasks documented"

    # ── 生成使用指南 ──────────────────────────────────────────────────

    usage_lines = [
        f"# {project} 使用指南",
        "",
        f"> 自动生成于 {_utc_now()}  |  DocManager Agent (T5)",
        "",
        "## 快速开始",
        "",
        "```bash",
        "./agentlab.sh init-task --project {project} --task-id task_XXXX",
        "./agentlab.sh prepare --project {project} --task-id task_XXXX --write-plan",
        "./agentlab.sh run-agent Supervisor --project {project} --task-id task_XXXX --execute",
        "```",
        "",
        "## CLI 命令参考",
        "",
        "| 命令 | 用途 |",
        "|---|---|",
        "| `init-task` | 初始化新任务 |",
        "| `prepare` | 生成工作流计划 |",
        "| `status` | 查看任务状态 |",
        "| `run-agent` | 运行 Agent (dry-run / --execute) |",
        "| `brain-status` | 查看大脑治理状态 |",
        "| `guard-status` | 查看守护状态 |",
        "| `task-search` | 搜索任务 |",
        "| `chat` | 终端对话 |",
        "| `task-purge` | 归档清理 + 生成文档 |",
        "",
        "## 项目配置",
        "",
        f"配置文件位于 `projects/{project}/project_config.yml`。",
        "全局策略位于 `config/` 目录。",
        "",
        "## 常见工作流",
        "",
        "### 新功能开发",
        "1. 创建任务: `./agentlab.sh init-task`",
        "2. 生成计划: `./agentlab.sh prepare --write-plan`",
        "3. 运行大脑Agent: `./agentlab.sh run-agent Supervisor --execute`",
        "4. 运行Coder: `./agentlab.sh run-agent Coder --execute`",
        "5. 验证审计: `./agentlab.sh run-agent TesterAuditor --execute`",
        "",
        "### 任务清理",
        "```bash",
        "# 预览清理内容 (dry-run)",
        "./agentlab.sh task-purge --project {project} --keep-days 7 --dry-run",
        "",
        "# 执行清理 + 生成文档",
        "./agentlab.sh task-purge --project {project} --keep-days 7",
        "```",
    ]

    usage_path = doc_dir / "usage_guide.md"
    usage_path.write_text("\n".join(usage_lines), encoding="utf-8")
    generated["usage_guide.md"] = "usage guide generated"

    # ── 生成 CHANGELOG ────────────────────────────────────────────────

    changelog_lines = [
        f"# {project} 更新日志",
        "",
        f"> 自动维护于 {_utc_now()}  |  DocManager Agent (T5)",
        "",
        "| 任务ID | 状态 | 标题 | 变更文件数 |",
        "|---|---|---|---|",
    ]

    for ts in sorted(task_summaries, key=lambda x: x.get("task_id", "")):
        changed_count = len(ts.get("files_changed", []))
        changelog_lines.append(
            f"| {ts['task_id']} | {ts.get('status', '?')} | "
            f"{ts.get('title', '无标题')[:60]} | {changed_count} |"
        )

    changelog_path = doc_dir / "CHANGELOG.md"
    changelog_path.write_text("\n".join(changelog_lines), encoding="utf-8")
    generated["CHANGELOG.md"] = f"{len(task_summaries)} entries"

    # ── 生成任务索引 ──────────────────────────────────────────────────

    index_lines = [
        f"# {project} 任务索引",
        "",
        f"> 自动生成于 {_utc_now()}",
        "",
        "| 任务ID | 状态 | 标题 | 路由 |",
        "|---|---|---|---|",
    ]

    for ts in sorted(task_summaries, key=lambda x: x.get("task_id", "")):
        route_str = " → ".join(ts.get("route", []))
        index_lines.append(
            f"| {ts['task_id']} | {ts.get('status', '?')} | "
            f"{ts.get('title', '无标题')[:50]} | {route_str[:60]} |"
        )

    index_path = doc_dir / "task_index.md"
    index_path.write_text("\n".join(index_lines), encoding="utf-8")
    generated["task_index.md"] = f"{len(task_summaries)} tasks indexed"

    return generated


def task_purge(
    agentlab_root: Path,
    project: str,
    keep_days: int = 7,
    *,
    dry_run: bool = False,
) -> dict:
    """主任务清理流程: 归档 + 文档生成

    Args:
        agentlab_root: AgentLab 根目录
        project: 项目名称
        keep_days: 完成多少天后归档
        dry_run: 只预览不实际执行
    Returns:
        purge_report dict
    """
    proj_d = _project_dir(agentlab_root, project)

    # 1. 自动归档
    archive_results = auto_archive_tasks(
        agentlab_root, project, keep_days, dry_run=dry_run
    )

    # 2. 生成文档
    doc_results = generate_project_documentation(agentlab_root, project)

    # 3. 写入清理报告
    purge_report = {
        "version": 1,
        "project": project,
        "timestamp": _utc_now(),
        "dry_run": dry_run,
        "keep_days": keep_days,
        "archive_results": archive_results,
        "archived_count": sum(1 for r in archive_results if r["action"] == "archive"),
        "skipped_count": sum(1 for r in archive_results if r["action"] == "skip"),
        "generated_docs": list(doc_results.keys()),
        "doc_summaries": doc_results,
    }

    report_path = proj_d / "runs" / "task_purge_report.yml"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(yaml.dump(purge_report, allow_unicode=True), encoding="utf-8")

    return purge_report
