# AgentLab Domain Glossary (CONTEXT.md)

This file defines the canonical domain terminology for AgentLab as an Agent Corporation / OS. These terms are used consistently across all codebases, rules, and synchronization protocols.

---

## Glossary of Terms

### 1. Agent Employee (Agent 雇员)
*   **Definition**: A distinct, registered agent instance (such as Claude Code, Antigravity/Gemini, Hermes, etc.) participating in tasks under the orchestration of AgentLab.
*   **Attributes**:
    *   **Agent ID**: A unique, persistent identifier.
    *   **Budget Ledger**: A tracked token and API cost registry.
    *   **Context Rules**: Specialized `.clinerules` or instructions assigned to their role.

### 2. Agent Workstation (Agent 工作站)
*   **Definition**: The centralized directory inside the AgentLab workspace (`.agents/workspaces/`) where all local Agent CLI configurations, state records, and session history are stored. 
*   **Mechanism**: Symbolic links are placed in the user's home directory pointing to the Workstation directories to ensure seamless CLI operations while keeping state inside the sync-ready codebase.

### 3. Relay Hub (61 中转站)
*   **Definition**: The central information exchange relay server located at IP `10.147.17.61` (TrueNAS host). It acts as the central git and asset sync repository, anchoring the truth across nodes.

### 4. Cloud Office (250 云端办公区)
*   **Definition**: The Cloud Runtime execution environment hosted at IP `10.147.17.250`. It runs heavy test suites, deployments, and containerized executions, syncing its state with the Relay Hub (61).

### 5. Task Sandbox (任务沙箱)
*   **Definition**: An isolated execution directory spawned per task (`projects/<ProjectName>/runs/<task_id>/`) where tool executions and experimental edits take place.

### 6. Three-Tier Artifact Isolation (三层隔离)
*   **Definition**: The compliance rule separating raw execution noise from official deliverables:
    *   *Task Sandbox Area* (raw execution outputs).
    *   *Task Artifact Capture* (verified outputs for the specific task).
    *   *Project Production Area* (cleaned, official project-level index).

### 7. Cost Ledger (费用总账 - 试运营)
*   **Definition**: The centralized ledger file (`cost_ledger.yml`) located in the Task Sandbox that tracks the token consumption and API cost of all participating Agent Employees in a task run.

### 8. Budget Grill (预算增资面试 - 试运营)
*   **Definition**: An interactive session initiated by the Supervisor (Hermes) when the Cost Ledger detects that a task run has breached its pre-allocated budget. The Supervisor pauses execution and interviews the user to decide whether to increase the budget, swap models, or reduce the task scope.

### 9. Auditor Agent (审计雇员 - 试运营)
*   **Definition**: An independent agent role (such as TesterAuditor or Verifier) that performs peer code reviews on a Coder Employee's deliverables to check for code correctness, security compliance, and over-engineering.

### 10. Acceptance Gate (验收网关 - 试运营)
*   **Definition**: The dual-layered compliance gate consisting of (1) automated suite runs (linters, unit tests) and (2) Peer Review by an Auditor Agent. Both must pass before a task is considered completed and cleared for archiving.
