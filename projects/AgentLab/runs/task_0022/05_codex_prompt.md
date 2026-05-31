# Codex Coder Prompt

## Objective
Implement the AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC v1.0 into the AgentLab project. Create all files and templates as specified in the supervisor plan. This is a Codex Full-Driver Coder phase — all file creation and editing must be performed now.

## Read These Files First
- 01_supervisor_plan.md
- 02_reposcout_report.md
- 04_interface_map.md

## Edit Only These Files
1. docs/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md (new — copy from user's attached spec document)
2. agent_templates/codex_full_driver/00_PRE_FLIGHT.md (new)
3. agent_templates/codex_full_driver/01_SUPERVISOR.md (new)
4. agent_templates/codex_full_driver/02_REPOSCOUT.md (new)
5. agent_templates/codex_full_driver/03_RESEARCHER.md (new)
6. agent_templates/codex_full_driver/04_INTERFACE_MAPPER.md (new)
7. agent_templates/codex_full_driver/05_CODEX_PROMPT_GENERATOR.md (new)
8. agent_templates/codex_full_driver/06_CODER.md (new)
9. agent_templates/codex_full_driver/07_TESTER_AUDITOR.md (new)
10. agent_templates/codex_full_driver/08_ARCHIVIST.md (new)
11. agent_templates/codex_full_driver/09_HANDOFF.md (new)
12. config/execution_modes.yml (new)
13. agent_runtime/codex_artifact_validator.py (new)
14. agent_runtime/handoff_builder.py (new)
15. agent_runtime/api_continuation.py (new)
16. agentlab.sh (modify — add 6 codex-* commands)
17. DRIVER_PROTOCOL.md (modify — add codex_full_driver mode)
18. projects/AgentLab/runs/task_0022/ (all required subdirs: diffs/, checkpoints/, command_logs/, sync/)

## Do Not Edit
- .env
- secrets/
- .git/
- node_modules/
- .venv/
- Existing agent_runtime/* (except 3 new Python files)
- Any existing config/* (except execution_modes.yml)
- Any existing agent_templates/* (only new codex_full_driver/ dir)

## Required Implementation Steps
1. Create docs/ directory and write spec document (copy from the user's attached file, stored at Downloads/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md)
2. Create agent_templates/codex_full_driver/ with all 10 template files
3. Create config/execution_modes.yml with 3 execution modes
4. Create agent_runtime/codex_artifact_validator.py with validate_artifacts() function
5. Create agent_runtime/handoff_builder.py with build_handoff_packet() function
6. Create agent_runtime/api_continuation.py with continue_with_api() function
7. Add codex-* command case branches to agentlab.sh
8. Add codex_full_driver mode documentation to DRIVER_PROTOCOL.md
9. Create task artifact subdirectories: diffs/, checkpoints/checkpoint_001_before_coder/, command_logs/, sync/

## Required Reports After Editing
- 06_implementation_report.md
- diffs/post_coder.diff
- command_logs/commands_run.md

## Validation Commands
```bash
# Verify all files exist
ls -la docs/AGENTLAB_CODEX_FULL_DRIVER_OPERATION_CHAIN_SPEC.md
ls -la agent_templates/codex_full_driver/
ls -la config/execution_modes.yml
ls -la agent_runtime/codex_artifact_validator.py
ls -la agent_runtime/handoff_builder.py
ls -la agent_runtime/api_continuation.py

# Verify YAML parses
python3 -c "import yaml; yaml.safe_load(open('config/execution_modes.yml')); print('YAML OK')"

# Verify Python syntax
python3 -m py_compile agent_runtime/codex_artifact_validator.py
python3 -m py_compile agent_runtime/handoff_builder.py
python3 -m py_compile agent_runtime/api_continuation.py
```

## Stop Conditions
- stop if any required file cannot be created
- stop if YAML parse fails
- stop if Python compile fails

## Expected Final Behavior
After this phase, the AgentLab project will have:
- A complete spec document at docs/
- 10 role templates for Codex Full-Driver mode at agent_templates/codex_full_driver/
- 3 Python utility modules for artifact validation, handoff building, and API continuation
- An execution mode config file
- Updated DRIVER_PROTOCOL.md documenting both Codex modes
- Updated agentlab.sh with new CLI commands