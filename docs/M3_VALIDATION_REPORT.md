# M3 Project Agent Validation Report

Date: 2026-07-24

## Decision

M3 is eligible for `main` only after the integration PR CI is green.

The validation used two new projects and did not migrate or mutate Crown of Ash.

## Merge gate

- Integration branch: `codex/m3-main-validation`
- Integration commit: `c88ecd4`
- Narrative specialist commit: `4eb6682`
- Recovery hardening and executable collaboration: `1a0d7f0`
- Pull request: `#12`
- Focused pre-merge compatibility suite: `131 passed`
- Initial merged full suite: `3310 passed, 20 skipped`
- Post-validation full suite before final hardening: `3314 passed, 20 skipped`
- Final full suite: `3318 passed, 20 skipped`
- Integration push and pull-request CI through recovery commit: passed

The focused suite covered Project Agents, Canonical Project Truth, Runtime v2,
Background Job Controller, Pipeline execution modes, pause semantics, and
legacy resume behavior.

## Cross-domain project

Project: `M3_Code_Validation`

Factory result:

- Architecture Agent
- Coder Agent
- Test Agent
- Security Agent
- Reviewer Agent

Validated behavior:

- The accepted API payload limit has one current canonical value.
- Earlier values are immutable history, not competing current files.
- Architecture Agent can write `architecture.*` and is blocked from
  `tests.*`.
- Architecture and Coder private memory use different physical stores.
- Coder pause and resume created manifest revisions 2 and 3.
- Rollback created a new canonical snapshot without rewinding history.
- Repeating the same rollback returned the same receipt.
- Rollback restored old content while preserving the current Coder lifecycle
  and authority manifest. General rollback cannot reactivate or broaden an
  Agent.
- The final truth audit passed.

Current snapshot at validation time:
`9fdfe29d0caf04d48ad18335ce7c2163a102f65abcbf876468b713c8be18292b`

## Narrative project

Project: `CrimsonMoon_Uncrowned_Pilot`

Title: `绛月无冕`

Factory and dynamic lifecycle result:

- World Agent
- Character Agent
- Timeline Agent
- Plot Agent
- Foreshadow Agent
- Mystery Keeper
- Style Guardian
- Writer Agent
- Checker Agent
- Reviewer Agent

The prompt-driven Factory now adds Mystery Keeper and Style Guardian when a
narrative request explicitly asks for mystery/suspense or style/adult sensory
aesthetics. The collaboration DAG places both specialists before Writer.
Checker remains after Writer, and Reviewer remains responsible for overall
quality after Checker.

The approved collaboration DAG is executable infrastructure, not only a plan:
the scheduler materializes every expert step as a dependency-linked Runtime v2
WorkItem in one atomic event, bound to the current snapshot, manifest revision,
and effective contract hash. A conflicting WorkItem ID leaves the ledger
unchanged. Factory roles map Writer, Coder, Verifier, and Reviewer duties to
their actual Runtime roles. Agent `model_profile` replacement changes the
subsequent configured model tier.

Validated behavior:

- All named characters are explicitly adults aged 21 or above.
- Adult intimacy requires consent and a reversible choice.
- Female portrayal has a canonical style rule requiring distinct agency and
  character-specific beauty.
- Manicure, pedicure, elegant feet/footwear, jewelry, fabric, and bearing are
  explicit visual motifs.
- Mystery Keeper cannot write manuscript scope.
- World and Writer private memory use different physical stores.
- Style Guardian pause/resume advanced its manifest to revision 3.
- The truth audit passed across 16 snapshots and 22 content objects.

The accepted three-chapter manuscript is the single current resource
`manuscript.pilot`. Domain acceptance is the single current resource
`acceptance.pilot`.

Current snapshot at validation time:
`aa5c39b605e8321d5cab7ae42b856778975f48e7447af3b11f6859c138e774cc`

## Artifact modification rule

The project uses these authority rules:

1. `project_truth.yml` is the only current-state pointer.
2. A semantic key has exactly one current resource or fact revision.
3. Updates append immutable history and atomically replace the pointer.
4. History is evidence, not a competing source of truth.
5. Human-readable output uses one in-place current projection.
6. A projection must bind its canonical snapshot, resource revision, and
   content hashes.
7. Changes update canonical truth first, then replace the projection in place.
8. Names such as `latest`, `final_v2`, `new_final`, and parallel copies are not
   authority.

The Pilot projection is:

`projects/CrimsonMoon_Uncrowned_Pilot/production/current/PILOT_CURRENT.md`

Its `CANONICAL_BINDING.yml` binds:

- canonical snapshot
- resource revision
- canonical content SHA-256
- projected file SHA-256

## Isolation and migration

- Crown of Ash remains unmigrated.
- No Crown truth pointer, Agent manifest, project file, or production artifact
  was changed by this validation.
- The validation projects live in a dedicated integration worktree and are
  excluded from the source commit.
- Full source/runtime physical separation remains the M3.1 follow-up; this
  report does not claim that repository-wide path decoupling is complete.
- M3's `workspace.isolation: required` gate provides the current logical,
  symlink-safe boundary and governed-write enforcement.

## Integration scope

The Project Agent execution path intentionally builds on Runtime v2 WorkItems,
snapshot bindings, and execution receipts already present in the integration
branch. Runtime v2 is a prerequisite for this path, not a replacement for the
legacy Worker Pipeline. With Project Agents disabled, legacy dispatch remains
unchanged.
