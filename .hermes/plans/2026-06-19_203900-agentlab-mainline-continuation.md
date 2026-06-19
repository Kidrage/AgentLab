# AgentLab Mainline Continuation Plan

> **For Hermes:** Planning only. Do not edit runtime code until the user approves execution. Follow systematic-debugging before fixing failures.

**Goal:** Continue the AgentLab S0-S12 mainline repair from the current repository state, preserving the completed S0-S8 baseline and advancing next through S9 Capability Fabric.

**Architecture:** Treat the handoff file as the roadmap, but verify the repo state before each stage. The current main branch already contains S6, S7, and S8 reports and tests; next execution should first re-accept the S0-S8 baseline, then implement S9 as a deterministic, mock-first capability registry and artifact perception contract layer.

**Tech Stack:** Python, Typer CLI in `agent_runtime/run_task.py`, YAML config under `config/`, pytest, compileall, deterministic file artifacts under `acceptance_runs/`.

---

## Current Status Snapshot

Observed from `/Users/saintpeter/Desktop/AgentLab`:

- Branch: `main`
- Latest commit: `120fa0d feat(s7-s8): add project brain executor loop`
- Recent commits show S6 and S7-S8 have landed:
  - `120fa0d feat(s7-s8): add project brain executor loop`
  - `ff99994 fix(text-integrity): harden S6 raw guards`
  - `3279976 fix(ci): stabilize recovery brain checks`
  - `1fe8478 feat(s6): add recovery brain planning`
- Untracked files:
  - `CLAUDE.md`
  - `Root AgentLab Mainline Repair Handoff.md`
- Acceptance reports present:
  - `acceptance_runs/s6_recovery_brain/S6_RECOVERY_BRAIN_REPORT.md` — PASS
  - `acceptance_runs/s7_long_project_orchestrator/S7_LONG_PROJECT_ORCHESTRATOR_REPORT.md` — PASS
  - `acceptance_runs/s8_executor_connector/S8_EXECUTOR_CONNECTOR_REPORT.md` — PASS
- Existing S7/S8 docs:
  - `docs/S7_LONG_PROJECT_ORCHESTRATOR.md`
  - `docs/S8_EXECUTOR_CONNECTOR_LOOP.md`
- Existing S7/S8 tests:
  - `tests/test_s7_long_project_orchestrator.py`
  - `tests/test_s8_executor_connector.py`
- No current `agent_runtime/capabilities/` implementation found during search.

Conclusion: the repo appears to be past S8 on the mainline. The next planned stage is S9, but first re-run baseline validation to confirm current checkout health.

---

## Stage 0: Re-accept Current Baseline Before New Work

**Objective:** Verify S0-S8 are still healthy before implementing S9.

**Files:**
- Read only initially.
- Possible report update later: `acceptance_runs/s9_capability_fabric/S9_CAPABILITY_FABRIC_REPORT.md`

**Steps:**

1. Record baseline:
   - `git status --short`
   - `git branch --show-current`
   - `git log --oneline -5`

2. Run required baseline checks:
   - `python -m compileall agent_runtime agentlab_app.py`
   - `python -m pytest -q`
   - `./agentlab.sh --help`
   - `./agentlab.sh run-pipeline --help`

3. If full pytest is too slow or fails broadly:
   - Run focused S6-S8 tests first:
     - `python -m pytest -q tests/test_s6_recovery_brain.py tests/test_s7_long_project_orchestrator.py tests/test_s8_executor_connector.py`
   - Then investigate failing tests with systematic-debugging before any fix.

4. Run text integrity guard:
   - `python scripts/audit_text_integrity.py --fail-on-suspicious`

**Expected result:** Baseline passes, or failures are isolated before S9 work begins.

---

## Stage 1: Implement S9 Capability Fabric Core Models

**Objective:** Add deterministic capability contract models without executing external tools.

**Files:**
- Create: `agent_runtime/capabilities/__init__.py`
- Create: `agent_runtime/capabilities/capability_contract.py`
- Create: `agent_runtime/capabilities/registry.py`
- Create: `agent_runtime/capabilities/permission_gate.py`
- Create: `agent_runtime/capabilities/result_verifier.py`
- Create: `tests/test_s9_capability_fabric.py`

**Implementation shape:**

- Define capability records with:
  - `capability_id`
  - `display_name`
  - `description`
  - `modality`
  - `backend_type`
  - `status`: `available | missing_backend | disabled | requires_approval`
  - `permissions`
  - `risk_level`
  - `evidence_required`

- Add built-in IDs from handoff:
  - `filesystem_read`
  - `filesystem_write`
  - `shell_command`
  - `git_ops`
  - `web_search`
  - `browser_fetch`
  - `pdf_read`
  - `docx_read`
  - `spreadsheet_read`
  - `image_understanding`
  - `ocr`
  - `video_understanding`
  - `audio_transcription`
  - `audio_analysis`
  - `database_query`
  - `github_ops`
  - `ide_handoff`
  - `openclaw_notify`

**Tests:**

- Registry loads deterministically.
- Duplicate `capability_id` fails.
- Missing backend creates a gap card rather than execution.
- Disabled capability cannot be selected.
- High-risk capability requires approval.

---

## Stage 2: Add S9 Config Files

**Objective:** Make capability fabric policy-driven.

**Files:**
- Create: `config/capability_registry.yml`
- Create: `config/capability_permission_policy.yml`
- Create: `config/media_artifact_policy.yml`
- Modify tests to load these configs.

**Rules:**

- Default to mock-first.
- No automatic model install.
- No automatic MCP execution.
- External/network/shell capabilities require explicit approval.
- Artifact outputs must be written to explicit output paths.

**Tests:**

- YAML parses.
- Required capability IDs exist.
- Private paths/secrets are not present.
- Policy blocks unsafe defaults.

---

## Stage 3: Add Media / Document Artifact Contracts

**Objective:** Add structured output contracts for vision, audio, and documents.

**Files:**
- Create: `agent_runtime/capabilities/media_artifact.py`
- Create: `agent_runtime/capabilities/vision_contract.py`
- Create: `agent_runtime/capabilities/audio_contract.py`
- Create: `agent_runtime/capabilities/document_contract.py`
- Extend: `tests/test_s9_capability_fabric.py`

**Contracts:**

- `vision_result.yml` fields:
  - `input_artifact`
  - `modality`
  - `observations`
  - `summary`
  - `evidence_artifacts`
  - `model_or_tool`
  - `confidence`
  - `risk`

- `audio_result.yml` fields:
  - `input_artifact`
  - `duration`
  - `observations`
  - `transcript`
  - `features`
  - `summary`
  - `evidence_artifacts`
  - `model_or_tool`
  - `confidence`
  - `risk`

- `document_result.yml` fields:
  - `input_artifact`
  - `pages`
  - `extracted_text`
  - `tables`
  - `figures`
  - `citations`
  - `confidence`

**Tests:**

- Contracts serialize to YAML deterministically.
- Missing confidence fails validation.
- Missing evidence artifacts fail validation when policy requires evidence.
- Human review risk is emitted for multimodal outputs.

---

## Stage 4: Add Capability Gap Decision Cards

**Objective:** If a mission/workflow requires a missing capability, AgentLab writes a decision card instead of executing or fabricating results.

**Files:**
- Create: `agent_runtime/capabilities/gap_card.py` if needed, or keep in `registry.py` if small.
- Create/extend tests.

**Artifact:**

- `capability_gap_decision_card.yml` with:
  - `required_capability`
  - `reason`
  - `available_backends`
  - `missing_backend_reason`
  - `approval_options`
  - `recommended_next_action`
  - `risk_notes`

**Tests:**

- `image_understanding` with no backend writes gap card.
- `audio_transcription` with no backend writes gap card.
- No fabricated `vision_result`/`audio_result` is produced when backend is missing.

---

## Stage 5: Add S9 CLI Commands

**Objective:** Expose S9 via deterministic CLI.

**Files:**
- Modify: `agent_runtime/run_task.py`
- Possibly create: `agent_runtime/capabilities/cli.py`
- Tests: `tests/test_s9_capability_fabric.py` or `tests/test_s9_capability_cli.py`

**Commands:**

- `./agentlab.sh capability-list`
- `./agentlab.sh capability-check --capability image_understanding --out /tmp/capability_demo`
- `./agentlab.sh capability-gap --capability image_understanding --out /tmp/capability_demo`
- Optional mock-only commands:
  - `./agentlab.sh vision-contract --input artifact.png --out /tmp/vision_demo --mock`
  - `./agentlab.sh audio-contract --input artifact.wav --out /tmp/audio_demo --mock`
  - `./agentlab.sh document-contract --input artifact.pdf --out /tmp/document_demo --mock`

**Tests:**

- CLI help works.
- `capability-list` prints known capabilities without secrets.
- `capability-gap` writes deterministic YAML.
- Mock media contracts write structured artifacts only when `--mock` is explicit.

---

## Stage 6: Integrate With Existing Mission/Workflow Signals Lightly

**Objective:** Connect S9 to existing mission/workflow artifacts without broad refactors.

**Files:**
- Search current mission/workflow modules first.
- Likely modify one narrow integration point if present.
- Add tests for capability need detection if existing S1/S2 contracts expose `required_capabilities`.

**Rule:** Do not redesign S1/S2. S9 should consume existing `required_capabilities` if present; otherwise provide standalone CLI.

**Tests:**

- Given a workflow/mission containing `required_capabilities: [image_understanding]`, S9 emits a gap card if no active backend exists.
- Given an available mock backend, S9 emits a structured result contract with evidence metadata.

---

## Stage 7: Documentation and Acceptance Report

**Objective:** Complete S9 handoff artifacts.

**Files:**
- Create: `docs/S9_CAPABILITY_FABRIC.md`
- Create: `docs/S9_VISION_AUDIO_DOCUMENT_CONTRACTS.md`
- Create: `acceptance_runs/s9_capability_fabric/S9_CAPABILITY_FABRIC_REPORT.md`

**Report format:** Follow handoff standard:

- Verdict
- Baseline
- Summary
- Changed Files
- New Runtime Modules
- New Configs
- New CLI
- Artifacts Produced
- Tests Added
- Tests Run
- Safety Notes
- Known Limitations
- Next Recommended Stage

---

## Validation Commands for S9 Completion

Run focused first:

```bash
python -m compileall agent_runtime/capabilities agent_runtime/run_task.py tests/test_s9_capability_fabric.py
python -m pytest -q tests/test_s9_capability_fabric.py
./agentlab.sh capability-list --help
./agentlab.sh capability-gap --help
python scripts/audit_text_integrity.py --fail-on-suspicious
```

Then baseline:

```bash
python -m compileall agent_runtime agentlab_app.py
python -m pytest -q
./agentlab.sh --help
./agentlab.sh run-pipeline --help
```

Final repo checks:

```bash
git status --short
git log --oneline -5
git ls-remote --heads origin main
```

---

## Risks / Constraints

- Do not execute external MCP, models, shell tools, or media processors in S9.
- Keep S9 deterministic and mock-first.
- Avoid heavy dependencies.
- Do not touch user-local private files, `.venv`, caches, or generated temporary runs except explicit acceptance artifacts.
- Preserve current S6-S8 behavior; S9 should be additive.
- If full pytest fails before S9 changes, fix baseline first; do not layer S9 on a broken baseline.

---

## Next Stage After S9

After S9 passes, continue to S10 Generalization Eval Suite + CI Gates.
S10 should prove cross-domain behavior using offline fixtures and should not depend on real web, real vision/audio backends, or external agents.
