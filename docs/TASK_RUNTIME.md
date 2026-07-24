# AgentLab Task Runtime

## Outcome

Task Runtime keeps one user-visible business goal under one stable `Task`. It no
longer treats every chapter, reviewer pass, retry, fallback, or candidate
revision as another task directory.

```text
Task (one business goal and acceptance boundary)
  └─ Job (inline/detached or alternative execution strategy)
      └─ WorkItem (chapter, review, test, batch unit, dependency node)
          └─ Attempt (one worker invocation, retry, or fallback)
              └─ ArtifactVersion + EvidenceBinding
```

Use a new Task only when the requested outcome can be accepted, cancelled, and
promoted independently. Use a Job for another strategy, a WorkItem for another
unit of the same goal, and an Attempt for a retry. Exact normalized goal matches
are blocked across Task IDs unless the caller explicitly declares an independent
acceptance boundary with `--allow-duplicate-goal` and an auditable
`--independent-boundary-reason`.

## Authority and storage

The only Task authority is:

```text
projects/<Project>/runtime/tasks/<task_id>/events.jsonl
```

Each line is canonical JSON with a sequence number, idempotency key, prior-event
hash, and its own SHA256. Appends are serialized by file locks, flushed, and
`fsync`ed. Hash, sequence, project, task, transition, duplicate-entity, missing
reference, and active-attempt violations fail closed.

Everything below `projections/` is a cache rebuilt from the ledger:

- `task.yml`, `jobs.yml`, `work_items.yml`, `attempts.yml`
- `artifact_index.yml`, `evidence.yml`, `trace_records.yml`
- `progress.yml`, `handoff.yml`

`runtime/task_index.yml` and `runtime/knowledge/selected_artifacts.yml` are also
rebuildable project projections. Editing them never changes Task truth.

## Strict input tiers

Task intake uses declared facts from `config/task_input_tiers.yml`; it does not
guess a cheaper route from prompt keywords. The resulting classification is
written into the `TASK_CREATED` event and every rebuilt Task projection.
Missing, partial, or unknown facts are not admitted for execution. The complete
tier meanings, Worker limits, validation gates, and required records live only
in that policy file. Runtime scheduling enforces the recorded tier and route;
completion enforces its immutable trace-record set. A requested tier may raise
the route but cannot lower the policy-derived minimum. Brain scope and quality
authority for prose builds is declared in `config/task_runtime_v2.yml`.

## Why this avoids evidence ambiguity

An Attempt is immutable and has one worker, provider, execution-contract hash,
ordinal, status, outcome, duration/cost data, and producer relationship. Only a
successful Attempt can create an ArtifactVersion. The version records file path,
size, media type, and SHA256; recording materializes a version-specific immutable
copy under `artifacts/versions/<version_id>/`. Selection is blocked until an
EvidenceBinding pins the input manifest hash, RAG index snapshot, source hashes,
audit result, and the producer execution receipt.

For strict-tier Tasks, `succeeded` is accepted only with the hashed output and
receipt written by `attempt execute-role`; the project doctor revalidates both.
Brain classification, scope, execution-plan, and quality records must match the
referenced Supervisor Attempt output. Worker receipts bind the delegated Attempt
receipt hashes, while change and memory records bind hashes of real files inside
the owning project. Sealed outbound sources are limited to governed project
production/Brain/reset inputs, explicitly labelled candidate run outputs, and
hashed outputs/receipts from the same Task Runtime Task. Candidate run files are
never labelled as authoritative or silently promoted to production fact.

This permits multiple revisions without growing one ambiguous “current state”
file: the ledger retains history, while projections show the current selection.

## RAG boundary

RAG remains project-level. Task Runtime does not create a vector/keyword database
per Task. The only runtime file eligible for the project knowledge collector is:

```text
projects/<Project>/runtime/knowledge/selected_artifacts.yml
```

Raw ledgers, attempt logs, failed outputs, and candidate artifact bytes are not
indexed. Canonical project facts and accepted content remain under
`project_brain/` and `production/`. Stable source and content hashes let the
existing knowledge system chunk and tombstone changed sources without copying
each Task into a separate knowledge base.

## Lifecycle and scheduling

Tasks use `created`, `ready`, `running`, `waiting`, `blocked`, `paused`,
`completed`, `failed`, and `cancelled`. WorkItems hold dependency edges. A
dependent WorkItem changes from `pending` to `ready` only when every dependency
is `accepted`.

Each WorkItem may have only one `scheduled` or `running` Attempt at a time. A
failed Attempt releases that lease; a retry receives a new Attempt ID and ordinal
inside the same WorkItem and Task. This makes Hermes+Ark primary execution and an
explicit Claude+Ark fallback distinct, auditable Attempts rather than parallel
Task chains.

## CLI

The v2 commands are registered on `agentlab.sh`:

```bash
./agentlab.sh task create --project Demo --task-id task-demo \
  --title "One result" --goal "Produce and review one result" \
  --input-profile-json '{"kind":"creative_patch","scope":"localized","target_count":1,"canon_impact":"candidate","risk_flags":[]}' \
  --idempotency-key request-001
./agentlab.sh task classify \
  --input-profile-json '{"kind":"prose_build","scope":"multi_chapter","target_count":0,"canon_impact":"canonical","risk_flags":["longform_continuity"]}'
./agentlab.sh task classify-set ...
./agentlab.sh task show --project Demo --task-id task-demo
./agentlab.sh task list --project Demo
./agentlab.sh task pause --project Demo --task-id task-demo \
  --idempotency-key pause-001
./agentlab.sh task resume --project Demo --task-id task-demo --status ready \
  --idempotency-key resume-001

./agentlab.sh job create ...
./agentlab.sh work-item create ...
./agentlab.sh work-item status ...
./agentlab.sh attempt schedule ...
./agentlab.sh attempt status ...
./agentlab.sh attempt execute-role ...
./agentlab.sh artifact record ...
./agentlab.sh evidence bind ...
./agentlab.sh artifact select ...
./agentlab.sh evidence verify ...
./agentlab.sh trace record ...

./agentlab.sh runtime rebuild --project Demo
./agentlab.sh runtime doctor --project Demo
```

Every mutating command requires an idempotency key, including Task
pause/resume/cancel. A later pause after a resume must use a new key; retrying the
same pause request reuses its original key. For strict-tier Tasks, `attempt
status --status succeeded` is intentionally rejected; only `attempt execute-role`
may append a successful Attempt after validating the model-execution receipt.

## Legacy migration

During the staged cutover, `task list` returns only v2 ledgers by default.
`projects/<Project>/runs/*/state.yml` can be inspected only with the explicit
`--include-legacy` compatibility option; a v2 entry wins if an ID exists in
both places.
The new `task`/`job`/`work-item`/`attempt` commands write only to v2. Existing
legacy pipeline entrypoints remain maintenance-only until their projects are
migrated; they are not a second authority for a v2 Task.

Migration is preview/apply and never edits or deletes legacy runs:

```bash
./agentlab.sh runtime migrate-legacy --project Demo
./agentlab.sh runtime migrate-legacy --project Demo --apply \
  --expected-plan-hash <approved_sha256>
```

If a legacy state or request changes after preview, apply fails. A repeated apply
recognizes matching imported source hashes and does not duplicate events.

## Retention and recovery

Ledgers, hashes, evidence, costs, audits, and selection history are permanent.
Attempt logs older than seven days may be losslessly replaced with verified gzip
files only through a hash-gated compaction plan. The receipt records original and
compressed hashes; no policy purges the compressed evidence.

```bash
./agentlab.sh runtime compact-logs --project Demo
./agentlab.sh runtime compact-logs --project Demo --apply \
  --expected-plan-hash <approved_sha256>
```

Use `runtime doctor` to detect ledger or artifact tampering. Use
`runtime rebuild` to discard and recreate every projection and the curated RAG
manifest. Never repair a damaged ledger by editing its hashes; stop execution and
recover from a verified copy or an explicit governance decision.
