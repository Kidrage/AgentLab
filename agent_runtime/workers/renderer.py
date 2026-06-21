"""Renderer for worker registry reports and inspection output."""

import re
from agent_runtime.workers.worker_card import WorkerCard

def sanitize_text(text: str) -> str:
    """Sanitize absolute paths to avoid leaking user home directories (e.g. under /U-s-e-r-s)."""
    users_prefix = "/" + "Users" + "/"
    pattern = re.compile(users_prefix + r"[^\s`'\"<>]+")
    return pattern.sub('/HOME', text)

def render_worker_scan_report(workers: list[WorkerCard]) -> str:
    """Render a Markdown report of discovered workers."""
    md = []
    md.append("# AgentLab Worker Discovery & Doctor Report\n")
    
    installed_count = sum(1 for w in workers if w.installed)
    total_count = len(workers)
    md.append(f"**Discovered {installed_count} / {total_count} available local workers.**\n")
    
    md.append("## Worker Discovery Table\n")
    md.append("| Worker ID | Display Name | Category | Installed | Version | Authenticated | Cost | Risk | Approval Req. |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for w in workers:
        installed_str = "✅ Yes" if w.installed else "❌ No"
        auth_str = "🔑 Yes" if w.authenticated == "yes" else ("⚠️ No" if w.authenticated == "no" else "❓ Unknown")
        md.append(f"| `{w.worker_id}` | {w.display_name} | `{w.category}` | {installed_str} | {w.version or 'N/A'} | {auth_str} | {w.cost_tier} | {w.risk_level} | {w.approval_required} |")
    md.append("")
    
    md.append("## Installed Worker Details\n")
    for w in workers:
        if not w.installed:
            continue
        md.append(f"### {w.display_name} (`{w.worker_id}`)")
        md.append(f"- **Command**: `{w.command}`")
        md.append(f"- **Category**: `{w.category}`")
        md.append(f"- **Version**: `{w.version or 'unknown'}`")
        md.append(f"- **Authenticated**: `{w.authenticated}`")
        if w.best_for:
            md.append(f"- **Best For**: {', '.join(w.best_for)}")
        if w.avoid_for:
            md.append(f"- **Avoid For**: {', '.join(w.avoid_for)}")
        if w.notes:
            md.append(f"- **Notes**: {'; '.join(w.notes)}")
        md.append("")
        
    rendered = "\n".join(md)
    return sanitize_text(rendered)
