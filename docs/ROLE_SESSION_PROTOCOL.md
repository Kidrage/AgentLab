# AgentLab Role Session Protocol

Authority: `_shared/AGENT_PROTOCOL.md`

AgentLab's logical roles are not implied by CLI names. A worker becomes a
Supervisor, Coder, Verifier, or any other role only after AgentLab generates a
role session packet and the worker-role binding passes policy.

## Roles

- Supervisor
- RepoScout
- Researcher
- InterfaceMapper
- PromptEngineer
- Coder
- ArtifactProducer
- TesterAuditor
- Verifier
- Archivist

## Required Session

```bash
./agentlab.sh role-session --role <Role> --worker <worker> --project <Project> --task-id <task_id>
```

The packet includes:

- role identity and worker id
- binding verdict
- task state
- required input artifacts
- required outputs
- ArtifactTask contract when role is `ArtifactProducer`
- source write policy
- shell policy
- forbidden actions
- exit report requirements

## Strong Rules

- A frontdesk-only worker cannot execute AgentLab roles.
- A worker cannot execute a role unless `config/agent_role_bindings.yml` allows
  both directions: worker allows role, and role allows worker.
- Generated role sessions are required for AgentLab-managed worker invocation.
- `ArtifactProducer` must receive `artifact_task.yml` before producing non-code
  or mixed deliverables.
- A worker must stay inside the assigned role and report evidence.

## Verification

```bash
./agentlab.sh role-doctor --role <Role> --worker <worker>
```
