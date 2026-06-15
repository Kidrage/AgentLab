<!-- text-integrity: keep this file as real physical lines in Git and GitHub raw. -->

# Skill Vault

AgentLab stores long-lived self-learned skills in a central local Skill Vault instead of project task run directories.

## Why project runs are not durable

Project task run folders are operational scratch space. They can be archived, pruned, or rebuilt after a task completes. A skill draft that may be useful for future work must survive task cleanup, so `projects/<Project>/runs/<task_id>/skill_drafts/` now contains only a lightweight pointer.

## Local layout

The default vault root is:

```text
memory/global/skills/
  registry.yml
  MANIFEST.yml
  inbox/
    self_learned/
    external_imports/
    discovered/
  drafts/
  approved/
  staging/
  active/
  rejected/
  retired/
  quarantine/
```

Status meanings:

- `inbox/self_learned`: newly generated local candidates before full draft packaging.
- `inbox/external_imports`: external URL or package candidates that are not approved.
- `inbox/discovered`: future discovery candidates; discovery remains disabled by default.
- `drafts`: complete `SKILL.md`, metadata, validation plan, evidence map, source trace, and origin pointer.
- `approved`: manually approved drafts waiting for staging or validation.
- `staging`: skills currently being validated.
- `active`: local long-term self-learned skills that may be used by runtime resolvers.
- `rejected`: manually rejected drafts.
- `retired`: previously used skills that should no longer be selected.
- `quarantine`: high-risk, conflicting, or untrusted material.

## Project run pointers

When `skill-distill` creates a draft, the durable draft is written to:

```text
memory/global/skills/drafts/<skill_id>/
```

The task run receives only:

```text
projects/<Project>/runs/<task_id>/skill_drafts/<skill_id>/POINTER.yml
```

The pointer records `skill_id`, `vault_path`, `source_project`, `source_task_id`, and status. It can be deleted with task cleanup without deleting the vault copy.

## Registry and manifest

`registry.yml` is the global index for skill id, status, project, task ids, risk, reuse score, validation signal, and safety flags.

`MANIFEST.yml` records file paths, SHA256 hashes, byte sizes, and artifact roles. It is updated after distillation, approval, rejection, migration, and backup planning.

## Git ignore policy

`memory/global/skills/` is local runtime memory and is ignored by git. Configuration and documentation remain tracked:

```text
config/skill_vault.yml
docs/SKILL_VAULT.md
```

Do not commit generated real skill drafts, local secrets, SSH keys, or private paths.

## TrueNAS / SSH backup

Skill Vault backup is configured in `config/backup_policy.yml` under `skill_vault_backup`. The backup module plans `rsync -av --delete` to a user-provided SSH destination.

No SSH host, user, private key, or password is hard-coded in the repository. Configure locally with either:

```bash
export AGENTLAB_SKILL_VAULT_BACKUP_REMOTE='user@host:/remote/base'
```

or:

```bash
export AGENTLAB_BACKUP_SSH_USER='user'
export AGENTLAB_BACKUP_SSH_HOST='host'
export AGENTLAB_BACKUP_REMOTE_BASE='/remote/base'
```

Backup defaults to dry-run. Real transfer requires `--execute`.

## Commands

```bash
./agentlab.sh skill-distill --project AgentLab --task-id <task_id>
./agentlab.sh skill-draft-list --project AgentLab
./agentlab.sh skill-draft-approve --project AgentLab --draft-id <skill_id>
./agentlab.sh skill-draft-reject --project AgentLab --draft-id <skill_id> --reason "reason"
./agentlab.sh skill-vault-list
./agentlab.sh skill-vault-status
./agentlab.sh skill-vault-migrate --project AgentLab --dry-run
./agentlab.sh skill-vault-migrate --project AgentLab --execute
./agentlab.sh skill-vault-backup --dry-run
./agentlab.sh skill-vault-backup --execute
./agentlab.sh skill-vault-backup-status
```

## Safety defaults

External skill discovery remains disabled by default. AgentLab does not automatically import, execute, approve, promote, or activate external skills.
