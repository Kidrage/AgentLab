---
name: printkk-print-on-demand
description: >
  PrintKK print-on-demand workflow skill for validating an external
  SKILL.md import package through AgentLab's allowlisted URL lifecycle.
version: 1.0.0
license: MIT
author: PrintKK Skill Maintainers
homepage: https://github.com/pizzzzzza/printkk-agent-skill
tags:
  - print-on-demand
  - ecommerce
  - product-design
  - external-skill
---

# PrintKK Print On Demand

This fixture mirrors the canonical external live smoke skill identity without
requiring network access. It is used only to validate AgentLab's import,
approval, staging, validation, promotion, retrieval, injection, and usage ledger
closure. The fixture does not execute external code.

## Task Fit

Use this skill when a task mentions PrintKK, print on demand, ecommerce product
design, product publishing, or order automation.

## Safety

- No commands are executed by AgentLab during import.
- The imported source is stored as a source snapshot for review.
- Promotion follows the normal approval and fake validation lifecycle.
