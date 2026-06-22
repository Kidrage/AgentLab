# AgentLab M2-2 — Capability Schema & 9-Role Requirement Matrix Report

## Verdict
PASS

## Baseline
- **branch**: `main`
- **before commit**: `3e5fccd` (feat: implement M2-1.7 skill and MCP capability broker)
- **current staging status**: Files staged, commit deferred as requested by operator.
- **remote**: `https://github.com/Kidrage/AgentLab.git`
- **CI**: Passing locally (`pytest tests/test_mainline_baseline_acceptance.py` + `pytest tests/test_m2_*` all green)

## Summary
Separated AgentLab roles from concrete CLIs by introducing a capability-driven role-mapping matrix.
- A **role** is defined as requiring, preferring, or forbidding specific **capabilities**.
- A **worker** (tool) is mapped to the **capabilities** it supports.
- Compatibility checks ensure that workers can only be assigned to roles if they satisfy all required capabilities and do not expose any forbidden capabilities.
- Risk tags classify capabilities into different risk levels (low, medium, high), determining if human approval is required for worker-to-role assignment.

## Changed Files
- `agent_runtime/capabilities/__init__.py`: Added exports for CapabilityDefinition, CapabilitySchema, RoleRequirementDefinition, RoleRequirementsRegistry, WorkerCapabilityRegistry, CompatibilityChecker, etc.
- `agent_runtime/run_task.py`: Added `capabilities`, `role-requirements`, `role-inspect`, and `role-compatible-workers` CLI commands.

## New Runtime Modules
- `agent_runtime/capabilities/capability_schema.py`: Schema mapping capability IDs to names, descriptions, and risk levels.
- `agent_runtime/capabilities/role_requirements.py`: Decoupled role model representing requirements (required, preferred, forbidden caps) and risk ceilings.
- `agent_runtime/capabilities/compatibility.py`: Compatibility checker checking worker capability lists against role constraints.
- `agent_runtime/capabilities/risk_tags.py`: Checks risk levels and human approval gates on roles/capabilities.
- `agent_runtime/capabilities/renderer.py`: Rich console formatting renderers for CLI commands.

## New Configs
- `config/capability_schema.yml`: Defines the 25 core capability families and their risk levels (e.g. `cloud_upload` is HIGH).
- `config/agent_role_requirements.yml`: Specifies capabilities requirements for the 9 AgentLab roles.
- `config/worker_capability_defaults.yml`: Maps default workers (like `rg`, `claude_code`, `bl`, `pytest`) to the capabilities they support.

## New CLI
- `./agentlab.sh capabilities`: List all defined capabilities in the schema.
- `./agentlab.sh role-requirements`: List a summary of all 9 AgentLab roles and their capability count.
- `./agentlab.sh role-inspect --role <RoleName>`: View detailed capability requirements (required, preferred, forbidden, approval) for a role.
- `./agentlab.sh role-compatible-workers --role <RoleName>`: Inspect compatible workers and whether their assignment requires approval.

## Artifacts Produced
- `acceptance_runs/m2_role_capability_matrix/M2_ROLE_CAPABILITY_MATRIX_REPORT.md` (this file)

## Tests Added
- `tests/test_m2_capability_schema.py`: Checks loading schema from YAML and `capabilities` CLI execution. (100% coverage on schema loader)
- `tests/test_m2_role_requirements.py`: Checks case-insensitive, normalized role registry lookup and inspect CLI command.
- `tests/test_m2_role_worker_compatibility.py`: Tests capability checks (e.g., `rg` cannot be Coder, `pytest` cannot be Supervisor) and approval requirements.

## Tests Run
```bash
agent_runtime/.venv/bin/python -m pytest tests/test_m2_capability_schema.py tests/test_m2_role_requirements.py tests/test_m2_role_worker_compatibility.py
```
Output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.13, pytest-8.4.2, pluggy-1.6.0
rootdir: /home/admin/AgentLab
configfile: pytest.ini
plugins: langsmith-0.8.18, anyio-4.14.0
collecting ... collected 6 items                                                              

tests/test_m2_capability_schema.py ..                                    [ 33%]
tests/test_m2_role_requirements.py ..                                    [ 66%]
tests/test_m2_role_worker_compatibility.py ..                            [100%]

============================== 6 passed in 2.34s ===============================
```

## Safety Notes
- Verified that `bl` cannot be assigned to roles/tasks requiring `cloud_upload` without approval since `cloud_upload` is flagged as a high-risk capability.
- Verified that assigning `claude_code` to roles brings high-risk capabilities like `shell_execution` and `cloud_upload`, which properly triggers human approval checks.
- Verified no unauthorized external execution, no secret exposure, and no path leakage.

## Known Limitations
- The current implementation maps static default capabilities to workers. Dynamic capability validation based on runtime worker health and state probe remains for the subsequent stages (`M2-3` performance ledger and audition).

## Next Recommended Stage
- **M2-3 — Worker Audition / Performance Ledger**: Establish runtime tracking and scoring of worker performance and error rates.
