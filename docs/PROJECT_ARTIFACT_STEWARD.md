# Project Artifact Steward

`ProjectArtifactSteward` is the deterministic artifact-governance layer for long-running AgentLab tasks. It is not a standing Project Manager agent. It is a small filesystem protocol used by Brain planning, Coder/ArtifactProducer output, Archivist promotion, and the artifact gate.

## Required Files

- `workflow_plan.yml` must include `artifact_intent`.
- `artifact_lineage.yml` records paths added, modified, replaced, deprecated, referenced, or marked evidence-only by the task.
- `artifact_promotion_plan.yml` lists candidate run artifacts that may be promoted into the project production artifact area.
- `archive_receipt.yml` is the machine-readable receipt written after Archivist performs copy, archive, and index updates.
- `project_artifact_index.yml` is the project-level ledger for current production artifacts and archived prior versions.

## Directory Rules

- `projects/<Project>/runs/<task_id>/` is for process evidence: reports, logs, plans, task packets, state, progress, and validation material.
- `projects/<Project>/runs/<task_id>/artifacts/` is for candidate deliverables produced by this task.
- `projects/<Project>/artifacts/` is for current production deliverables only.
- `projects/<Project>/artifacts/_archive/<artifact_id>/<timestamp>__<task_id>/` stores old production versions before replacement.

## Fatal Gate Conditions

- Production artifact directories contain run reports, prompts, validation reports, audit reports, or other evidence files without an explicit `evidence_only` ledger marker.
- A promoted artifact has no matching `source_task` and `source_run_artifact` in `project_artifact_index.yml`.
- One artifact has multiple `current` versions.
- A replacement claims `supersedes` but has no archived old version.
- A completed task has no `archive_receipt.yml`.
- `artifact_lineage.yml` declares an undeclared production path.

`09_archive_update.md` remains a human-readable summary. It is not sufficient archive evidence by itself.
