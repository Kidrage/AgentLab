from __future__ import annotations

from datetime import datetime, timezone
import gzip
import os
from pathlib import Path

from agent_runtime.task_runtime_v2.retention import AttemptLogRetention


def test_attempt_logs_are_hash_gated_and_retained_as_gzip_after_seven_days(
    tmp_path: Path,
) -> None:
    log_root = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-one"
        / "attempt_logs"
        / "attempt-001"
    )
    log_root.mkdir(parents=True)
    old_log = log_root / "worker.stderr.log"
    recent_log = log_root / "worker.stdout.log"
    permanent_receipt = log_root / "process_receipt.yml"
    old_log.write_text("old diagnostic\n", encoding="utf-8")
    recent_log.write_text("recent diagnostic\n", encoding="utf-8")
    permanent_receipt.write_text("status: succeeded\n", encoding="utf-8")
    os.utime(old_log, (1_700_000_000, 1_700_000_000))
    os.utime(recent_log, (1_700_777_000, 1_700_777_000))
    os.utime(permanent_receipt, (1_700_000_000, 1_700_000_000))
    retention = AttemptLogRetention(tmp_path, project="Demo")
    now = datetime.fromtimestamp(1_700_800_000, tz=timezone.utc)

    plan = retention.plan(now=now, older_than_days=7)
    receipt = retention.apply(
        expected_plan_hash=plan["plan_hash"], now=now, older_than_days=7
    )

    compressed = old_log.with_name(old_log.name + ".gz")
    assert not old_log.exists()
    assert gzip.decompress(compressed.read_bytes()) == b"old diagnostic\n"
    assert recent_log.read_text(encoding="utf-8") == "recent diagnostic\n"
    assert permanent_receipt.read_text(encoding="utf-8") == "status: succeeded\n"
    assert receipt["compressed_count"] == 1
    assert receipt["deleted_without_replacement"] == []
    assert Path(receipt["receipt_path"]).is_file()
