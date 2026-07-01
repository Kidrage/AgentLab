# M-Series Scope

Last updated: 2026-06-30

This document freezes the M-series repair scope so future stages can advance
without mixing governance, operator control, and business/productization work.

Current handoff note: the latest planning discussion uses M2 for the remaining
long-project governance hardening, M3 for Operator OS / Transparent Control
Plane, and M4 for Project-to-Revenue OS. See:

- `docs/M2_STABLE_BASELINE_REPAIR_PLAN.md`
- `docs/M3_0_OPERATOR_OS_ALIGNMENT.md`
- `docs/M3_UPGRADE_PLAN_REVIEW.md`

The older labels below remain as historical repository milestone names.

Active repair labels:

| Label | Current repair meaning |
| --- | --- |
| M2 | Long-Project Governance Stable Baseline |
| M3 | Operator OS / Transparent Control Plane |
| M4 | Project-to-Revenue OS |

## Positioning

AgentLab is a local-first AI Production OS and Project-to-Revenue OS in staged
development. It is the backend truth source for project memory, task state,
capabilities, evidence, approvals, recovery, acceptance, and delivery packages.

AgentLab is not a direct replacement for Codex, Claude Code, Cline, Hermes,
OpenClaw, or other executor/front-end agents. Those systems remain possible
executors or control surfaces. AgentLab coordinates and verifies their work.

## M1: Project Governance Kernel

M1 is about long-running project governance.

M1 includes:

- External project registry and capability mapping.
- Mission Compiler v2.
- Project Workflow Templates v2.
- Project Brain consolidation.
- Executor Connector Loop consolidation.
- Document / Code / Media ingestion contracts.
- Phase Acceptance consolidation.
- Recovery / Replanning v2.
- Context Compression v1.
- Offline generalization demos.

M1 does not include:

- UI polish.
- Full TUI.
- Heavy WebUI.
- Business/revenue model.
- CRM.
- Payment, invoicing, or legal contract automation.
- Real platform posting.
- Real social media crawling.
- Automatic external skill installation.
- Uncontrolled browser automation.
- Real autonomous video generation calls.

## M2: Operator OS / Transparent Control Plane

M2 is about operator control, transparency, observability, and cost visibility.

M2 includes:

- Config Center.
- Cost System v2.
- Event Timeline / Observability.
- TUI.
- WebUI.
- AgentLab Assistant Modes.
- Skill / Capability / Executor Control Panel.
- Operator Acceptance Demo.

M2 does not include:

- Business/revenue automation.
- CRM/client delivery loops.
- Platform growth automation.
- Unsafe external execution.
- Automatic skill installation.
- Automatic public server exposure.

CLI remains the primary reliable control surface. TUI and WebUI must be optional.

## M3: Project-to-Revenue OS

M3 is about asset, production, channel, revenue, compliance, client, and SOP
loops.

M3 includes:

- Business Contract.
- Asset Registry + Lineage.
- Production Pipeline Templates.
- Market / Channel Intelligence.
- Analytics + Revenue Ledger.
- Compliance / Risk Brain.
- CRM / Client Delivery Loop.
- SOP / Skill Factory 2.0.
- End-to-end Project-to-Revenue demo projects.

M3 does not include:

- Unsafe platform automation.
- Login-walled or paywalled scraping.
- Spam, fake engagement, policy evasion, or bulk abuse.
- Automatic posting/uploading to real platforms.
- Automated payments or legally binding contract execution.

## Global Safety Boundary

Across M1, M2, and M3:

- No automatic external tool execution.
- No automatic skill installation.
- No automatic MCP server launch.
- No automatic dependency installation.
- No public bind by default.
- No secrets in project memory, artifacts, handoffs, or reports.
- No accepting external executor results without evidence and review.
- Network, shell, write, browser, account, and external capabilities require
  explicit policy and scoped approval.

## Version Milestones

- `v0.7 Project Kernel`: long-project governance kernel complete.
- `v0.8 Operator OS`: transparent control plane complete.
- `v0.9 Internal Closed Loop`: M1-M3 integrated and hardened.
- `v1.0 Local-first AI Production OS`: M1-M3 stabilized, documented,
  demo-ready, and release-quality as the M4 Project-to-Revenue starting point.

v1.0 is not the M4 commercial layer. Project-to-Revenue work starts after the
internal closed loop is stable.
