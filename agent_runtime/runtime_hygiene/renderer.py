"""Renderer for runtime layout and audit results."""

from typing import Any
import yaml
import re

def sanitize_text(text: str) -> str:
    """Sanitize absolute paths to avoid leaking user home directories (e.g. under /U-s-e-r-s)."""
    users_prefix = "/" + "Users" + "/"
    pattern = re.compile(users_prefix + r"[^\s`'\"<>]+")
    return pattern.sub('/HOME', text)


def render_layout_yaml(layout_report: Any, symlink_audit: Any, gitignore_audit: Any, secret_scan: Any) -> str:
    """Render a unified YAML report."""
    data = {
        "runtime_layout": layout_report.to_dict(),
        "symlink_audit": symlink_audit.to_dict(),
        "gitignore_audit": gitignore_audit.to_dict(),
        "secret_scan": secret_scan.to_dict()
    }
    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return sanitize_text(dumped)

def render_layout_markdown(layout_report: Any, symlink_audit: Any, gitignore_audit: Any, secret_scan: Any) -> str:
    """Render a unified Markdown report."""
    layout_data = layout_report.to_dict()
    sym_data = symlink_audit.to_dict()
    git_data = gitignore_audit.to_dict()
    sec_data = secret_scan.to_dict()

    md = []
    md.append("# AgentLab Runtime Hygiene Report\n")

    
    # Verdict
    all_warnings = layout_data["warnings"] + sym_data["warnings"] + git_data["warnings"] + sec_data["warnings"]
    verdict = "WARNING" if all_warnings else "PASS"
    md.append(f"## Verdict: {verdict}\n")

    # Layout overview
    md.append("## Layout Overview")
    md.append(f"- **AgentLab Root**: `{layout_data['agentlab_root']}`")
    md.append(f"- **Profiles Dir**: `{layout_data['profiles_dir']}`")
    md.append(f"- **Workspaces Dir**: `{layout_data['workspaces_dir']}`")
    md.append(f"- **Bridges Dir**: `{layout_data['bridges_dir']}`")
    md.append(f"- **Logs Dir**: `{layout_data['logs_dir']}`")
    md.append(f"- **Runtime Dir**: `{layout_data['runtime_dir']}`\n")

    # Profile entries
    md.append("### Profiles")
    md.append("| Name | Path | Exists | Symlink | Git Tracked | Risk Flags |")
    md.append("|---|---|---|---|---|---|")
    for entry in layout_data["profile_entries"]:
        flags = ", ".join(entry["risk_flags"]) if entry["risk_flags"] else "none"
        md.append(f"| {entry['name']} | {entry['path']} | {entry['exists']} | {entry['symlink']} | {entry['git_tracked']} | {flags} |")
    md.append("")

    # Workspace entries
    md.append("### Workspaces")
    md.append("| Name | Path | Exists | Symlink | Git Tracked | Cleanable | Risk Flags |")
    md.append("|---|---|---|---|---|---|---|")
    for entry in layout_data["workspace_entries"]:
        flags = ", ".join(entry["risk_flags"]) if entry["risk_flags"] else "none"
        md.append(f"| {entry['name']} | {entry['path']} | {entry['exists']} | {entry['symlink']} | {entry['git_tracked']} | {entry['cleanable']} | {flags} |")
    md.append("")

    # Symlink audit
    md.append("## Symlink Audit")
    if sym_data["symlinks"]:
        md.append("| Path | Target | Valid | Outside | Absolute | Risk Flags |")
        md.append("|---|---|---|---|---|---|")
        for sym in sym_data["symlinks"]:
            flags = ", ".join(sym["risk_flags"]) if sym["risk_flags"] else "none"
            md.append(f"| {sym['path']} | {sym['target']} | {sym['is_valid']} | {sym['outside_workspace']} | {sym['absolute']} | {flags} |")
    else:
        md.append("No symlinks scanned.")
    md.append("")

    # Gitignore audit
    md.append("## Gitignore Audit")
    if git_data["missing_rules"]:
        md.append("### Missing required rules:")
        for rule in git_data["missing_rules"]:
            md.append(f"- `{rule}`")
    else:
        md.append("All required rules exist in .gitignore.")
    md.append("")

    # Secret scan
    md.append("## Secret Scan")
    if sec_data["findings"]:
        md.append("| File | Line | Pattern | Snippet (Redacted) |")
        md.append("|---|---|---|---|")
        for f in sec_data["findings"]:
            md.append(f"| {f['file']} | {f['line']} | {f['pattern_matched']} | `{f['snippet_redacted']}` |")
    else:
        md.append("No potential secrets found.")
    md.append("")

    # Warnings
    if all_warnings:
        md.append("## Warnings Logged")
        for w in all_warnings:
            md.append(f"- {w}")
        md.append("")

    rendered = "\n".join(md)
    return sanitize_text(rendered)

