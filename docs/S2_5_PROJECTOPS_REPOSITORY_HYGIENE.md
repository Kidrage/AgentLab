# S2.5 ProjectOps / Repository Hygiene

S2.5 is inserted between S2 Domain Workflow Templates and S3 Skill OS.

The goal is to keep AgentLab debuggable before more external skills, external agents, and capability providers are added.

## What S2.5 Adds

- Repository root hygiene policy.
- Project routing that separates AgentLab self-development from user projects.
- Standard project initialization layout.
- Task compaction output.
- Agent contribution ledger.
- Lightweight agent packet contract.
- Project status reporting.

## What S2.5 Does Not Do

- No skill discovery or installation.
- No web crawling.
- No vision or multimodal model calls.
- No external execution.
- No dashboard UI.
- No automatic deletion of raw artifacts.

## Command Surface

```bash
./agentlab.sh repo-hygiene-check
./agentlab.sh project-route --mission-contract examples/mission_contracts/creative_longform.yml
./agentlab.sh project-init --project-id example_creative_project --type creative --title "Example Creative Project"
./agentlab.sh project-status --project example_creative_project
./agentlab.sh task-compact --project example_creative_project --task task_0001
./agentlab.sh agent-contributions --project example_creative_project --task task_0001
```

The same commands are available through:

```bash
python -m agent_runtime.project_ops.cli <command>
```

## Why This Matters

S3 and later stages will introduce more skill/package/capability inputs. Without S2.5, AgentLab would accumulate unclassified root artifacts and repeated raw task logs, making agent collaboration slow, expensive, and opaque.
