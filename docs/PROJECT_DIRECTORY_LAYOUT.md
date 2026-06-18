# Project Directory Layout

Every non-trivial user project should have a project boundary. AgentLab's own repository development is only one project, not the default destination for every invocation.

## Standard Layout

```text
projects/<project_id>/
  project.yml
  project_brain/
    product_vision.md
    roadmap.yml
    decision_log.yml
    acceptance_history.yml
    unresolved_questions.yml
    known_risks.yml
    architecture_state.yml
    next_actions.yml
    memory_index.yml
  tasks/
    active/
    closed/
    compacted/
    archived/
  agents/
  artifacts/
  acceptance/
  cost/
```

## Routing Rule

Only route to `projects/AgentLab` when the mission clearly asks to modify AgentLab itself, this repository, or the mainline repair plan. Creative, research, business, document, audio, and multimodal tasks create new user projects by default.

Use:

```bash
./agentlab.sh project-route --mission-contract path/to/mission_contract.yml
```
