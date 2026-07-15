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
  --input projects/<Project>/inputs/<source-file> \
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
- `assigned_inputs`: optional, explicit root-contained files bound to
  `artifact_inputs/<index>_<name>` with byte count, SHA-256, and
  `read_only: true`. Repeat `--input` for multiple files; directories,
  symlinks, path escapes, or changed hashes fail before provider execution.

## Provider Routing

Provider capabilities are configured in:

```text
config/artifact_task_policy.yml
```

Current provider order:

- `claude_deepseek`: default text, spreadsheet, and presentation producer
  through the governed Claude Code + DeepSeek contract.
- `qwen_cli`: metered text, spreadsheet, and presentation fallback
  through the governed Qwen CLI contract. It receives only the sealed task
  packet and hash-verified read-only input copies in an isolated workspace;
  AgentLab copies back only exact declared outputs.
- `qwen_37max_api`: explicit API fallback for only the artifact types and
  capabilities declared in policy.
- `grok_media`: quarantined candidate image/video producer. It is never
  selected automatically and may run only as an explicit bounded canary.

Default image/video generation is routed separately through the approval-gated
Bailian CLI, with Ark as the premium configured option. These media backends
remain governed ArtifactProducer executions even though they are not generic
text ArtifactTask providers.

No governed audio backend is currently registered. Audio requests therefore
return `capability_mismatch` until a provider with `generate_audio` and
`write_artifact_file` is explicitly added. A fallback flag never makes an
otherwise incapable provider eligible.

The selected provider maps to a bound worker. Role binding is still enforced by
`role-session` and `role-doctor`. Provider/model changes are never silent: any
fallback must be named by an explicit, governed decision.

Image and video outputs remain candidates. The producer cannot review or accept
its own output; promotion requires independent Observer, Reviewer, and Verifier
evidence over the actual returned asset files and hashes.

## Failure Contract

If the assigned worker cannot produce the artifact, it must return one of:

```yaml
status: capability_mismatch
missing_capability: generate_audio
recommended_role: ArtifactProducer
recommended_provider: null
```

or:

```yaml
status: needs_fallback
reason: provider_unavailable
attempted_provider: qwen_cli
recommended_provider: qwen_37max_api
```

Cross-provider mixed requests are `capability_mismatch` until a composite
adapter can preserve every requested component; they are never reduced to one
provider's partial output.

It must not silently switch providers or claim a file was produced without
evidence.

## Verification

Run:

```bash
./agentlab.sh artifact-doctor
./agentlab.sh protocol-doctor
```

Both must pass before relying on ArtifactProducer routing.
