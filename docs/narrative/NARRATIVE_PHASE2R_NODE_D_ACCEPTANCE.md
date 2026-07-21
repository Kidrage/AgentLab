# Phase 2R Node D — live Writer adapter acceptance

## Verdict

Node D is accepted. Implementation, provider-free Crown Ch25–Ch27 preflight,
final independent Standards/Spec review and the full repository regression all
pass. Earlier review rounds rejected real authority gaps; every reported seam
now has a deterministic replay and a verified correction. A bounded Gate 1 live
Writer call is now permitted under the existing candidate-only authorization.

Post-acceptance operator-path inspection found that `run-agent Writer --execute`
still selected the legacy four-output materializer after a successful v2 call,
even though `run-pipeline` selected the v2 prose-only contract. A shared
run-local identity dispatcher now serves both entry points. Its focused
regression passes. Standards review then reproduced a success-to-blocked legacy
retry that retained the prior four candidate artifacts; the dispatcher now
removes those explicit run-local outputs on a blocked retry while preserving the
failure contract. Spec review additionally reproduced an empty completed retry
that removed the outputs but left the prior passing contract; every blocked
legacy retry now atomically persists a blocked contract with zero materialized
outputs and an explicit issue. The focused set is 133/0. Final correction review
and the repository rerun passed: both Standards and Spec returned PASS, and the
authoritative full repository run completed with 3,004 passed, 2 skipped and 11
warnings in 232.09 seconds. The direct live command is now permitted once its
exact frozen workflow plan has been persisted and revalidated.

The provider-free preflight previously kept that exact plan only in memory. A
new integration replay proved this would let `run-agent` rebuild a generic plan.
After a session passes twice with byte-stable packet and context hashes, the
preflight now atomically writes `workflow_plan.yml` and records its path and
SHA256 in the metrics receipt. Crown Ch25–Ch27 were recompiled 3/3 with zero
provider calls and an unchanged Production digest; all three persisted plans
load as `narrative_generation_v2`, include only Writer and require the recorded
external-context approval. Review and regression for this final preparation
unit are pending before any model call.

The first review rejected publishing a chapter plan before the rest of the
batch had passed and overwriting a deterministic run slot without ownership.
The corrected preflight binds every plan to the frozen spec hash, rejects a
different existing request or plan before writing, validates the complete batch
and final provider/Production invariants, then publishes all plans with rollback
on a partial write failure. Replaying the identical spec is idempotent. Red
tests cover a later-chapter failure, a foreign occupied slot and an injected
second-plan publish failure; focused verification is 137/0. Crown Ch25–Ch27 was
regenerated twice with identical metrics and plan hashes, provider calls zero
and Production unchanged. Final correction review and the full regression are
still required before execution.

Standards then identified a remaining check-to-replace race. Publication no
longer calls an unconditional atomic replace: it writes and fsyncs a complete
sibling temporary file, then uses an atomic hard-link create-if-absent. A
concurrent different owner is preserved and blocks the preflight; identical
content is an idempotent no-op. After publishing the batch, every request/plan
pair is read and matched again. A concurrent-slot replay now passes and the
focused total is 138/0. The real Crown replay retains the exact preceding hashes,
zero provider calls and unchanged Production. Final rereview remains pending.

A further Standards replay exposed parent-directory swaps, rollback identity and
process-crash durability. Each validated run directory is now opened with
`O_NOFOLLOW`, matched by captured device/inode, and protected by a run-slot lock;
all temp creation, hard-link publication, rollback and directory fsync use that
held dirfd. Rollback removes only the inode created by this preflight. Because a
three-directory commit cannot be made atomically, plans become executable only
after one final batch activation receipt records every request/plan hash.
`load_or_build_plan` validates that receipt before accepting a marked v2 plan;
a crash before activation therefore leaves partial files inert. Parent-swap and
pre-activation crash replays pass, focused verification is 140/0, and real Crown
plans now load through the active receipt with provider calls zero and Production
unchanged. Final rereview and full regression remain pending.

Standards next found that pipeline execution bypassed the activation check, the
direct loader validated then reread the plan, and reversed chapter order could
deadlock run-slot locks. Direct operator and pipeline paths now share one deep
loader that returns the exact plan mapping decoded from the bytes already
validated against single-read request and activation bytes. Root-relative reads
walk every component through `dirfd` plus `O_NOFOLLOW`; marked plans are not
reread by the direct loader. Locks are acquired in canonical sorted path order.
Tests prove missing activation blocks both entry points, replacement after the
sealed read cannot alter the returned plan, and reversed input still locks a→b.
Focused verification is 141/0; both real Crown loaders resolve the same v2
Writer-only plans with provider calls zero and Production unchanged. Final
rereview and the full regression remain pending.

The next review showed that pipeline execution validated the stored plan but
then rebuilt a generic one, PREPARE could rewrite the activated file, and direct
execution could reread a replaced request. Pipeline model execution now builds
its `WorkflowPlan` from the sealed mapping; activated PREPARE skips artifact,
mission and skill mutation. The validated request content travels in a
runtime-only excluded schema field, so Writer compiles from the exact approved
bytes and the final on-disk request-hash check blocks any later replacement.
Lifecycle files never persist that sealed content. Tests cover the actual
pipeline plan selection, PREPARE immutability, plan replacement after read and
request replacement after read. Focused verification remains 141/0, and real
Crown direct/pipeline plans both hold the v2 route plus sealed approved request.
No provider or Production write occurred; final rereview/full regression remain.

The correction-five rereview found two remaining operator overrides. Direct
execution with a supplied budget rebuilt the plan, while deletion of the request
after sealed loading returned `None` and could re-enter the legacy Writer path.
Activated plans now preserve an identical budget and reject request, budget, or
backend changes. A sealed plan with a missing request returns an explicit blocked
session after removing any prior passing session receipt, prose and Writer
execution receipt and atomically replacing the v2 output contract with a blocked
contract. The same cleanup now applies to every safely bound v2 preflight block;
unactivated legacy plans keep their prior `None` behavior. Persisted plans are
also forbidden from carrying the runtime-only sealed request field.
Final request and context-manifest rehashing now converts concurrent deletion or
read failure into an explicit blocked v2 contract instead of propagating an
exception before cleanup. A public `run_agent_model` replay deletes the request
during packet compilation and proves provider zero, stale-success cleanup and
the exact missing-during-compile issue.
The public-path replays fail on the prior behavior and pass after the minimal
corrections. Focused narrative/output/run-next verification remains 141/0; Ruff
and Python compilation pass. Correction nine then passed final independent
Standards and Spec review. The authoritative repository regression completed
with 3,012 passed, 2 skipped and 11 warnings in 240.28 seconds. Provider calls
and Production writes remain zero. Commit/CI are the final prerequisites before
execution.

The registered Writer path now activates v2 only when its run directory contains
`narrative_v2_writer_request.yml` with structured narrative-generation identity,
candidate-only flags and a mandatory external-context-approval policy. Natural
language cannot activate the adapter. A missing request leaves the legacy Writer
path unchanged, including for malformed or code-task plan labels.

## Runtime closure

The narrative-only adapter validates project, task, chapter, source paths and
hashes before model selection. The request is bound to the frozen Writer input
manifest. Canon and the CreativeBrief are not merely project-local: the latter
is deterministically re-derived from the manifest's hash-bound source plan and
chapter selector, so an alternate Ch25 brief cannot substitute for the accepted
one. It compiles one sealed packet from the accepted CreativeBrief/context path
plus the Node C memory snapshot. Supplementary
context is limited to the project's fact snapshot and Production bible; the one
private role source must be the canonical Writer template. Cross-project,
future-chapter, stale, symlinked, wrong-route or non-approved inputs block before
provider execution.

Node C memory is not accepted from completeness flags alone. Every category
item is revalidated against its source hash, locator, exact excerpt,
category-specific relevance, source chapter and five-chapter window. The public
validator also binds the snapshot itself to the requested project's Candidate
tree and rejects symlink relocation. All request and memory evidence hashes are
checked against the accepted snapshot's declared hashes after packet compilation
to close the observed compile-time mutation window.

Both CLI and direct-API outbound gates read
`execution_policy.external_context_approval_required`. The live packet asks for
one `fiction_draft.md` edit envelope. AgentLab—not the Writer—materializes prose,
computes its hash and issues `writer_execution_receipt.yml`. A result is
materialized only when its status is `completed` and the current request hash
matches the passing v2 session receipt. Any failed/stale, non-prose, duplicate,
blank or wrong-target result leaves no prose or success receipt.

## Provider-free Crown replay

Inputs and exact hashes are frozen in
`acceptance_runs/narrative_efficiency/phase2r_node_d/preflight_inputs.yml`; the
reproducible result is
`acceptance_runs/narrative_efficiency/phase2r_node_d/preflight_metrics.json`.

- Chapters: Ch25, Ch26, Ch27
- Sessions compiled: 3/3
- Literary-memory occurrences: exactly one per Writer packet
- Provider calls: 0
- Production digest before/after: identical
- Median packet bytes: 68,051, 32.10% below the frozen legacy median
- Median loaded context bytes: 62,312, 44.77% below the frozen legacy median
- Positive calibration: `missing_user_samples`

Every chapter is compiled twice inside the replay; both packet and context
manifest hashes match, and instability now fails the preflight. This proves the
live input contract and efficiency target, not literary output equivalence or
Gate 1.

## Tests and scope

- Focused efficiency plus v2 delivery: 126 passed.
- Extended narrative domain (`tests/test_narrative_*.py`): 224 passed.
- Adversarial replay covers structured identity, route separation,
  missing request approval, cross-project and manifest-undeclared future canon,
  future predecessor/supplemental prose, incomplete literary evidence,
  compile-time source mutation, unsafe preflight identifiers, symlinked run
  directories/memory, stale memory/session binding and pre-provider blocking.
- Ruff and whitespace diff checks: pass.
- Full repository: 3,000 passed, 2 skipped, 11 warnings in 234.66 seconds.
- First independent Standards review: rejected; five reported seams corrected.
- First independent Spec review: rejected; four reported evidence gaps corrected.
- First correction re-review: rejected; CreativeBrief derivation, declared
  memory-dependency hashes and public snapshot/project binding corrected.
- Final independent Standards correction re-review: pass.
- Final independent Spec correction re-review: pass.

New policy lives in `agent_runtime/narrative/production/`. Central runtime edits
are thin adapters: combined net growth across `agent_runner.py`,
`cli_executor.py` and `pipeline_runner.py` is 82 lines, below the 150-line stage
limit. No Crown rule is present in those modules.

Node C commit `c8ac0a1` is independently CI-green in GitHub Actions run
`29803770261`.

## Quality boundary

No prose was generated in Node D preflight. No literary score, revision uplift,
human preference or Gate 1 acceptance is claimed. Node D review/full regression
now permit live Ch25–Ch27 generation, which must remain candidate-only.

## Rollback

Revert the future Node D commit. Remove the derived candidate context bundles
and run-local preflight requests if desired; Production requires no restoration.
