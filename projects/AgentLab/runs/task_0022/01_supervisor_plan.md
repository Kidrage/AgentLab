# Supervisor Plan

## Task Summary
Implement the AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC v1.0 specification into the AgentLab project. This involves:
1. Creating the spec document at docs/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md
2. Creating 10 role templates under agent_templates/codex_full_driver/
3. Creating config/execution_modes.yml execution mode configuration
4. Creating agent_runtime/codex_artifact_validator.py artifact validator
5. Creating agent_runtime/handoff_builder.py handoff packet builder
6. Creating agent_runtime/api_continuation.py API continuation module
7. Updating agentlab.sh with codex-* CLI commands
8. Updating DRIVER_PROTOCOL.md to define codex_full_driver mode

## Scope Decision
- In scope:
  - All 8 file creation/update tasks listed above
  - Full artifact directory structure: required reports, diffs/, checkpoints/, command_logs/, sync/
- Out of scope:
  - Modifying existing agent_runtime/ core files (except new files)
  - Implementing LangGraph pipeline changes
  - Modifying web_ui/
  - Running the AgentLab API agents (this is a Codex Full-Driver task)

## Route
- Supervisor
- RepoScout
- Researcher: yes — need to confirm spec details
- InterfaceMapper: yes — CLI commands and config schema changes
- CodexPromptGenerator
- Coder
- TesterAuditor
- Archivist

## Allowed Edits
- docs/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md (new)
- agent_templates/codex_full_driver/*.md (new, 10 files)
- config/execution_modes.yml (new)
- agent_runtime/codex_artifact_validator.py (new)
- agent_runtime/handoff_builder.py (new)
- agent_runtime/api_continuation.py (new)
- agentlab.sh (modify)
- DRIVER_PROTOCOL.md (modify)
- projects/AgentLab/runs/task_0022/* (all artifact files)

## Forbidden Edits
- .env
- secrets/
- .git/
- node_modules/
- .venv/
- Existing agent_runtime/* (except the 3 new files)
- config/* (except execution_modes.yml)
- agent_templates/* (only codex_full_driver/ is new)

## Risk Level
Medium — 8 new files, 2 file modifications, structured across multiple directories. No risk to existing functionality since all new files are additive.

## Acceptance Criteria
- [ ] docs/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md exists and matches spec
- [ ] agent_templates/codex_full_driver/ has 10 template files
- [ ] config/execution_modes.yml defines 3 execution modes
- [ ] agent_runtime/codex_artifact_validator.py has validate_artifacts() function
- [ ] agent_runtime/handoff_builder.py has build_handoff_packet() function
- [ ] agent_runtime/api_continuation.py has continue_with_api() function
- [ ] agentlab.sh has codex-start, codex-status, codex-handoff, codex-resume, codex-verify-artifacts, continue-with-api commands
- [ ] DRIVER_PROTOCOL.md documents both codex_coder_only and codex_full_driver modes
- [ ] All task artifacts (reports, diffs, checkpoints) are created

## Stop Conditions
- stop if tests fail in a destructive way
- stop if secrets appear in staged files
- stop if required files are missing
- stop if scope must expand beyond allowed edits

## Next Agent
RepoScout