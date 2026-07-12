from __future__ import annotations

from agent_runtime.audit_helpers import trusted_collect_strict_pass


def _strict_status() -> dict:
    return {
        "status": "pass",
        "items": [
            {
                "id": "run_crown_internal_writer_eval",
                "status": "pass",
                "returned_candidate_artifacts_accepted": True,
            },
            {
                "id": "run_crown_internal_media_smoke",
                "status": "pass",
                "returned_candidate_artifacts_accepted": True,
            },
        ],
    }


def _strict_collect() -> dict:
    return {
        "status": "pass",
        "pending_items": [],
        "acceptance_blockers": [],
        "returned_candidate_artifacts_accepted_count": 2,
        "secret_values_rendered": False,
    }


def test_trusted_collect_strict_pass_accepts_complete_returned_artifacts() -> None:
    assert trusted_collect_strict_pass(_strict_status(), _strict_collect()) is True


def test_trusted_collect_strict_pass_rejects_partial_or_unsafe_pass_reports() -> None:
    status = _strict_status()
    status["items"][1]["returned_candidate_artifacts_accepted"] = False
    assert trusted_collect_strict_pass(status, _strict_collect()) is False

    collect = _strict_collect()
    collect.pop("returned_candidate_artifacts_accepted_count")
    assert trusted_collect_strict_pass(_strict_status(), collect) is False

    collect = _strict_collect()
    collect["secret_values_rendered"] = True
    assert trusted_collect_strict_pass(_strict_status(), collect) is False
