# AgentLab Self-Evolution Control Plane

AgentLab self-evolution is a governed way to improve AgentLab itself. It is not
permission for a worker to edit production configuration, install providers,
or merge its own changes.

## Lifecycle

1. Record a capability-gap observation under a project run.
2. Prove the gap is explicit or repeated across two independent tasks and
   cannot be satisfied by existing roles or routes.
3. Propose a versioned `ComponentManifest`.
4. Materialize bridge files in an isolated Git worktree.
5. Run structural checks, focused tests, the full test suite, and independent
   Verifier review. Structural-only validation is diagnostic and cannot enter
   review-ready state.
6. Prepare a draft pull request. A human merge is the activation decision.
7. Load the active component on the next AgentLab configuration reload.

The verification handoff is intentionally split:

```text
self-evolution validate --execute-commands
self-evolution verifier-request
run-agent Verifier --execute --force
self-evolution verifier-collect
self-evolution validate --verifier-receipt <receipt>
self-evolution review-ready
```

Attaching the Verifier receipt does not rerun or rewrite the validation report.
The receipt must match that immutable report and the final registered Verifier
model-execution attempt. The runtime also binds the source role session, the
self-evolution request, the exact sealed CLI task packet, its outbound-context
manifest, the model receipt and chain, and the returned report by hash. A report
passes only with the required component, manifest, role-session, empty-blocker,
and explicit `PASS` markers; prose length alone is never acceptance. Validation
records the exact policy command list, one indexed receipt per command, and a
hash-bound full output log under the evolution run. Verifier preparation and
review reconstruct that list from the current policy and reject missing,
reordered, failed, or altered command evidence. Those logs are also declared
Verifier inputs. The outbound source inventory must bind the exact prepared
Verifier packet used for provider execution, so temporarily changing the packet
and restoring it after execution cannot pass collection.
Validation commands may use
`{validation_artifact_dir}` for disposable doctor output; they may not leave
source, test, or unrelated untracked changes in the candidate worktree.
`runtime-doctor` remains informative for pre-existing warnings, but its report
is parsed and candidate-scoped secret, symlink, or gitignore regressions fail the
self-evolution validation.

## v1 Boundary

`agent_role` is the only fully materialized component kind in v1. Skill, route,
runtime-adapter, RAG, repository-management, and other core-module proposals can
use the evidence and review lifecycle, but stop before materialization until a
specific materializer is registered and reviewed.

New roles bind only to workers and model routes already active in
`config/runtime_registry.yml`. They declare capability demand, not provider or
model identifiers. AgentLab records why every route was accepted or rejected.
The v1 execution adapter supports exactly one flat
`runs/task_xxxx/<default_report>` output per component-managed role, matching the
generic `run-agent` materializer instead of advertising artifacts it cannot
produce. Run-control filenames such as `workflow_plan.yml`, `state.yml`, and
`execution_log.yml` are reserved. Immediately before each CLI dispatch,
AgentLab resolves every declared component input, fails on a missing or symlinked
input, creates a bound run-local role session for the selected worker, and adds
the inputs and session to the sealed context. Runtime usage records the session
hash. The generic result adapter accepts exactly one matching `AGENTLAB_EDIT`
block and atomically writes its contents; the CLI report envelope is never used
as the declared artifact.
The compiler emits `workflow_binding.yml`: a role already named by a reviewed
route is normally selectable; every other merged role is available only through
an AgentLab-created bound role session until a separate route-pack change is reviewed.
The compiler never inserts an arbitrary role into default mission routing.

`NarrativePlanner` is the first migrated component-managed role. Heavy narrative
audit runs `Reviewer -> Scribe -> NarrativePlanner -> Verifier`; the planner owns
only `revision_or_rewrite_proposal.yml`, while Verifier retains final acceptance
checking and writes `verification_report.md`.

Every observation, proposed manifest, ledger, validation report, and Verifier
receipt stays under a declared `projects/<Project>/runs/<task_id>/` boundary.
A proposal may read immutable gap observations from other task runs to establish
recurrence, while its own manifest, ledger, validation, and review evidence stay
in one run. A Verifier receipt must identify a returned independent role session
and bind the validation report, generated compatibility manifest, model execution
receipt, final model execution chain attempt, and verification report by hash.
Review preparation revalidates the exact managed worktree, branch, base commit,
manifest, and generated bundle before staging only that component's allowlisted
paths. Symlinks are rejected, compatibility-manifest hashes are rechecked, and
both the staged Git blobs and committed Git tree must equal the validated regular
files.

Active component roles are loaded fail-closed. The runtime validates the regular
manifest and generated directory, compatibility identity, exact generated-file
inventory, every declared hash, and the absence of symlinks before replacing a
legacy adapter. A damaged replacement is removed from the effective role and
worker-binding views; it never silently falls back to the legacy declaration.

`self-evolution rollback` is also review-only. It accepts only a review-ready,
component-scoped commit and emits a hash-bound binary reverse patch plus explicit
`git apply --check` and apply commands. It does not execute the patch, mutate the
main branch, or merge a revert.

RAG remains an evidence-retrieval layer by default and cannot become a fact
authority implicitly. A future repository manager receives no destructive Git,
remote-write, or auto-merge permission by default.
