from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.background_job_controller import (
    consume_process_receipt,
    create_crown_delivery_job,
    load_job_state,
    schedule_next_attempt,
    write_process_receipt,
)
from narrative_test_authority import install_narrative_test_authority


def test_receipt_completed_after_attempt_deadline_cannot_advance_job(
    tmp_path: Path,
) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)
    create_crown_delivery_job(
        tmp_path,
        project="Crown_of_Ash",
        job_id="candidate-v1",
        eval_id="candidate-v1",
        start_chapter=1,
        end_chapter=3,
        writer_worker="fake-writer",
        **install_narrative_test_authority(tmp_path, writer="fake-writer"),
        chapter_state_plan="runs/shared/chapter_state_plan.yml",
        attempt_lease_seconds=60,
        now="2026-07-19T10:00:00+00:00",
    )
    attempt = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="candidate-v1",
        now="2026-07-19T10:00:00+00:00",
    )
    write_process_receipt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="candidate-v1",
        attempt_id=attempt["attempt_id"],
        idempotency_key=attempt["idempotency_key"],
        lease_token=attempt["lease_token"],
        outcome="success",
        exit_code=0,
        result={"status": "pass"},
        now="2026-07-19T10:01:01+00:00",
    )

    with pytest.raises(ValueError, match="lease expired"):
        consume_process_receipt(
            tmp_path,
            project="Crown_of_Ash",
            job_id="candidate-v1",
            now="2026-07-19T10:01:01+00:00",
        )

    state = load_job_state(tmp_path, "Crown_of_Ash", "candidate-v1")
    assert state["status"] == "preflight"
    assert state["active_attempt"]["attempt_id"] == attempt["attempt_id"]
