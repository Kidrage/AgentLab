# External Agent Handoff Protocol

## Overview
This document outlines the protocol for creating and managing external agent handoffs in the AgentLab system. The protocol ensures proper documentation, validation, and tracking of external agent interactions.

## Handoff Creation Process

### 1. Prerequisites
- External agent must be registered in `config/external_agents.yml`
- Agent must be disabled (status=proposed) to prevent automatic execution
- User must explicitly trigger the handoff creation

### 2. Handoff Artifact Structure
The handoff process generates two key artifacts:
- `external_handoff.yml` - Machine-readable YAML format
- `external_handoff.md` - Human-readable documentation

### 3. Handoff Data Model
```yaml
handoff_id: "handoff_20260612_235959"
task_id: "task_0035"
project: "AgentLab"
target:
  agent_id: "cline_codex"
  agent_type: "ide_agent"
  integration_mode: "handoff_only"
  enabled: false
  status: "proposed"
objective:
  title: "Implement feature X"
  summary: "Description of the task to be performed by the external agent"
constraints: []
required_outputs: []
budget:
  billing_mode: "subscription_quota"
  api_cost_visible: false
  external_token_visibility: "unknown"
evidence_requirements: []
```

## Key Constraints

### 1. Agent Configuration
- Only agents with `integration_mode: handoff_only` can be used
- Disabled agents can only create handoffs with status=proposed
- Token visibility must always be "unknown"

### 2. Artifact Management
- Handoff artifacts must be written to task run directories
- No direct repository modifications allowed during handoff creation
- All handoffs must be recorded in the external agent ledger

### 3. Security Requirements
- No API keys or credentials stored in artifacts
- No automatic execution of external agents
- All handoffs require explicit user trigger

## Artifact Validation

### 1. Handoff Validation
- Must validate agent registry configuration
- Must verify agent is disabled before creating proposed handoffs
- Must maintain consistency between YAML and markdown formats

### 2. Evidence Requirements
- Changed files must have corresponding command execution or artifact evidence
- Build/test claims require verification through execution evidence
- Missing evidence results in warning/failure status

## Integration with Task Management
- All handoffs must be recorded in task events
- Ledger updates must occur for each handoff and result submission
- Skill usage must be tracked in the skill usage ledger