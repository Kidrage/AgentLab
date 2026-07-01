# AgentLab v1.0 Stable Internal Closed Loop Acceptance

Status: passed
Date: 2026-07-01

## Scope

v1.0 validates the internal M1-M3 closed loop. M4 commercial/productization
features are explicitly out of scope for this acceptance run.

## Required Evidence

- Operator State uses canonical timeline and cost facade.
- WebUI/TUI mutations use Operator Action runtime.
- External executor launch is blocked by default from operator surfaces.
- Operator action ledger appears in timeline and Operator State.
- Cost facade attributes spend by task, phase, executor/model, and retry.
- Content project promotion requires lineage, state transition, archive receipt, and single current artifact.
- Repository hygiene rejects artificial padding, private paths, compressed files, and forbidden tracked assets.

## Validation Commands

```bash
python -m pytest -q tests/test_v1_internal_closed_loop_guards.py
python -m pytest -q tests/test_m3_1_operator_state_consistency.py tests/test_m3_6_observability_timeline.py tests/test_m3_5_cost_system_v2.py
python -m pytest -q tests/test_m3_2_webui_operator_console.py tests/test_m3_3_tui_daily_driver.py
python -m pytest -q tests/test_content_project_long_chain.py tests/test_project_artifact_steward.py
python -m pytest -q tests/test_repository_text_integrity.py
python -m pytest -q
```

## Result

- Focused v1 guard suite: passed.
- Operator State / Timeline / Cost / WebUI / TUI / content governance / text integrity target suite: 74 passed.
- Full local pytest: 2015 passed, 2 skipped, 11 warnings.
- CI verification: passed on run 28500440976 for commit 95d975d.
