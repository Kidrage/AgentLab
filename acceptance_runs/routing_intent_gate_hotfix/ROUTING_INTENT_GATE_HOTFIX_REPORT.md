# Routing Intent & Gate Consistency — Hotfix Report

**Date**: 2026-06-26
**Branch**: `main`
**Prior hotfix**: `7bebdbf` (fix(cli): normalize Claude Code binary resolution)

---

## Root Cause

`agent_runtime/task_router.py:recommend_route()` checked `wants_evaluation`
**before** checking for implementation intent.  The evaluation hints list
includes words like "evaluate", "assessment", "validate", "benchmark" —
these also appear in implementation prompts.  When matched, the router
selected the `evaluation_task` route which **skips Coder entirely**,
even when the prompt contained strong implementation signals like
"implement", "fix", "create files", "add tests".

Secondary issues:
1. No implementation intent detection existed at all.
2. `brain_governor.py:222` silently skipped the `implementation_report`
   artifact check when Coder was absent, masking the contradiction.
3. No route-gate consistency validation ran before task packet finalization.

---

## Changes

### 1. `agent_runtime/task_router.py`

- Added `IMPLEMENTATION_HINTS` (40+ English + Chinese keywords)
- Added `EXPLICIT_ANALYSIS_ONLY_HINTS` (15+ explicit override signals)
- Added `IMPLEMENTATION_EXECUTORS` frozenset
- Added `_detect_implementation_intent()` function
- Added `_has_implementation_executor()` helper
- Updated `recommend_route()`:
  - Implementation intent checked FIRST (before evaluation)
  - Implementation + evaluation → implementation wins
  - Explicit analysis-only → strips Coder from route
  - Safety net: injects Coder if route somehow lacks an implementation executor
  - Updated rationale messages distinguish implementation vs analysis-only

### 2. `agent_runtime/route_gate_consistency.py` (NEW)

- `RouteGateConsistencyError` dataclass
- `validate_route_gate_consistency()` — checks 4 rules
- `format_consistency_errors()` — human-readable output
- Covers: missing executor, artifact ownership, analysis-only gates, no-executor blocking

### 3. `agent_runtime/brain_governor.py`

- Line 222: Instead of silently skipping `implementation_report` when Coder
  is absent, now checks whether the task route rationale indicates
  implementation intent.  If it does, flags the gap as a WARN with a
  recommendation to add an implementation executor.

### 4. `tests/test_routing_gate_consistency.py` (NEW)

23 tests in 6 classes covering implementation detection, route recommendation,
gate consistency, multimodal preservation, and config alignment.

### 5. `scripts/check_routing_gate_consistency.py` (NEW)

Deterministic acceptance script with 7 fixtures (5 route + 2 contradiction).

### 6. `docs/ROUTING_INTENT_AND_GATE_CONSISTENCY.md` (NEW)

Full documentation of intent classification, route selection, and consistency invariant.

---

## Test Results

```
tests/test_routing_gate_consistency.py ......... 23 passed in 0.15s
```

## Acceptance Script

```
python scripts/check_routing_gate_consistency.py
✅ All route–gate consistency checks passed.
```

## Key Behavior Changes

| Scenario | Before | After |
|----------|--------|-------|
| "Implement patch, add tests" | → evaluation_task, Coder skipped | → implementation route, Coder included |
| "请实现补丁，修改仓库" | → evaluation_task, Coder skipped | → implementation route, Coder included |
| "Analyze only, don't implement" | → small_task, Coder included | → analysis-only, Coder removed |
| "Evaluate AND implement fixes" | → evaluation_task, Coder skipped | → implementation route, Coder included |
| Route skips Coder + gate requires impl_report | → silently masked by brain_governor | → flagged as WARN with recommendation |

## Remaining Limitations

1. **Keyword-based classification is inherently fragile**: Edge cases in
   prompt wording may still misclassify. A future improvement could use the
   Supervisor LLM to classify intent.

2. **Config-level `analysis_only: true` on `evaluation_task` route** in
   `routing_rules.yml` is still present. The code-level override handles this
   at runtime, but a future config cleanup could remove the flag.

3. **Chinese keyword coverage**: The current list covers common patterns but
   may miss some colloquial expressions. Expand as discovered.

4. **No real agent execution tested**: All tests are shape/contract validations.
   Integration testing requires a full AgentLab run with an implementation
   prompt.
