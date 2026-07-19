# AgentLab Narrative Production Repair Plan v2

Status: highest-priority narrative workstream  
Execution posture: staged, AgentLab-supervised, candidate-only  
Source diagnosis: `/Users/saintpeter/Downloads/7.20修改方案.md`  
Machine contract: `docs/narrative/NARRATIVE_PRODUCTION_REPAIR_EXECUTION.yml`

## 1. Domain boundary

This plan strengthens only the narrative-production domain.

Code tasks and narrative tasks remain separate governance routes:

- Code work uses repository scope, patch proposals, compile/test evidence, code
  review, and merge/delivery receipts.
- Narrative work uses canon snapshots, creative briefs, prose candidates,
  literary review, continuity projection, Candidate Sets, human acceptance, and
  promotion receipts.
- Both domains may reuse generic governance primitives: structured job identity,
  immutable inputs, context hashes, leases, retries, fencing, evidence receipts,
  approvals, atomic promotion, recovery, and rollback.
- The generic job engine must never import prose scoring, canon, scene, chapter,
  compiler, test-runner, or code-review semantics.
- Narrative policies live below `agent_runtime/narrative/`; code policies keep
  their existing route. This work must not change code-task routing behavior.

AgentLab is the narrative producer/editorial operating system. It does not
become the author. Writer models create prose; AgentLab compiles bounded context,
routes editorial work, records evidence, and governs versions.

## 2. Corrected baseline and frozen decisions

Confirmed defects:

- Writer is a distinct role, but one call still emits prose, continuity YAML,
  state proposals, and a self-authored delivery receipt.
- Every chapter is still forced to advance plot, character, relationship/world,
  foreshadowing, emotion, and time state.
- Literary scorecard and local revision primitives exist, but default chapter
  generation does not use a live editorial/rewrite closure.
- The background revision adapter deliberately returns `decision_required` and
  does not execute provider-backed rewrites.
- Long-term candidate memory preserves fact events better than voice, life
  texture, emotional debts, scene functions, or reader knowledge.
- Exact paragraph duplication is detected; structural, rhetorical, and semantic
  fatigue are not.
- Generic Candidate Set creation does not require an exact expected chapter
  sequence.

Corrections to the source diagnosis:

- Ch23 prose exists. Its heading is malformed as `章二十三`, so the assembly
  failure is `malformed_chapter_heading:23`, not a missing manuscript chapter.
- Current final Writer routing is Claude shell plus DeepSeek V4 Pro, not the old
  Agy/Gemini Writer route.
- The proposed 75% system / 25% model attribution is unmeasured and must not be
  reported as fact.
- Not every textual symptom worsens monotonically. Confirmed long-range signals
  include falling life-detail density and rising pseudo-precision.

Calibration v2 is immutable once written:

- Positive, trait-tagged: Ch01, Ch04, Ch09, Ch17.
- Negative: Ch26.
- Conflict holdout: Ch30; it tests thematic strength versus reading fatigue and
  is excluded from binary positive/negative thresholds.
- Structural-fatigue probes: Ch05, Ch07, Ch14.
- The current Ch01-Ch30 manuscript and source runs remain a read-only baseline.

All implementation and live trials remain:

```yaml
candidate_only: true
production_modified: false
automatic_rewrite_limit: 2
```

## 3. Target production architecture

The ordinary chapter path is:

```text
BriefCompiler
-> ContextCompiler
-> prose-only Writer
-> deterministic checks and pattern signals
-> Reader/Editor according to the active review policy
-> optional scene rewrite, independent re-audit, and blind A/B
-> StateProjector
-> Continuity Verifier
-> Candidate Set
```

Story architecture is compiled at volume/arc cadence. Scene planning is invoked
only for high-risk chapters or an insufficient brief; neither becomes a fixed
per-chapter meeting.

Public narrative interfaces:

```text
ChapterEngine.run(ChapterRequest) -> ChapterOutcome
CandidateGovernance.freeze/promote(...)
JobEngine.submit/claim/complete/recover(...)  # Phase 5 only
```

New v2 artifacts:

- `chapter_creative_brief.yml`: one primary function, at most one secondary
  function, POV, opposing wants, turn, cost, reader question, must-preserve,
  creative freedom, recent patterns to avoid, risk signals, and source hashes.
- `fiction_draft.md`: the Writer's only content output.
- `narrative_state_delta.yml`: hard facts and soft literary observations,
  separated and bound to prose hash plus exact evidence locations.
- `narrative_memory_snapshot.yml`: voice, knowledge gaps, emotional debts, life
  details, recent scene functions, rhetoric use, motifs, and unresolved reader
  questions, rebuilt from append-only deltas.
- `chapter_production_manifest.yml`: hashes and receipts for brief, context,
  prose, model/cost, review, rewrite, state projection, and selection.
- `candidate_set_manifest.yml` v2: exact expected chapter IDs, titles, order,
  evidence, version, and hashes.
- `assembly_manifest.yml`: exact chapter-to-format mapping and release hashes.

New writes use `chapter_delivery_compliance_matrix.yml`,
`chapter_literary_quality_matrix.yml`, and
`longform_governance_capacity_simulation.yml`. Historical names remain read-only
compatibility inputs.

## 4. Staged implementation

### Phase 0R - trusted re-baseline

Scope:

- Freeze source and bundle hashes for the current 30 chapters.
- Create calibration manifest v2 with the decisions above.
- Add a deterministic assembly replay that counts 30 chapters but reports the
  malformed Ch23 heading.
- Measure model/process/orchestration/queue time, tokens, retries, role file
  loads, duplicated context, and usable-candidate yield.
- Update diagnosis, call graph, efficiency baseline, and root handoff.

No production refactor, UI, release export, provider prose generation, or
Production write is allowed.

Acceptance:

- Baseline and hashes are recomputable.
- Existing immutable calibration evidence is not overwritten.
- The malformed-heading replay is red before implementation.
- Narrative/code governance boundaries are documented and tested.

### Phase 1R - prose-only Writer and creative brief

Scope:

- Add a deep `narrative/production` module; central runtime files receive only
  thin adapters.
- Convert legacy chapter state plans into v2 creative briefs before Writer input.
- Remove the all-dimensions-every-chapter requirement from the v2 path.
- Make Writer return prose only. AgentLab owns execution and delivery receipts.
- Run StateProjector after prose selection; retrying it may not rerun Writer.
- Verify state deltas independently against prose.

Acceptance:

- Writer non-prose content output is zero.
- Static, life, relationship, consequence, and atmosphere chapters validate.
- A StateProjector or Verifier failure replays no successful upstream node.
- Legacy v1 runs remain readable.

### Phase 2R - context, literary memory, and efficiency

Scope:

- ContextCompiler always includes the current brief, canon snapshot, immediate
  predecessor prose, and necessary hard state.
- It selects only relevant voice examples, emotional debts, life-detail anchors,
  recent scene signatures, and open reader questions.
- Shared content is built and hashed once; roles append narrow private slices.
- Add advisory pattern signals for syntax/rhetoric, opening/ending templates,
  report language, explanation density, character n-gram similarity, scene
  functions, ability sequences, and decision patterns.
- Pattern signals trigger review or risk escalation; they cannot claim literary
  pass or promotion.

Acceptance targets:

- First-pass ordinary Gate 1 chapter: no more than three model calls (Writer,
  Editor, StateProjector).
- Stable unsampled ordinary chapter: no more than two model calls.
- Writer non-prose tokens fall at least 50% and ordinary input context median at
  least 25% against the quality-equivalent baseline.
- Shared file reload duplication and upstream replay on node failure are zero.

### Phase 3R - editorial and verified revision uplift

Scope:

- Retain the six core quality dimensions and veto rules.
- Add voice differentiation, dialogue naturalness, rhetorical fatigue,
  explanation density, life texture, mystery branching, and continue-reading
  intent.
- Compile evidence-bound findings into scene-level revision contracts.
- Prefer local scene rewrite; permit at most two attempts.
- Run deterministic checks, independent re-audit, and anonymous A/B before any
  candidate replacement.
- If there is no approved higher-quality Writer route, a second failed attempt
  becomes `decision_required`, never a silent downgrade to WriterFlash.

Gate 1 model control:

- Writer remains DeepSeek V4 Pro so the system change is isolated.
- Primary narrative Editor uses a registered Qwen 3.7 Max route.
- StateProjector uses the narrow Qwen 3.6 Flash/Scribe route.
- A different-model second Judge is used only for high-risk/conflict cases after
  its Reviewer contract and probe pass.

Review frequency:

- Gate 1 through the complete 30-chapter validation: one Editor per chapter.
- After a stable 30-chapter curve: all high-risk chapters plus one ordinary
  chapter in five during production.
- Candidate Set seal still requires a current literary receipt for every chapter.

### Phase 4R - exact Candidate Sets, assembly, and promotion

Scope:

- Candidate Set v2 declares exact expected chapter IDs; actual IDs must match.
- Freeze, seal, and promotion all validate order, title, prose hash, audit hash,
  approval hash, and evidence completeness.
- Generic assembly moves out of the Crown worker; Crown remains an adapter.
- Any prose change makes dependent audits stale.
- Promotion remains atomic and requires a current hash-bound user receipt.

Acceptance:

- Missing, duplicate, malformed, reordered, title-mismatched, stale, or
  unapproved chapters fail closed.
- Ch23 produces the correct malformed-heading finding before title repair.
- Every failed or interrupted promotion leaves Production unchanged.

### Phase 5 - background core, workbench, and release

This phase starts only after the earlier live gates pass.

- Extract a domain-neutral JobEngine with structured identity, queue, lease,
  fencing, deadlines, node-local retry, recovery, idempotent seal, and receipts.
- Narrative semantics stay in a narrative adapter; code-task semantics remain in
  the code route.
- Workbench reads only formal indexes/manifests/receipts.
- Export an immutable Markdown/TXT/DOCX/EPUB package with contents, bible and
  outline, editorial report, audit archive, approvals, promotion receipt,
  changelog, and SHA256 manifest. PDF is deferred.

## 5. Tests and live gates

Tests stay consolidated in the existing narrative domain files. Add one combined
Candidate/assembly domain file only if existing cases cannot be cleanly grouped.
Do not make external model fixed scores into unit assertions.

Mandatory replays cover prose-only Writer, static briefs, node-local retry,
context reuse, advisory-only pattern signals, quality vetoes, Ch23 heading,
complete Candidate Sets, stale evidence, atomic promotion, and the separation of
code and narrative routes.

Live rollout:

1. Gate 1A uses only the already authorized Crown Ch25-Ch27 context through a
   trusted role-session. An environment denial remains
   `blocked_external_execution_policy`; it must not be bypassed.
2. Gate 1B creates ten anonymized whole-chapter A/B pairs for Ch05, Ch07, Ch13,
   Ch14, Ch15, Ch16, Ch20, Ch25, Ch26, and Ch27. Sending the first seven chapters
   externally requires a new explicit approval. At least seven of ten must favor
   the new pipeline with no new blocking.
3. Gate 2 repairs Ch01-10, Ch11-20, and Ch21-30 as three independent batches,
   exercising restart, quota, capacity wait, expired leases, delayed workers,
   incremental re-audit, and the two-rewrite stop.
4. A candidate-only Ch31-50 degradation trial requires separate approval.
5. A 200-chapter audit soak is allowed only when a complete 200-chapter Candidate
   Set already exists. This plan never authorizes unattended generation to fill it.

## 6. AgentLab self-repair supervision

AgentLab may execute this plan one phase at a time because it can compile phase
plans, create Coder task packets, invoke registered role workers, collect changed
files and tests, perform evidence checks, and replan failures.

It is not authorized to auto-close external execution phases. The supervision
contract is therefore:

- AgentLab owns task identity, phase planning, dispatch, receipts, state, and
  recovery.
- The registered Coder owns implementation; TesterAuditor and Verifier own
  validation.
- Codex acts only as supervisor: inspect the planned scope before dispatch,
  verify actual diff/evidence after return, approve or reject phase acceptance,
  and intervene only on blocking, scope drift, unsafe mutation, repeated failure,
  or ambiguous product decisions.
- Only one phase is active at a time. The next phase cannot start before the
  current phase has its tests, acceptance report, handoff progress row, and
  rollback instructions.
- Every phase starts and ends with an append-only row in `PROJECT_HANDOFF.md`.
- No AgentLab self-repair task may edit Production, Crown candidate prose, or the
  generic code-task route unless that exact file is named in the active phase.

## 7. Stop and rollback rules

Stop and request a decision when:

- narrative changes cannot be isolated from code-task behavior;
- Production content must change;
- a safety test or schema would need weakening;
- a central module would gain over 150 net lines instead of using a deep module;
- baseline evidence cannot be reproduced;
- the same revision fails twice;
- external context or a new provider/model requires approval;
- someone is about to claim quality uplift without the ten-pair human result.

Each phase is a separate commit. New code dual-reads v1/v2 and writes only v2;
historical runs are not migrated. Rollback reverts only the phase commit and
selects the prior pipeline/policy version. No push to main and no Production
promotion occur without explicit user approval.
