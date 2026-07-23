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

`project_truth_mode` supports `legacy`, `shadow`, and `enforced`. Project Agents
may execute only when the mode is `enforced` and workspace isolation is
required. Existing Worker pipelines remain unchanged while the feature is off.

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
./agentlab.sh project-truth-audit --project MyProject
```

Do not create `final_v2`, `latest_new`, or parallel "current" files to express a
revision. The semantic key is the identity; history is automatic.

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
System recommendations require approval. Trusted factory templates may activate
without approval only when they do not expand an existing Agent's authority.

Runtime v2 binds every enabled WorkItem to:

- `assigned_agent_id`;
- `agent_manifest_revision`;
- `canonical_snapshot_id`;
- `effective_contract_hash`.

Paused, archived, missing, stale, or contract-mismatched Agents fail closed.

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
