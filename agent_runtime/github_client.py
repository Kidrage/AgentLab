"""GitHub API planning helpers for AgentLab sync.

This module intentionally separates request construction from execution so the
UI and agents can review the exact GitHub action before any remote mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import base64
import json
from typing import Any
from urllib import request


GITHUB_API = "https://api.github.com"
API_VERSION = "2022-11-28"


@dataclass
class GitHubRequestPlan:
    method: str
    path: str
    required_permissions: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    mutates_remote: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "required_permissions": self.required_permissions,
            "body": self.body,
            "mutates_remote": self.mutates_remote,
        }


class GitHubClient:
    """Small stdlib GitHub REST client for future approved sync operations."""

    def __init__(self, token: str, api_base: str = GITHUB_API) -> None:
        self.token = token
        self.api_base = api_base.rstrip("/")

    @staticmethod
    def plan_create_private_repo(name: str, description: str = "") -> GitHubRequestPlan:
        return GitHubRequestPlan(
            method="POST",
            path="/user/repos",
            required_permissions={"administration": "write", "contents": "write", "metadata": "read"},
            body={
                "name": name,
                "description": description,
                "private": True,
                "auto_init": True,
            },
            mutates_remote=True,
        )

    @staticmethod
    def plan_put_file(owner: str, repo: str, path: str, content: str, message: str, branch: str = "main") -> GitHubRequestPlan:
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        return GitHubRequestPlan(
            method="PUT",
            path=f"/repos/{owner}/{repo}/contents/{path}",
            required_permissions={"contents": "write", "metadata": "read"},
            body={
                "message": message,
                "content": encoded,
                "branch": branch,
            },
            mutates_remote=True,
        )

    @staticmethod
    def plan_workflow_dispatch(owner: str, repo: str, workflow_id: str, ref: str, inputs: dict[str, str] | None = None) -> GitHubRequestPlan:
        return GitHubRequestPlan(
            method="POST",
            path=f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches",
            required_permissions={"actions": "write", "metadata": "read"},
            body={
                "ref": ref,
                "inputs": inputs or {},
            },
            mutates_remote=True,
        )

    def execute(self, plan: GitHubRequestPlan) -> dict[str, Any]:
        """Execute an already-approved GitHub request plan."""
        if not self.token:
            raise ValueError("GitHub token is required")
        req = request.Request(
            f"{self.api_base}{plan.path}",
            data=json.dumps(plan.body).encode("utf-8") if plan.body else None,
            method=plan.method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": API_VERSION,
                "Content-Type": "application/json",
            },
        )
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {"status": response.status}
