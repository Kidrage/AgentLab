# M3 Architecture Impact Report

## Decision

AgentLab will add two deep modules without replacing the Background Job
Controller or the existing Worker Pipeline:

1. `ProjectTruthStore` owns project-current state, immutable accepted history,
   optimistic concurrency, and canonical commit receipts.
2. `ProjectAgentRegistry` owns explicit project-agent identity, contracts,
   lifecycle, and factory proposals.

The Project Agent layer depends on enforced Project Truth. Existing projects
and pipelines remain on the legacy path until explicitly enabled.

## Baseline

- Source baseline: `7ef00bf9ad9d989fa8d4911ac793dba95126f5ca`
- Baseline branch: `feature/task-runtime-v2`
- Implementation branch: `feature/m3-project-agents-truth`
- Focused baseline: `143 passed`
- Crown production job
  `crown-efficiency-v7-ch001-010-20260723`: `paused`
- The pre-existing dirty workspace is preserved. M3 implementation uses an
  isolated clean Git worktree.

## Current Architecture

| Concern | Current authority | M3 treatment |
|---|---|---|
| Stable role contracts | `config/agent_registry.yml` | Unchanged; project agents bind through `runtime_role` |
| Model and worker selection | model profiles, worker contracts, capacity config | Existing authority remains; a manifest's `model_profile` selects a configured tier |
| Workflow and lifecycle | fixed pipeline and Background Job Controller | Unchanged when project agents are disabled |
| Runtime evidence | Task Runtime v2 events, ArtifactVersion, EvidenceBinding | Reused by canonical commit receipts |
| Project deliverables | `production/` plus `project_artifact_index.yml` | Becomes a projection of Project Truth |
| Project facts | Project Brain snapshots and domain-specific ledgers | Becomes a rebuildable projection |
| Knowledge | system/domain/project SQLite shards | Adds private Agent shards and snapshot-aware selection |
| External executors | External Agent Registry and worker contracts | Kept separate from project professional identity |

## Confirmed Failure Modes

### Artifact identity is not semantic identity

`project_artifact_steward._record_index_promotion` supersedes records only when
the artifact ID or production path matches. The validator detects multiple
current versions of one artifact ID, but not multiple artifacts that assert the
same project fact.

### Path-based authority promotes candidates

The knowledge collector assigns all supported files under `project_brain/`
canonical authority. A file whose own lifecycle is `candidate` can therefore
enter project retrieval as canonical.

### Promotion is not a transaction

The legacy archive protocol copies and replaces targets one at a time and
writes the project index after the loop. A later failure can leave a partially
modified production tree. There is no expected-current snapshot or project
write lease.

### Project data and source development overlap

Canonical narrative snapshots have contained absolute paths to sibling Git
worktrees. During the architecture audit, Crown authority files changed while
the audit was read-only. This confirms that source development and production
data need non-overlapping roots and explicit leases.

### Domain-specific authority is not a project operating model

Narrative Fact Authority provides a good single-lineage precedent, but its
schema and projections are narrative-specific. It cannot be the core authority
for code architecture, media settings, research conclusions, or Agent
manifests.

## New Invariants

1. A project has exactly one atomic `current_snapshot_id`.
2. A live `resource_key` has exactly one current revision in that snapshot.
3. A live `fact_key` has exactly one current value and owner resource.
4. Candidates, evidence, projections, and history never become truth because
   of their directory.
5. All project mutations enter through a ChangeSet with an expected snapshot.
6. Multi-resource commits either switch the single current pointer or leave it
   unchanged.
7. Accepted history is immutable and excluded from normal retrieval.
8. Project agents can propose changes but cannot directly write canonical
   projections.
9. Every dynamic project agent is registered; no implicit project agents exist.
10. AgentLab source writes and project-production writes use logically
    isolated, symlink-safe workspaces and separate leases.

M3 enforces the logical workspace boundary needed by Project Agents. Moving all
runtime project roots physically outside the AgentLab source checkout is the
accepted M3.1 follow-up and is not claimed as complete here.

## Storage and Compatibility

The project root exposes one mutable pointer:

```text
project_truth.yml
```

Internal immutable state lives under:

```text
.agentlab/truth/objects/sha256/
.agentlab/truth/snapshots/
.agentlab/truth/receipts/
.agentlab/truth/events.jsonl
```

`production/`, `project_artifact_index.yml`, and Project Brain snapshots remain
available as legacy projections. In enforced mode they carry the source
snapshot ID and are not writable by project agents.

Feature configuration:

```yaml
features:
  project_truth_mode: legacy
  enable_project_agents: false
workspace:
  isolation: required
```

Modes:

- `legacy`: existing behavior.
- `shadow`: audit and report conflicts without changing legacy writes.
- `enforced`: canonical writes and reads use Project Truth.

`enable_project_agents: true` is invalid unless truth mode is `enforced`.

## Public Interfaces

### Project Truth

- `ProjectTruthStore.current()`
- `ProjectTruthStore.commit(change_set)`
- `ProjectTruthStore.fact_history(key)`
- `ProjectTruthStore.resource_history(key)`
- `ProjectTruthStore.rollback(snapshot_id, ...)`
- `ProjectTruthStore.audit()`

Every mutation requires an idempotency key and expected snapshot ID. Stale
writers receive a deterministic conflict instead of last-write-wins behavior.
The controller owns principal authentication and assigns `actor_id`; model
output is never permitted to select that audit identity.

### Project Agents

- `ProjectAgentRegistry.list()` / `get()`
- `ProjectAgentRegistry.register()`
- `ProjectAgentRegistry.update()`
- `AgentLifecycle.pause()` / `resume()` / `replace()` / `archive()`
- `ProjectAgentFactory.propose()`
- `ProjectAgentFactory.create_team()`

Permission expansion and user/recommendation creation require approval.
Factory proposals also require an explicit approval decision; Registry callers
cannot self-declare a trusted template.

## Runtime Integration

Project-enabled WorkItems add:

- `assigned_agent_id`
- `agent_manifest_revision`
- `canonical_snapshot_id`
- `effective_contract_hash`

The assigned project agent resolves to an existing `runtime_role`. The existing
RoleAttemptExecutor remains responsible for worker execution. Expert
consultations are ordinary WorkItems and produce snapshot-bound advisory
artifacts. `ExpertCollaborationScheduler` materializes the registered,
topologically validated expert DAG as Runtime v2 WorkItems. At execution time
the RoleAttemptExecutor revalidates the current snapshot, manifest revision,
active status, runtime role, and effective contract hash. The Agent manifest's
`model_profile` then selects the configured full, performance, or low model
tier; an unknown profile fails closed.

Runtime v2 is therefore an explicit prerequisite of the executable Project
Agent path in this integration. It remains independently disabled for legacy
projects, so the existing Worker Pipeline and Background Job Controller keep
their prior behavior.

## Migration

Migration is review-first:

1. Audit and classify current, candidate, history, evidence, and unknown files.
2. Produce a deterministic migration plan without mutation.
3. Resolve fact-key conflicts.
4. Ingest selected current resources and facts into the first snapshot.
5. Rebuild projections and knowledge from that snapshot.
6. Verify hashes and context isolation.
7. Enable enforced mode.

Crown is the first narrative pilot. Its approved 1,980-chapter decision becomes
the sole current scale fact; old 200-chapter outlines and 1,500-chapter
simulations remain history or evidence only.

## Rollback

- Before pointer switch: discard staged immutable objects.
- After pointer switch: create a new generation pointing to the selected prior
  revisions; never rewrite history.
- General content rollback excludes `agents.manifest.*`. Agent lifecycle,
  authority, runtime role, and model profile change only through Registry and
  Lifecycle operations, so rollback cannot resurrect or broaden an Agent.
- Projection failure: mark the projection stale and block consumers while the
  canonical pointer remains recoverable.
- Agent rollout failure: disable `enable_project_agents`; existing pipelines
  continue through compatibility projections.

## Delivery Gates

Each implementation slice is committed separately. Before the next slice:

1. focused tests pass;
2. full pytest passes;
3. the commit is pushed to the feature branch;
4. GitHub CI is green.

The final gate includes conflict injection, crash recovery, knowledge leakage,
permission, lifecycle, logical workspace-isolation, backward-compatibility, and
migration-planner tests. Crown itself is not migrated automatically.
