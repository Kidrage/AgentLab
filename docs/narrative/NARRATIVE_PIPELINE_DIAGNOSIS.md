# Narrative pipeline diagnosis (Phase 0 approval report)

## Verdict

AgentLab cannot currently be described as able to run all novel generation and
audit work stably in the background. The real Crown 200-chapter job is `blocked`
after 11 attempts, remains on batch 1 (Ch01-Ch10), has no sealed batches, and has
no completion receipt.

The architectural product boundary is sound: AgentLab should be the producer,
editorial/governance system, version controller, and scheduler; a suitable model
should remain the prose Writer. The current implementation makes that governance
too expensive and, more importantly, cannot yet prove that a revision improves
the reading experience.

Phase 0 establishes a reproducible measurement seam and evidence baseline. It
does not repair routing, seal logic, quality gates, UI, promotion, or the queue.
The planned live Ch25-Ch27 sample is blocked pending explicit permission to send
Crown manuscript/canon context to the configured external Writer provider.

## Baseline

The frozen baseline contains SHA256-bound runtime configuration, canon/outline
authority, Ch01-Ch03 historical candidates, Ch21-Ch30 candidates, Ch26/Ch30 user
negative labels, pre/post repair audits, and a content-free live-trial receipt.
No user-approved positive sample exists:

```yaml
positive_calibration_status: missing_user_samples
```

Headline measurements:

- Ch01-Ch30 generation: 50 provider calls, 11,638.927 provider seconds,
  4,772,583 all-model tokens, $26.903531 in receipts, and 2,829,440 outbound
  packet bytes.
- Only 12 of those 50 calls appear as paid calls in the historical cost ledgers;
  the ledger shows at least $4.798659.
- Writer source reuse reaches 69.81% duplicated bytes across Ch01-Ch30.
- Ch21-Ch30 post-repair heavy audit: 646.967 seconds wall time, 612.465 provider
  seconds, four calls, 324,983 all-model tokens, at least $2.067835, and 36.45%
  duplicated source bytes.
- That post-repair audit still contains five blocking fiction findings and five
  rewrite proposals.
- Ch26 consumed two Writer calls, 146,728 all-model tokens, and $0.841700; it
  remains a user-reported negative sample.
- The generic context budget claimed 42 tokens for a heavy-audit run whose
  Reviewer packet was 345,971 bytes and whose receipt reported 87,637 input
  tokens.

Detailed measurements and their confidence labels are in
`NARRATIVE_EFFICIENCY_BASELINE.md` and
`acceptance_runs/narrative_efficiency/baseline_metrics.json`.

## Root Causes

### 1. Durable semantic identity is missing at the generic boundary

Evidence: the complete audit-only replay is classified as `rewrite` because the
text mentions a rewrite proposal. The classifier gives rewrite evidence priority
over the explicit audit action.

The current Crown controller does persist an `action` field and does not perform
this second classification in its inspected attempt path. The deeper problem is
that the job schema is Crown-specific and has no durable `job_kind`, `run_mode`,
candidate-set identity, or audit lineage. A generic queue built on the current
entry classifier would therefore inherit the ambiguity.

Recommended Phase 1 seam: compile natural language exactly once into an immutable
semantic envelope, then let the narrative adapter and state machine consume only
that envelope.

### 2. Seal authority is narrower than audit authority

Evidence: `_heavy_audit` derives `requires_rewrite` only from
`continuity_failure_report.yml`. `_successful_transition` seals whenever that
boolean is false. The deterministic replay with `fiction_review=blocked` and
continuity pass seals the batch.

Recommended Phase 1 seam: one fail-closed seal decision object must bind required
audit artifact hashes and veto on fiction, continuity, literary quality, missing
files, stale hashes, missing independent re-audit, expired attempt, or stale user
approval. An audit that finds issues should still complete successfully as an
audit; it should not authorize sealing.

### 3. Invocation evidence is fragmented and lossy

Evidence: execution logs preserve provider processes, model receipts preserve
usage, cost ledgers contain only selected successful pipeline results, and role
context manifests can be overwritten by retries. Across Ch01-Ch30, 38 of 50
provider processes have no corresponding paid cost-ledger row. Ch26 records two
calls but one ledger entry. The pre-repair 10-chapter audit records a repeated
Scribe process that is absent from the cost ledger.

Phase 0 mitigation: an opt-in, append-only, content-free
`narrative_invocations.jsonl` snapshot is now written immediately after every
narrative provider return and before materialization. This is observation, not a
state-machine repair.

### 4. Context governance measures the wrong payload and does not reuse a bundle

Evidence: the generic context pack estimates 42 tokens while the final Reviewer
packet has 345,971 bytes. Historical Writer source duplication rises from 49.39%
for three chapters to 69.81% for 30. The isolated Ch25 attempt includes a
114,889-byte candidate fact ledger inside a 207,910-byte packet, showing that the
state representation itself can become a dominant context source.

Recommended Phase 2 seam: construct one immutable context bundle with a canon
snapshot hash and chapter window; record shared versus role-specific files;
measure the final sealed payload; reference or cache shared material by hash; and
bound candidate fact history to relevant state rather than replaying an
ever-growing ledger.

### 5. Revision intent is not compiled into an executable quality contract

Evidence: current audit artifacts can locate many continuity issues, but there is
no mandatory six-dimensional literary scorecard, scene-level preservation/change
contract, or anonymous old/new preference. Ch26 was retried on a stronger model
and still failed the user's quality calibration. The post-repair 10-chapter audit
still has five blocking findings.

Recommended Phase 3 seam: evidence-backed scene revision contracts, local rewrite
by default, deterministic regression checks, independent re-audit, and anonymous
A/B selection. Two failed revisions must end in `decision_required`, not a third
automatic rewrite.

### 6. Heavy audit is not risk-tiered enough

Evidence: a 10-chapter heavy audit invokes Supervisor, Reviewer, Scribe, and
Verifier. Supervisor alone consumes 312.610 provider seconds in the post-repair
run. Reviewer/Scribe/Verifier all use the same DeepSeek Pro model family, so the
extra roles add procedural separation but limited model independence.

Recommended Phase 2 seam: deterministic prechecks first, one literary Judge for
ordinary chapters, a second independent Judge only for risk triggers, and
arbitration only on conflict. Successful nodes and unchanged chapter windows must
be reusable.

### 7. Literary calibration has no positive boundary

Evidence: Ch26 and Ch30 are user negatives; there are no user-approved positives
and no 10-pair human blind-review result. Without positive samples, threshold
tuning can improve recall by simply rejecting everything.

Recommended action before any quality claim: obtain and freeze three to five
user-positive chapters, then run at least 10 anonymous old/new comparisons.

## Confirmed Issues

| Issue | Code path | Test/replay path | Runtime evidence | Impact outside narrative | Rollback |
|---|---|---|---|---|---|
| Audit text misclassified as rewrite | `agent_runtime/narrative_intent.py` | `baseline_metrics.json / known_issue_checks` | observed `kind=rewrite` | none measured; classifier has article/chapter consumers | no fix made in Phase 0 |
| Fiction blocking can seal | `agent_runtime/background_job_worker.py`, `background_job_controller.py` | deterministic known-issue replay | observed `batch_sealed`, one sealed batch | controller is Crown-specific today | no fix made in Phase 0 |
| Paid attempts missing from ledger | `agent_runner` → pipeline cost append boundary | frozen historical replay | Ch01-Ch30: 50 processes vs 12 ledger calls | telemetry is narrative-route opt-in only | unset diagnostics env/remove hook |
| Context budget misses final payload | context profiling versus outbound manifest | frozen heavy-audit replay | 42 estimated tokens vs 87,637 reported Reviewer input | generic context pack remains unchanged | remove diagnostic comparison only |
| Revision uplift unprovable | audit/rewrite artifact contract | Ch26 and Ch21-Ch30 replay | negative Ch26; five post-repair blocking findings | none | no quality code changed |
| 200-chapter job incomplete | Crown background state | persisted job state | blocked, batch 1, 0 sealed, 11 attempts, no completion receipt | none | no job state changed |

## Rejected Hypotheses

- **Every chapter runs five agents:** rejected. Historical chapter production is
  primarily Writer execution; the four-role chain is the heavy-audit batch path.
- **Every audit role reads the full manuscript:** rejected. Reviewer reads the
  bounded prose; Scribe and Verifier read derived reports/contracts.
- **Every node failure restarts the whole pipeline:** rejected. Node-level retry
  exists; the pre-repair audit repeated Scribe without repeating Reviewer.
- **The current Crown attempt controller reclassifies generated prose:** rejected
  for the inspected path. `action_request.yml` carries a structured `action`.
  The public classifier and missing generic semantic schema remain defects.
- **There is no provider cache:** rejected. Receipts contain cache-read usage,
  although it is not tied to a reusable context hash.
- **The model alone explains slowness:** unsupported. Provider time is large, but
  observed elapsed spans also contain retry/idle gaps and context construction;
  historical queue and I/O fields are missing.
- **A stronger Writer model guarantees better prose:** rejected as a general
  remedy by the user-negative Ch26 Pro result.
- **Over-precise scene contracts are the proven cause of boredom:** not proven.
  It remains a plausible hypothesis requiring an A/B design with frozen positives.
- **Current automatic repair improved quality:** not established. There is no
  hash-bound blind preference or accepted score delta.

## Changed Modules

Phase 0 changes are deliberately narrow:

- `agent_runtime/narrative/diagnostics/telemetry.py`: opt-in append-only invocation
  events, locked writes, receipt/context snapshot, no prose.
- `agent_runtime/narrative/diagnostics/baseline.py`: evidence-labelled historical
  collector and deterministic defect replay.
- `agent_runtime/agent_runner.py`: thin calls immediately after CLI/API provider
  returns; no routing, model selection, patching, or state transition changed.
- `tests/test_narrative_efficiency.py`: consolidated domain tests for opt-in
  behavior, failed-call preservation, ledger gaps, and context duplication.
- `acceptance_runs/narrative_efficiency/`: frozen manifest, generated baseline,
  and content-free live-probe evidence.
- `docs/narrative/`: diagnosis, call graph, and baseline reports.

No Crown rule was added to a generic queue/core module. No Production artifact was
modified. No central module received a new state-machine branch.

## State-Machine Changes

None in Phase 0. The two red state/identity replays intentionally remain red and
are recorded as `confirmed_defect`. Repairing them before user approval would
violate the diagnostic-first gate.

## Efficiency Before/After

There is no optimization “after” result yet. Phase 0 adds measurement only.
Normal runs have zero new behavior unless `AGENTLAB_NARRATIVE_DIAGNOSTICS=1`.
When enabled, each provider return performs one locked JSONL append and `fsync`;
its local overhead has not yet been benchmarked separately and must be included
in the live three-chapter comparison.

The pre/post historical heavy-audit comparison shows an existing 32.3% wall-time
reduction and 15.9% known-cost reduction, but it predates this repair branch and
does not validate a new optimization.

## Quality Before/After

No defensible before/after literary result exists. Current evidence says only:

- Ch26 and Ch30 are user negatives;
- Ch26's stronger-model revision did not satisfy that calibration;
- Ch21-Ch30 post-repair still has five blocking findings;
- positive samples, independent blind A/B, and human preference are missing.

No claim that prose intelligence, tension, curiosity, or non-formulaic progression
improved is authorized.

## Test Results

Phase 0 domain tests cover:

- telemetry disabled means no file or behavior change;
- a failed paid/attempted call is persisted before materialization and excludes
  draft prose;
- cost-ledger omissions remain visible against execution logs/receipts;
- repeated context bytes are computed by SHA256 across roles and runs;
- existing CLI dispatch tests remain compatible with the thin hook.

Validation result on this branch:

- focused narrative/runtime regression set: 137 passed in 6.60 seconds;
- full repository suite: 2,739 passed, 2 skipped, 11 existing missing-directory
  warnings in 219.67 seconds;
- `ruff check`: pass;
- `git diff --check`: pass.

Passing tests are not presented as proof of literary quality.

## Live Trial Results

The isolated Ch25-Ch27 trial attempted Ch25 and stopped:

- sandbox result: `network_required` after 173.956 seconds;
- observed tokens/cost: 0 / $0;
- packet: 207,910 bytes across 21 sources;
- external execution request: denied pending explicit disclosure approval;
- completed chapters: 0 of 3;
- source and isolated Production tree hashes match before/after;
- real Production remained unchanged.

This is a valid blocked trial, not a pass. The preserved evidence contains hashes
and metrics, not prose.

## Remaining Risks

- Entry identity and false-green seal defects remain active until Phase 1.
- Historical cost/token accounting cannot be reconstructed perfectly where
  receipts are missing or models are unpriced.
- The live baseline is incomplete until explicit external-context approval.
- No positive literary calibration exists.
- Context telemetry is opt-in; old runs remain partially observed.
- The current background controller is still Crown-specific and should not be
  renamed into a generic queue.
- No lease/fencing, promotion, Candidate Set, UI, export, or 200-chapter soak work
  has been accepted in this phase.

## Rollback Instructions

Before commit, rollback is removal of the new narrative diagnostics package,
tests/docs/acceptance artifacts, plus the two recorder calls in
`agent_runtime/agent_runner.py`. After commit, revert the single Phase 0 commit.
No data migration or Production restoration is required because Production was
never written.

Operationally, leaving the code installed but unsetting
`AGENTLAB_NARRATIVE_DIAGNOSTICS` disables all telemetry writes.

## Next Recommended Gate

1. Explicitly approve or decline sending Ch25-Ch27 and their necessary canon
   context to the configured external Writer provider. If approved, rerun the
   isolated sample and append actual cost/time/context evidence.
2. Freeze three to five user-positive chapters; do not claim literary improvement
   before they exist.
3. Approve Phase 1 only: structured job identity plus fail-closed seal tests and a
   two-rewrite terminal state. Keep this separate from efficiency and quality work.
4. Re-run Gate 1 on three chapters before any 10-chapter batch; do not start the
   200-chapter soak.
