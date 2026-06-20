# AgentLab M1-8 Recovery / Replanning v2 Report

## Verdict
PASS

## Baseline
- **branch**: `main`
- **before commit**: `5b249f7 feat: implement M1-6 Document/Code/Media Ingestion v1` (plus M1-7 local changes)
- **after commit**: Local modifications for M1-8
- **remote**: `https://github.com/Kidrage/AgentLab.git`
- **CI**: passing locally

## Summary
Implement M1-8 Recovery / Replanning v2. Phase recovery has been upgraded from task-level retries into project-phase level replanning. When a phase fails or requires changes, the recovery engine analyzes the failure reason based on the Failure Taxonomy, decides the recommended next action from the Next Actions catalog, counts and caps retries, and writes a detailed replan plan while updating the project brain's next actions.

## Changed Files
- `agent_runtime/run_task.py`: Added the `phase-replan` CLI command.

## New Runtime Modules
- `agent_runtime/recovery/phase_recovery.py`: Main entry point coordinating phase-level recovery.
- `agent_runtime/recovery/replanning.py`: Decider logic mapping failures to next actions, managing retry counts, writing replan plans, and updating project brain states.

## New Configs
- None.

## New CLI
- `./agentlab.sh phase-replan --project <name> --phase <phase_id> --acceptance <file> --out <dir>`: CLI command for executing replanning.

## Artifacts Produced
- `replan_plan.yml`: Structured replanning report.
- `replan_plan.md`: Human-readable Markdown summary.
- `capability_gap_decision_card.yml`: Written when a capability gap is detected.

## Tests Added
- `tests/test_m1_replanning.py`: Validates taxonomy mapping, capping retries, budget violations, and scope drift decisions.
- `tests/test_m1_phase_recovery.py`: Validates CLI execution and end-to-end recovery coordinators.
- `tests/test_m1_fake_evidence_detector.py`: Unit tests for fake evidence and ungrounded claim checks.

## Tests Run
```text
tests/test_m1_phase_acceptance.py ....                                   [ 26%]
tests/test_m1_phase_recovery.py ..                                       [ 40%]
tests/test_m1_replanning.py .....                                        [ 73%]
tests/test_m1_fake_evidence_detector.py ....                             [100%]

============================== 15 passed in 0.78s ==============================
```

## Safety Notes
All checks run locally in the standard sandbox context. No external code is run. Repeated retry loops are strictly capped.

## Known Limitations
None.

## Next Recommended Stage
- M1-9 Context Compression v1.
