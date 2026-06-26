# Artifact Producer Protocol

`ArtifactProducer` is the generalized execution role for non-code and mixed
deliverables. It exists so `Coder` does not become a catch-all executor for
text, images, video, audio, spreadsheets, presentations, and bundled outputs.

## Dispatch Rule

Brain/Supervisor must route by deliverable type before choosing a worker.

- Code changes, patching, scripts, and automated integration: `Coder`.
- Text, image, video, audio, spreadsheet, presentation, or mixed deliverables:
  `ArtifactProducer`.
- Code plus deliverables: `Coder` first, then `ArtifactProducer`.

`ArtifactProducer` must not execute without an `ArtifactTask` contract.

## ArtifactTask Contract

Generate a contract with:

```bash
./agentlab.sh artifact-task-plan \
  --task-text "<user artifact request>" \
  --project <Project> \
  --task-id <task_id> \
  --write
```

The contract is written to:

```text
projects/<Project>/runs/<task_id>/artifact_task.yml
```

Required fields:

- `artifact_type`: `text`, `image`, `video`, `audio`, `spreadsheet`,
  `presentation`, or `mixed`.
- `output.path` and `output.format`.
- `required_capabilities`.
- `requirements`.
- `validation`.
- `routing`.

## Provider Routing

Provider capabilities are configured in:

```text
config/artifact_task_policy.yml
```

Current provider order:

- `codex_high_cli`: highest-quality CLI provider.
- `agy_cli`: regular CLI provider for frontdesk-adjacent artifact work.
- `qwen_37max_api`: fallback provider.

The selected provider maps to a bound worker. Role binding is still enforced by
`role-session` and `role-doctor`.

## Failure Contract

If the assigned worker cannot produce the artifact, it must return one of:

```yaml
status: capability_mismatch
missing_capability: generate_video
recommended_role: ArtifactProducer
recommended_provider: qwen_37max_api
```

or:

```yaml
status: needs_fallback
reason: provider_unavailable
attempted_provider: agy_cli
recommended_provider: qwen_37max_api
```

It must not silently switch providers or claim a file was produced without
evidence.

## Verification

Run:

```bash
./agentlab.sh artifact-doctor
./agentlab.sh protocol-doctor
```

Both must pass before relying on ArtifactProducer routing.
