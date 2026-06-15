# Skill Distillation

AgentLab supports a local skill lifecycle. P2-F adds Project Memory → Skill Draft.
Drafts are generated locally, require human approval, and are never promoted automatically.

## Commands

```bash
./agentlab.sh skill-distill --project AgentLab --task-id task_0001
./agentlab.sh skill-draft-list --project AgentLab
./agentlab.sh skill-draft-approve --project AgentLab --draft-id <draft_id>
./agentlab.sh skill-draft-reject --project AgentLab --draft-id <draft_id> --reason "not reusable"
```

## Artifact format

```text
projects/<Project>/runs/<task_id>/skill_drafts/<draft_id>/
  SKILL.md
  metadata.yml
  validation_plan.yml
  evidence_map.yml
  source_trace.yml
```

This phase does not support full-web automatic skill discovery or automatic external skill loading. `config/skill_discovery.yml` is disabled by default.

## Central Skill Vault

Project Memory now flows through `SkillDistiller` into `memory/global/skills/drafts/<skill_id>/`. The project run keeps only `POINTER.yml`, so task cleanup cannot remove durable skill drafts. Manual approval moves drafts to `approved`; rejection moves them to `rejected`; activation is never automatic.
