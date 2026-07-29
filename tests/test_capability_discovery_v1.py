from __future__ import annotations

from pathlib import Path
import os
import subprocess

from agent_runtime.capability_discovery import (
    GitHubSourceAdapter,
    LocalAgentSkillsAdapter,
    McpRegistrySourceAdapter,
)


def test_local_agent_skills_discovery_loads_metadata_not_instruction_body(
    tmp_path: Path,
) -> None:
    skill = tmp_path / "pdf-processing"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: pdf-processing\n"
        "description: Process PDFs when extraction is requested.\n"
        "license: Apache-2.0\n"
        "compatibility: Requires local pdftotext.\n"
        "---\n"
        "SECRET_INSTRUCTION_BODY_MUST_NOT_BE_DISCOVERED\n",
        encoding="utf-8",
    )
    (skill / "scripts").mkdir()

    candidates = LocalAgentSkillsAdapter(tmp_path).search("pdf")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["name"] == "pdf-processing"
    assert candidate["lifecycle_status"] == "quarantined"
    assert candidate["progressive_disclosure"]["metadata_loaded"] is True
    assert candidate["progressive_disclosure"]["instructions_loaded"] is False
    assert "SECRET_INSTRUCTION" not in str(candidate)
    assert candidate["contains_code"] is True


def test_mcp_registry_metadata_is_untrusted_and_uses_pessimistic_risk_defaults() -> None:
    payload = {
        "servers": [
            {
                "server": {
                    "name": "io.example/read-only",
                    "description": "Claims to read records.",
                    "version": "1.0.0",
                    "repository": {
                        "url": "https://github.com/example/read-only",
                        "source": "github",
                    },
                    "packages": [
                        {
                            "registryType": "npm",
                            "identifier": "@example/read-only",
                            "version": "1.0.0",
                        }
                    ],
                    "_meta": {
                        "tool_annotations": {
                            "readOnlyHint": True,
                            "destructiveHint": False,
                        }
                    },
                }
            }
        ]
    }

    candidates = McpRegistrySourceAdapter.parse(payload)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["source_kind"] == "mcp_registry"
    assert candidate["registry_metadata_only"] is True
    assert candidate["annotations_trusted"] is False
    assert candidate["effective_risk"] == {
        "read_only": False,
        "destructive": True,
        "idempotent": False,
        "open_world": True,
    }


def test_github_popularity_is_discovery_signal_not_promotion_evidence() -> None:
    payload = {
        "items": [
            {
                "full_name": "example/capability",
                "html_url": "https://github.com/example/capability",
                "description": "Example capability",
                "stargazers_count": 50000,
                "default_branch": "main",
                "license": {"spdx_id": "Apache-2.0"},
            }
        ]
    }

    candidates = GitHubSourceAdapter.parse(payload)

    assert candidates[0]["discovery_signals"]["stars"] == 50000
    assert candidates[0]["promotion_evidence_eligible"] is False
    assert candidates[0]["lifecycle_status"] == "quarantined"


def test_capability_cli_exposes_task_search_and_radar() -> None:
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [str(root / "agentlab.sh"), "capability", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "NO_COLOR": "1", "COLUMNS": "180"},
    )

    assert result.returncode == 0, result.stderr
    for command in ("search", "radar", "audit", "audition"):
        assert command in result.stdout
