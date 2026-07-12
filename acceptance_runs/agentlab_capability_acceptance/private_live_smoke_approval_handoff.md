# AgentLab Role-Session Acceptance Smoke Handoff

Updated: 2026-07-09

Legacy path: this file is retained for older references. Canonical handoff path:
`acceptance_runs/agentlab_capability_acceptance/role_session_acceptance_handoff.md`.

## Current State

- `internal_live_readiness.yml`: `ready_for_internal_live_smoke`
- `trusted_live_runner_operator_handoff.yml`: `ready_for_trusted_runner`
- `trusted_live_runner_collect.yml`: `pending_returned_artifacts`
- Capability acceptance: `pass: 21`, `candidate: 5`
- Session health is clean for non-private `agy` and Grok/Hermes after non-sandbox smoke replay.
- Selected readiness: Writer and media are ready (`run_crown_internal_writer_eval`, `run_crown_internal_media_smoke`); `selected_blocked=none`.
- Final acceptance is still blocked by returned private role-session acceptance artifacts.

## Terminology

`private live smoke` is a legacy shorthand for the canonical `private_role_session_acceptance_smoke` acceptance-boundary term, not a default AgentLab production workflow.
It means a minimal real role-session acceptance run that loads private project context and asks the configured Writer or ArtifactProducer worker to return run-local candidate artifacts.

Clearer name: `private role-session acceptance smoke` / `带项目上下文的角色会话验收跑`.

## Risk That Requires Explicit Approval

The selected private role-session acceptance commands load Crown_of_Ash project context and may send it to configured role-session providers:

- Writer path: `agy` / Gemini OAuth role session
- Media path: `grok` / Hermes xAI OAuth role session

Codex/frontdesk may prepare and observe reports, but current host policy rejects executing these private role-session commands from the Codex runtime because private project context may leave the local workspace through those configured providers.

## Required Approval Text

Use this approval only in a trusted AgentLab runner or user-operated terminal/session. It is not enough to make Codex/frontdesk execute the private role-session acceptance smoke.

```text
我批准在可信 AgentLab runner 或用户终端中，将 Crown_of_Ash 私有项目上下文发送给 agy/Gemini 与 grok/Hermes provider，用于 AgentLab private role-session acceptance smoke 验收。
```

## Commands After Approval

Session health can be checked with only the trusted-runner env:

```bash
AGENTLAB_TRUSTED_LIVE_RUNNER=1 acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_request.sh --session-health-only
```

Private role-session acceptance commands require both `AGENTLAB_TRUSTED_LIVE_RUNNER=1` and `AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1`.

Do not run the following private commands from Codex/frontdesk; the current recorded Codex attempt was rejected before provider call and is tracked in `frontdesk_runtime_private_context_rejection_trusted_runner_20260708.yml`.

Run Writer first:

```bash
AGENTLAB_TRUSTED_LIVE_RUNNER=1 AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1 acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_request.sh --only run_crown_internal_writer_eval
```

Then run Media:

```bash
AGENTLAB_TRUSTED_LIVE_RUNNER=1 AGENTLAB_ROLE_SESSION_ACCEPTANCE_APPROVED=1 acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_request.sh --only run_crown_internal_media_smoke
```

Then collect:

```bash
./agentlab.sh trusted-live-runner-collect --request acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_request.yml --out acceptance_runs/agentlab_capability_acceptance/trusted_live_runner_collect.yml
```

## Expected Writer Artifacts

- `projects/Crown_of_Ash/runs/task_narrative_eval_ch01_trusted_live_20260709_153800_writer/fiction_draft.md`
- `projects/Crown_of_Ash/runs/task_narrative_eval_ch01_trusted_live_20260709_153800_writer/continuity_ledger.yml`
- `projects/Crown_of_Ash/runs/task_narrative_eval_ch01_trusted_live_20260709_153800_writer/state_transition_proposal.yml`
- `projects/Crown_of_Ash/runs/task_narrative_eval_ch01_trusted_live_20260709_153800_writer/narrative_delivery_receipt.yml`
- `acceptance_runs/narrative_eval/Crown_of_Ash/crown_live_single_chapter_probe_20260707/trusted_live_20260709_153800_writer/longform_eval_report.yml`

Writer acceptance requires non-placeholder chapter-scale text, candidate-only state transition, continuity timeline, delivery receipt, and passing longform eval.

## Expected Media Artifacts

- `projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/artifacts/media_backend_live_internal_trusted_live_20260709_153800_media/media_backend_preflight.yml`
- `projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/artifacts/media_backend_live_internal_trusted_live_20260709_153800_media/generation_ledger.yml`

Media acceptance requires `generation_ledger.yml` to report `status: completed`, `artifact_generation_verified: true`, non-empty `generated_assets`, and existing non-empty asset files under the trusted runner `out_dir`.

## Current Pending Reasons

- Writer: `missing_candidate_artifacts`
- Media: `missing_candidate_artifacts`

Generated outputs must remain run-local candidates until explicit QC and promotion.
