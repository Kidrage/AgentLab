# Phase 2R Node D — live Writer adapter acceptance

## Verdict

Node D is accepted. Implementation, provider-free Crown Ch25–Ch27 preflight,
final independent Standards/Spec review and the full repository regression all
pass. Earlier review rounds rejected real authority gaps; every reported seam
now has a deterministic replay and a verified correction. A bounded Gate 1 live
Writer call is now permitted under the existing candidate-only authorization.

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
