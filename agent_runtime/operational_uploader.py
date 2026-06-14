"""Narrow operational executors for deployment-style AgentLab tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse

from schemas import LLMCallResult, WorkflowPlan


@dataclass
class CommandResult:
    command: list[str]
    cwd: str | None
    returncode: int
    stdout: str
    stderr: str

    @property
    def command_text(self) -> str:
        return " ".join(self.command)


def maybe_run_operational_agent(plan: WorkflowPlan, agent_name: str) -> LLMCallResult | None:
    """Run deterministic shell work for a small class of upload tasks.

    This intentionally handles only explicit local-git-to-Gitea upload requests.
    It is not a general shell executor for arbitrary model output.
    """
    if agent_name not in {"Coder", "TesterAuditor"}:
        return None

    request = _read_text(Path(plan.user_request_path))
    local_repo = _extract_local_repo(request)
    target_url = _extract_target_url(request)
    if not local_repo or not target_url:
        return None
    if not _looks_like_gitea_repo_url(target_url):
        return None
    if not local_repo.exists() or not (local_repo / ".git").exists():
        return None

    if agent_name == "Coder":
        return _run_git_upload(plan, local_repo, target_url)
    return _run_git_upload_validation(plan, local_repo, target_url)


def _run_git_upload(plan: WorkflowPlan, local_repo: Path, target_url: str) -> LLMCallResult:
    results: list[CommandResult] = []

    def run(args: list[str], *, check: bool = True) -> CommandResult:
        result = _run(args, cwd=local_repo)
        results.append(result)
        if check and result.returncode != 0:
            raise RuntimeError(f"{' '.join(args)} failed with {result.returncode}: {result.stderr.strip()}")
        return result

    try:
        status = run(["git", "status", "--short"])
        branch = run(["git", "branch", "--show-current"]).stdout.strip()
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        remote = run(["git", "remote", "get-url", "origin"]).stdout.strip()
        before = run(["git", "ls-remote", "origin", f"refs/heads/{branch}"], check=False)

        if status.stdout.strip():
            content = _render_report(
                plan, "Coder", local_repo, target_url, results,
                summary="Upload blocked because the local git worktree is dirty.",
                risks=["Dirty worktree could upload unreviewed or unintended changes."],
                blockers=["Commit, stash, or explicitly approve the dirty files before upload."],
                deliverables=["USER_DECISION_REQUIRED.md"],
            )
            decision = Path(plan.run_dir) / "USER_DECISION_REQUIRED.md"
            decision.write_text(content, encoding="utf-8")
            return LLMCallResult(
                provider="agentlab-operational-uploader",
                model="git-push-v1",
                content=content,
                status="blocked_user_decision",
                error="Dirty worktree blocks upload.",
                raw_usage={"operational": True, "dirty_worktree": True},
            )

        push = run(["git", "push", "origin", f"HEAD:{branch}"])
        after = run(["git", "ls-remote", "origin", f"refs/heads/{branch}"])
        http = _run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{content_type} %{size_download}", target_url])
        results.append(http)

        remote_head = _ls_remote_hash(after.stdout)
        success = push.returncode == 0 and remote_head == head and http.stdout.startswith("200 ")
        summary = (
            f"Uploaded local HEAD {head[:12]} to origin/{branch}; target page returned {http.stdout.strip()}."
            if success else
            "Upload command ran but remote/page verification did not prove success."
        )
        risks = [] if success else ["Remote HEAD or HTTP page verification did not match the expected success criteria."]
        blockers = [] if success else ["Review command output and rerun upload after resolving verification mismatch."]

        content = _render_report(
            plan, "Coder", local_repo, target_url, results,
            summary=summary,
            risks=risks,
            blockers=blockers,
            deliverables=[
                f"origin/{branch} at {remote_head or '[unknown]'}",
                f"HTTP verification: {http.stdout.strip()}",
            ],
            extra={
                "branch": branch,
                "local_head": head,
                "remote": remote,
                "remote_before": before.stdout.strip() or "[empty]",
                "remote_after": after.stdout.strip() or "[empty]",
            },
        )
        status_value = "completed" if success else "blocked_user_decision"
        return LLMCallResult(
            provider="agentlab-operational-uploader",
            model="git-push-v1",
            content=content,
            status=status_value,
            error=None if success else "Upload verification failed.",
            raw_usage={"operational": True, "upload_success": success},
        )
    except Exception as exc:
        content = _render_report(
            plan, "Coder", local_repo, target_url, results,
            summary="Upload failed during AgentLab operational execution.",
            risks=["The target repository may be unreachable or authentication may be missing."],
            blockers=[str(exc)],
            deliverables=[],
        )
        return LLMCallResult(
            provider="agentlab-operational-uploader",
            model="git-push-v1",
            content=content,
            status="blocked_user_decision",
            error=str(exc),
            raw_usage={"operational": True, "exception": str(exc)},
        )


def _run_git_upload_validation(plan: WorkflowPlan, local_repo: Path, target_url: str) -> LLMCallResult:
    results: list[CommandResult] = []

    def run(args: list[str], *, check: bool = True) -> CommandResult:
        result = _run(args, cwd=local_repo)
        results.append(result)
        if check and result.returncode != 0:
            raise RuntimeError(f"{' '.join(args)} failed with {result.returncode}: {result.stderr.strip()}")
        return result

    try:
        status = run(["git", "status", "--short"])
        branch = run(["git", "branch", "--show-current"]).stdout.strip()
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        remote = run(["git", "ls-remote", "origin", f"refs/heads/{branch}"])
        http = _run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{content_type} %{size_download}", target_url])
        results.append(http)
        remote_head = _ls_remote_hash(remote.stdout)
        passed = not status.stdout.strip() and remote_head == head and http.stdout.startswith("200 ")
        content = _render_report(
            plan, "TesterAuditor", local_repo, target_url, results,
            summary="Upload validation passed." if passed else "Upload validation failed.",
            risks=[] if passed else ["Local HEAD, remote HEAD, clean worktree, or HTTP page check did not pass."],
            blockers=[] if passed else ["Re-run Coder upload after resolving failed validation evidence."],
            deliverables=[
                f"local HEAD: {head}",
                f"remote HEAD: {remote_head or '[unknown]'}",
                f"HTTP verification: {http.stdout.strip()}",
            ],
            extra={"branch": branch, "passed": str(passed).lower()},
        )
        return LLMCallResult(
            provider="agentlab-operational-uploader",
            model="git-upload-validator-v1",
            content=content,
            status="completed" if passed else "blocked_user_decision",
            error=None if passed else "Upload validation failed.",
            raw_usage={"operational": True, "validation_passed": passed},
        )
    except Exception as exc:
        content = _render_report(
            plan, "TesterAuditor", local_repo, target_url, results,
            summary="Upload validation failed during AgentLab operational execution.",
            risks=["The target repository may be unreachable or authentication may be missing."],
            blockers=[str(exc)],
            deliverables=[],
        )
        return LLMCallResult(
            provider="agentlab-operational-uploader",
            model="git-upload-validator-v1",
            content=content,
            status="blocked_user_decision",
            error=str(exc),
            raw_usage={"operational": True, "exception": str(exc)},
        )


def _render_report(
    plan: WorkflowPlan,
    agent_name: str,
    local_repo: Path,
    target_url: str,
    results: list[CommandResult],
    *,
    summary: str,
    risks: list[str],
    blockers: list[str],
    deliverables: list[str],
    extra: dict[str, str] | None = None,
) -> str:
    commands = "\n".join(f"- `{r.command_text}` -> exit {r.returncode}" for r in results) or "- None"
    evidence = "\n\n".join(_format_command_result(r) for r in results) or "No command evidence recorded."
    extra_lines = "\n".join(f"- {k}: {v}" for k, v in (extra or {}).items()) or "- None"
    risks_text = "\n".join(f"- {risk}" for risk in risks) or "- None"
    blockers_text = "\n".join(f"- {blocker}" for blocker in blockers) or "- None"
    deliverables_text = "\n".join(f"- {item}" for item in deliverables) or "- None"
    now = datetime.now(timezone.utc).isoformat()
    title = "Coder Report" if agent_name == "Coder" else "Tester/Auditor Report"
    scope = "Git upload to explicit Gitea remote." if agent_name == "Coder" else "Independent validation of git upload."
    return f"""# {title}

## Task
- Task id: {plan.task_id}
- User request: {_read_text(Path(plan.user_request_path)).strip()}
- Assigned scope: {scope}

## Work Performed
- Files read: {local_repo}/.git metadata, task request, workflow plan
- Commands run:
{commands}
- Backend: agentlab-operational-uploader
- Target URL: {target_url}
- Local repo: {local_repo}
- Completed at: {now}
- Key observations:
{extra_lines}

## Findings
- Summary: {summary}
- Risks:
{risks_text}
- Blockers:
{blockers_text}

## Outputs
- Deliverables:
{deliverables_text}
- Recommended next steps: {"Proceed to validation/audit." if not blockers else "Resolve blockers and rerun this agent."}

## Command Evidence

{evidence}
"""


def _format_command_result(result: CommandResult) -> str:
    stdout = result.stdout.strip() or "[empty]"
    stderr = result.stderr.strip() or "[empty]"
    return f"""### `{result.command_text}`

- cwd: `{result.cwd or "[none]"}`
- exit: {result.returncode}
- stdout:
```text
{stdout}
```
- stderr:
```text
{stderr}
```"""


def _run(args: list[str], cwd: Path | None = None) -> CommandResult:
    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=120,
    )
    return CommandResult(
        command=args,
        cwd=str(cwd) if cwd else None,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _extract_local_repo(request: str) -> Path | None:
    users_root_pattern = "/" + "Users" + r"/[^\s，,]+/AO-SpatialAuthoring-Modular"
    match = re.search(users_root_pattern, request)
    return Path(match.group(1)) if match else None


def _extract_target_url(request: str) -> str | None:
    match = re.search(r"https?://[^\s，,]+", request)
    return match.group(0).rstrip("。.)") if match else None


def _looks_like_gitea_repo_url(url: str) -> bool:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    return parsed.scheme in {"http", "https"} and len(parts) >= 2


def _ls_remote_hash(output: str) -> str:
    first = output.strip().splitlines()[0] if output.strip() else ""
    return first.split()[0] if first else ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""
