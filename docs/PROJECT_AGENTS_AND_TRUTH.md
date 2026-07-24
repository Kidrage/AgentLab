# Project Agents and Canonical Truth

## Authority rule

An enforced project has exactly one visible authority pointer:
`projects/<project>/project_truth.yml`.

That pointer selects one immutable canonical snapshot under
`.agentlab/truth/snapshots/`. A snapshot contains one live revision for each
semantic resource key and fact key. Revisions that are no longer selected are
history, not competing truth.

The following are never authority in enforced mode:

- candidate, run, evaluation, receipt, archive, and evidence files;
- timestamps, filename suffixes, and "latest" naming conventions;
- `production/`, `project_artifact_index.yml`, and knowledge indexes, which are
  projections;
- old `project_brain/` documents retained after migration.

All writes use `ChangeSet` with an expected snapshot (compare-and-swap), a
stable idempotency key, and an immutable receipt. Concurrent stale writers fail.
An artifact promotion must declare `canonical_key`; two revisions with the same
key replace the current selection rather than creating two authorities.

## Feature flags

New projects remain backward compatible:

```yaml
features:
  project_truth_mode: legacy
  enable_project_agents: false
workspace:
  isolation: required
```

`project_truth_mode` supports `legacy`, `shadow`, and `enforced`. Shadow mode
keeps legacy reads/writes and persists the migration planner's conflict report;
it never silently activates a selected truth:

```bash
./agentlab.sh project-truth-shadow --project MyProject
```

Project Agents may execute only when the mode is `enforced` and workspace
isolation is required. Existing Worker pipelines remain unchanged while the
feature is off.

These names describe different layers and must not be presented as one generic
"capability":

- **Task Runtime** is the durable Task/Job/WorkItem/Attempt execution
  architecture. `runtime-v2` and `task-runtime-v2` remain compatibility
  identifiers for the existing CLI and persisted schema; the product name is
  versionless.
- **Canonical Project Truth** is the single-pointer, immutable-history authority
  model. `project_truth_mode` is its real project-level mode switch:
  `legacy`, `shadow`, or `enforced`.
- **Project Agent Organization** is the optional registered Agent team layer.
  `enable_project_agents` is its real feature flag.
- **Workspace isolation** is a safety gate, not a feature or release name.
- **Collaboration DAGs** are per-task execution plans compiled from the current
  Agent Registry; they are resources, not global switches.
- **Project Knowledge** is a derived RAG index of the selected current truth. It
  is never an authority source.

Enable the new layer explicitly:

```bash
./agentlab.sh project-agents-enable --project MyProject
```

## Updating project content

Small decisions should use stable fact keys:

```bash
./agentlab.sh set-project-fact \
  --project MyProject \
  --key novel.total_word_count \
  --value-json 150000 \
  --owner project.editorial \
  --idempotency-key approve-length-150k
```

Documents and structured assets use stable resource keys:

```bash
./agentlab.sh set-project-resource \
  --project MyProject \
  --key characters.current \
  --content-path projects/MyProject/project_brain/characters.yml \
  --idempotency-key approve-characters-r7
```

Inspect history and integrity:

```bash
./agentlab.sh project-fact-history \
  --project MyProject --key novel.total_word_count
./agentlab.sh project-resource-history \
  --project MyProject --key characters.current
./agentlab.sh project-truth-audit --project MyProject
```

Do not create `final_v2`, `latest_new`, or parallel "current" files to express a
revision. The semantic key is the identity; history is automatic.

Rollback also creates a new audited generation; it never moves the pointer
backward or deletes history. General truth rollback deliberately preserves all
current `agents.manifest.*` resources. Agent status, authority, runtime role,
and model profile may change only through Registry/Lifecycle operations, so
content recovery cannot reactivate or broaden an old Agent:

```bash
./agentlab.sh rollback-project-truth \
  --project MyProject \
  --snapshot-id <approved-prior-snapshot> \
  --idempotency-key rollback-after-review
```

## Dynamic Agent lifecycle

Every project Agent has an explicit `AgentManifest`. It includes identity,
responsibilities, stable Runtime role, read/write/approval scopes, private
knowledge binding, model/tool/budget profiles, lifecycle status, acceptance
rules, and collaboration relationships.

Supported operations:

```bash
./agentlab.sh create-agent-team --project MyProject --prompt "Build a secure API"
./agentlab.sh add-agent --project MyProject --agent-id history \
  --name "History Research Agent" --role history_researcher \
  --responsibility "Maintain historical accuracy" \
  --read-scope "world.*" --write-scope "research.history.*"
./agentlab.sh pause-agent --project MyProject --agent-id history
./agentlab.sh resume-agent --project MyProject --agent-id history
./agentlab.sh replace-agent --project MyProject --agent-id history \
  --model-profile high_reasoning
./agentlab.sh archive-agent --project MyProject --agent-id history
```

Agents are never hard-deleted. Archived manifests remain in immutable history.
System recommendations and factory team proposals require approval. The CLI
team-creation command is an explicit user approval; API callers must pass their
approval decision and Registry callers cannot assert a trusted-template bypass.

Task Runtime binds every enabled WorkItem to:

- `assigned_agent_id`;
- `agent_manifest_revision`;
- `canonical_snapshot_id`;
- `effective_contract_hash`.

Paused, archived, missing, stale, or contract-mismatched Agents fail closed.
The bound manifest's `model_profile` selects the configured full, performance,
or low Runtime model tier. Replacing an Agent therefore changes subsequent
snapshot-bound execution, while an unknown profile fails closed.
Canonical truth independently enforces the active manifest's write scope, so a
caller cannot bypass the contract by writing directly to the truth store.
`actor_id` is audit metadata assigned by the trusted AgentLab controller; it
must never be copied from model output or exposed as a user-selectable remote
API field. Deployments that expose Project Truth across a process boundary must
authenticate the principal before constructing a `ChangeSet`.

Artifact promotion records
`canonical_projection_transaction.yml` as `pending_projection` after the
canonical commit and `projected` after the filesystem projection. Retrying the
same task is idempotent and completes an interrupted projection.

## Memory and collaboration

Knowledge resolution follows:

`Global Memory -> Domain Memory -> Project Memory -> Agent Memory`

Agent memory uses a private physical shard named by
`agent.<project>.<agent_id>`. Project Agents cannot substitute another Agent's
namespace.

Reusable collaboration DAGs are available for narrative, software, audio, and
generic production. Domain experts prevent local errors before production;
Reviewer remains responsible for overall quality instead of impersonating every
expert role.

Materialize an approved DAG as ordinary, dependency-linked Task Runtime WorkItems:

```bash
./agentlab.sh work-item materialize-collaboration \
  --project MyProject \
  --task-id task-001 \
  --domain narrative \
  --idempotency-prefix task-001-experts
```

Each generated WorkItem is bound to the current canonical snapshot, Agent
manifest revision, and effective contract hash. The command validates the full
DAG before atomically appending one batch event; a conflict writes no WorkItem
from the batch.

`workspace.isolation: required` currently means a logical, symlink-safe project
boundary with governed writes and leases. Moving runtime project roots
physically outside the AgentLab source checkout is tracked as a separate follow-up.

## Legacy migration

Never activate canonical truth by choosing the newest-looking legacy file.
Generate a conflict report first:

```bash
./agentlab.sh plan-project-truth-migration \
  --project Crown_of_Ash \
  --output /tmp/crown_truth_plan.yml
```

The planner reports differing scalar claims such as multiple word-count rules.
It deliberately sets `activation_ready: false`. A human-approved
`project-truth-migration/v1` manifest must name the chosen fact/resource keys
and bind every imported source by SHA-256.

Apply only after the manifest is reviewed:

```bash
./agentlab.sh apply-project-truth-migration \
  --project Crown_of_Ash \
  --manifest /path/to/approved_migration.yml
```

Activation happens last. Legacy files remain non-authoritative evidence; the
canonical pointer becomes the only live truth.
