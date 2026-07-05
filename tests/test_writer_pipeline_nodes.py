"""Creative writing route lifecycle node coverage."""

import sys
from pathlib import Path

AGENT_RUNTIME = Path(__file__).resolve().parents[1] / "agent_runtime"
if str(AGENT_RUNTIME) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNTIME))

from agent_runtime.lifecycle_graph import NODE_REQUIRED_OUTPUTS, create_lifecycle
from agent_runtime.pipeline_runner import NODE_TO_AGENT, NODE_TO_REPORT


def test_fiction_route_enables_writer_reviewer_scribe_nodes(tmp_path: Path):
    workflow = {
        "route": {
            "agents": ["Supervisor", "Writer", "Reviewer", "Scribe", "Verifier", "Archivist"],
        },
    }

    lifecycle = create_lifecycle(tmp_path, workflow)

    assert lifecycle["nodes"]["WRITER_DRAFT"]["status"] == "waiting"
    assert lifecycle["nodes"]["FICTION_REVIEW"]["status"] == "waiting"
    assert lifecycle["nodes"]["SCRIBE_LEDGER"]["status"] == "waiting"
    assert NODE_REQUIRED_OUTPUTS["WRITER_DRAFT"] == ["fiction_draft.md"]
    assert NODE_REQUIRED_OUTPUTS["FICTION_REVIEW"] == ["fiction_review.yml"]
    assert NODE_REQUIRED_OUTPUTS["SCRIBE_LEDGER"] == ["continuity_ledger.yml"]
    assert NODE_TO_AGENT["WRITER_DRAFT"] == "Writer"
    assert NODE_TO_AGENT["FICTION_REVIEW"] == "Reviewer"
    assert NODE_TO_AGENT["SCRIBE_LEDGER"] == "Scribe"
    assert NODE_TO_REPORT["WRITER_DRAFT"] == "fiction_draft.md"
    assert NODE_TO_REPORT["FICTION_REVIEW"] == "fiction_review.yml"
    assert NODE_TO_REPORT["SCRIBE_LEDGER"] == "continuity_ledger.yml"


def test_nonfiction_route_skips_writer_reviewer_scribe_nodes(tmp_path: Path):
    workflow = {
        "route": {
            "agents": ["Supervisor", "RepoScout", "Coder", "TesterAuditor", "Archivist"],
        },
    }

    lifecycle = create_lifecycle(tmp_path, workflow)

    assert lifecycle["nodes"]["WRITER_DRAFT"]["status"] == "skipped"
    assert lifecycle["nodes"]["WRITER_DRAFT"]["skip_reason"] == "Route does not include Writer"
    assert lifecycle["nodes"]["FICTION_REVIEW"]["status"] == "skipped"
    assert lifecycle["nodes"]["FICTION_REVIEW"]["skip_reason"] == "Route does not include Reviewer"
    assert lifecycle["nodes"]["SCRIBE_LEDGER"]["status"] == "skipped"
    assert lifecycle["nodes"]["SCRIBE_LEDGER"]["skip_reason"] == "Route does not include Scribe"
