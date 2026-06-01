"""Deterministic fake provider for dry-run pipeline tests.

Produces valid report output without calling any real LLM API.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fake_supervisor_output() -> str:
    return """# Supervisor Plan

## Task Summary
Fake evaluation task for lifecycle testing.

## Scope Decision
- In scope: test lifecycle closure
- Out of scope: API calls

## Route
- Supervisor
- RepoScout
- Coder
- TesterAuditor
- Archivist

## Risk Level
Low

## Acceptance Criteria
- [ ] lifecycle completes
- [ ] artifacts valid

## Next Agent
RepoScout
"""


def fake_reposcout_output() -> str:
    return """# RepoScout Report

## Repository Map
| Path | Purpose |
|---|---|
| agent_runtime/ | Core runtime |

## Relevant Files
- lifecycle_graph.py
- artifact_contract.py

## Next Agent
Coder
"""


def fake_researcher_output() -> str:
    return """# Research Notes

Status: skipped
Reason: Route does not require external research.
"""


def fake_interface_mapper_output() -> str:
    return """# Interface Map

Status: skipped
Reason: No interfaces affected by this task.
"""


def fake_coder_output() -> str:
    return """# Implementation Report

## Backend
Dry-run (fake provider)

## Files Changed
None (dry run)

## Behavior Implemented
Dry-run lifecycle test.

## Next Agent
TesterAuditor
"""


def fake_validation_output() -> str:
    return """# Validation Report

## Static Checks
- YAML parse: ✅ pass
- Python compile: ✅ pass

## Recommendation
READY_FOR_ARCHIVIST
"""


def fake_audit_output() -> str:
    return """# Audit Report

## Diff Summary
No diffs (dry run).

## Scope Compliance
- Edited only approved files: yes

## Final Decision
READY_FOR_ARCHIVIST
"""


def fake_archive_output() -> str:
    return """# Archive Update

## Task Completed
- task_id: dry-run test
- execution_mode: fake_provider

## What Changed
Dry-run lifecycle test completed.

## Backup Status
- GitHub: not pushed
- Local checkpoint: dry-run
"""


def fake_output_for_agent(agent_name: str) -> str:
    """Return deterministic fake output for any agent."""
    outputs = {
        "Supervisor": fake_supervisor_output(),
        "RepoScout": fake_reposcout_output(),
        "Researcher": fake_researcher_output(),
        "InterfaceMapper": fake_interface_mapper_output(),
        "Coder": fake_coder_output(),
        "TesterAuditor": fake_validation_output(),
        "Archivist": fake_archive_output(),
    }
    return outputs.get(agent_name, f"# {agent_name} Report\n\nFake provider output for dry-run.\n")


def generate_sync_report() -> str:
    """Generate a valid dry-run sync report."""
    return """# Sync Report

Status: skipped
Reason: Dry-run mode; commit not required.
"""