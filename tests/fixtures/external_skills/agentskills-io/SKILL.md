---
name: agentskills-io
description: >
  AgentSkills.io canonical external skill for validating AgentLab's
  allowlisted URL import lifecycle, skill retrieval, injection,
  and usage ledger closure.
version: 1.0.0
license: MIT
author: OpenClaw Skill Maintainers
homepage: https://github.com/openclaw/skills
tags:
  - agent-skills
  - external-skill
  - canonical
  - mvp-fixture
---

# AgentSkills.io

This fixture mirrors the canonical external live smoke skill identity
(openclaw/skills/killerapp/agentskills-io) without requiring network
access. It is used only to validate AgentLab's import, approval,
staging, validation, promotion, retrieval, injection, and usage ledger
closure. The fixture does not execute external code.

## Task Fit

Use this skill when a task mentions agent skills, skill discovery,
skill import, or external skill lifecycle validation.

## Safety

- No commands are executed by AgentLab during import.
- The imported source is stored as a source snapshot for review.
- Promotion follows the normal approval and fake validation lifecycle.