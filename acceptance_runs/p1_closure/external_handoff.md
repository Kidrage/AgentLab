# External Agent Handoff

**Task ID:** p1_closure_acceptance
**Handoff ID:** handoff_p1_closure_acceptance_cline_codex_20260613_151004_b5c9fb54
**Project:** AgentLab
**Created At:** 2026-06-13T15:10:04.186817+00:00

## Target Executor
- **Agent ID:** cline_codex
- **Display Name:** Cline with Codex Subscription
- **Type:** ide_agent
- **Integration Mode:** handoff_only
- **Enabled:** False
- **Status:** proposed

## Objective
**Title:** Review a small local repo and prepare an external handoff plan
**Summary:** Task summary: local fake repo only. [REDACTED_SECRET] [REDACTED_SECRET]

## Task Summary
Task summary: local fake repo only. [REDACTED_SECRET] [REDACTED_SECRET]

## Repository Context
- Local checkout context only; do not clone remote repositories.
- Allowed files and forbidden files must be confirmed before editing.

## Acceptance Criteria
- Provide implementation or review evidence without exposing secrets.
- Do not execute external tools automatically from AgentLab.
- Do not misuse external subscriptions, API keys, or private credentials.

## Constraints
- Do not auto-run external tools from AgentLab.
- Do not full clone remote repositories unless explicitly approved.
- Do not install dependencies without approval.
- Do not copy third-party source code.
- Do not expose secrets, API keys, OAuth tokens, or subscription credentials.
- Return changed files, commands run, evidence artifacts, and residual risks.

## Required Outputs
- implementation_summary
- changed_files
- tests_run
- evidence_artifacts
- residual_risks
- cost_notes

## Evidence Requirements
- **require_changed_files:** True
- **require_test_summary:** True
- **require_execution_log_or_external_unverified_marker:** True
- **require_no_secret_leak:** True
- **require_residual_risks:** True

## Budget
- **Billing Mode:** subscription_quota
- **API Cost Visible:** False
- **Token Visibility:** unknown
- **Expected Agentlab API Cost (USD):** None

## Skill Context
- ecc.planner
- ecc.code-reviewer

## How to submit result back to AgentLab

1. Complete the assigned task following all constraints.
2. Record all changed files, commands run, and artifacts produced.
3. Prepare a result YAML file with the required outputs listed above.
4. Run the following command to submit your result:

```bash
./agentlab.sh external-agents submit-result --task-id p1_closure_acceptance --handoff-id handoff_p1_closure_acceptance_cline_codex_20260613_151004_b5c9fb54 --result-file path/to/result.yml
```

**Note:** AgentLab does NOT automatically execute external agents.
You must manually perform the work and submit results.
