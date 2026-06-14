# P2-G Autonomous Task: Run Commands

## Commands Executed

All commands are deterministic, local-only, dry-run.

### 1. P2 Closure Runner

```bash
python scripts/p2_closure_check.py \
  --task-id task_p2g_smoke \
  --delivery-path tests/fixtures/p2g_smoke_task/fake_repo \
  --output-dir acceptance_runs/p2g_autonomous_task_smoke \
  --provider-id mock_executor \
  --executor mock \
  --dry-run
```

**Result:** Verdict `rejected` — missing `external_handoff.md`, `skill_usage_ledger.yml`, and required report sections.

### 2. P2 Capability Map

```bash
python -c "from agent_runtime.p2_closure.capability_map import scan_p2_capabilities; import yaml; print(yaml.dump(scan_p2_capabilities()))"
```

**Result:** All 7 P2 modules detected as implemented with callable entrypoints.

## Verification Commands

```bash
python scripts/audit_text_integrity.py --fail-on-suspicious  # PASS
python -m pytest -q                                          # 625 passed, 2 skipped
./agentlab.sh --help                                         # OK
./agentlab.sh p2-closure --help                              # OK
```

## Safety Evidence

- No external scripts executed: true
- No network calls made: true
- No secrets exposed: true
- No production config modified: true
