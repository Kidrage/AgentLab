# AgentLab Capability Boundary Report

Generated for the current mainline after the routing, lifecycle, artifact, and
evaluation-harness fixes through commit `0421ce51bafee566f20e09de3deb95398be23658`.

This report separates what is proved by current deterministic evidence from
what remains unproved. It should not be read as a promise about live LLM output
quality unless a live execution test is listed as evidence.

## Evidence Snapshot

| Area | Evidence | Result | Scope |
|---|---|---:|---|
| Full Python test suite | `python -m pytest -q` | `2073 passed, 2 skipped, 11 warnings` | Unit/integration regression coverage |
| GitHub CI | run `28748843693` | `success` | Mainline CI after lifecycle route fix |
| Capability scorecard | `python agent_runtime/evaluation/eval_all.py --root .` | `100%`, `Production-like` | Local deterministic system checks; execute smoke not run |
| Performance eval | `./agentlab.sh performance-eval --project AgentLab --task-id task_capability_boundary_20260706` | `96.5/100`, route `evaluation_task` | Local deterministic routing/config/lifecycle/command/artifact check |
| Narrative eval | `./agentlab.sh narrative-eval run --project Crown_of_Ash --mode mock --chapters 1-3 --timestamp capability_boundary_20260706` | `warn`; L2 sample `pass`; L3 simulation `pass` | Mock longform governance, not live prose quality |

## Coding Capability Boundary

### Guaranteed Now

- Route selection is deterministic for the covered task classes:
  `small_task`, `medium_task`, `interface_sensitive_task`,
  `research_sensitive_task`, `large_or_risky_task`, `evaluation_task`,
  `narrative_light_chapter`, `article_light_draft`, and
  `narrative_heavy_audit`.
- Lifecycle nodes now obey the selected route. If a route does not include
  `TesterAuditor`, `Verifier`, or `Archivist`, validation/audit/verify/archive
  nodes are skipped instead of silently turning a light path into a heavy path.
- Analysis-only evaluation tasks skip `Coder` and route to `evaluation_task`.
- The local deterministic capability suite passes all dimensions when execute
  smoke is skipped.
- Performance scoring now includes artifact completeness. The latest local
  performance evaluation scores `96.5/100`, not `100/100`, because artifact
  pass rate is `0.77`.

### Not Guaranteed Yet

- Live API execution quality is not guaranteed by the current scorecard because
  `Execute Smoke Test` was not run.
- Artifact completeness is not perfect in the current performance eval
  (`17/22`, pass rate `0.77`), even though the overall deterministic score is A.
- The scorecard proves local orchestration health; it does not prove that every
  external model/provider will produce correct patches in a live task.

## Writing Capability Boundary

### Guaranteed Now

- Novel chapter requests such as Crown single-chapter writing route to
  `narrative_light_chapter` by default.
- Article/essay/report requests route to `article_light_draft` unless they are
  explicitly longform fiction work.
- Heavy narrative audit is reserved for audit/check/promotion/quality-dispute
  requests, not default chapter generation.
- The light chapter path requires:
  `fiction_draft.md`, `continuity_ledger.yml`,
  `state_transition_proposal.yml`, and `narrative_delivery_receipt.yml`.
- `story-long-write` is not default-injected; the tracked default skill is
  `narrative-chapter-writer-lite`.
- For `Crown_of_Ash`, fact source health passed: artifact index, fact snapshot,
  bible refs, and outline refs were present.
- The mock longform eval produced 3 candidate chapters with valid delivery
  receipts and no production writes.
- The reset eval did not use deprecated production chapters as continuity
  sources for the candidate baseline.

### Long-Novel Length Boundary

Current verified boundary:

- **3 consecutive candidate chapters** are structurally validated in mock mode.
- **1500 chapters** are only validated as a deterministic scale simulation:
  series arc ledger, chapter state plan, foreshadowing ledger, character arc
  ledger, and timeline/worldline ledger are generated and internally coherent.

Current non-guarantee:

- AgentLab **cannot yet guarantee high-quality live prose for 1500 chapters**.
- AgentLab **cannot yet guarantee high-quality live prose for any exact chapter
  count** from this evidence alone, because the latest acceptance run used mock
  generation, not live Writer/Reviewer model calls.
- The honest live-writing quality guarantee today is therefore: **0 live
  chapters quality-guaranteed by current evidence**. The system can guarantee
  the governance envelope and candidate artifact contract, not the literary
  quality of live generated prose.

## Narrative Risks Found By Evaluation

- `Crown_of_Ash` has 10 existing production manuscript chapters marked as
  deprecated for reset evaluation.
- Historical rebuild paths exist and must remain audit evidence only:
  `archive/legacy_roots/20260630/...`, `runs/task_crown_rebuild_blueprint`,
  and `runs/task_crown_rebuild_ch01`.
- Several historical narrative runs are incomplete under the new contract
  because they lack some of:
  `fiction_draft.md`, `fiction_review.yml`, `continuity_ledger.yml`,
  `state_transition_proposal.yml`, and `narrative_delivery_receipt.yml`.
- `project_brain/revision_log.jsonl` is missing for `Crown_of_Ash`, reported as
  a warning by L0 fact source health.

## Required Next Evidence Before Stronger Claims

To claim real longform writing quality, run and preserve evidence for:

1. Live `narrative-eval` over at least chapters 1-3 with real Writer/Reviewer
   model calls.
2. Heavy audit over the generated chapter batch.
3. Promotion dry run proving candidate facts do not enter production until user
   confirmation.
4. At least one 10-chapter live continuity batch with no blocking continuity
   failures.
5. Human or model-assisted quality review rubric covering prose quality, pacing,
   character state, foreshadowing payoff, and timeline consistency.

Until those pass, the system should claim **strong governance and routing**,
not guaranteed longform literary quality.
