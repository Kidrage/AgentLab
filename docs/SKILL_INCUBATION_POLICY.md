# Skill Incubation Policy

External skills may become unavailable, paid, closed-source, or risky. AgentLab therefore tracks useful external skills and proposes internal skill candidates based on repeated successful use. The goal is to summarize workflows and checklists, not copy external source code.

`config/skill_incubation_policy.yml` defines:

- budget caps for incubation per task
- trigger thresholds such as successful use count and quality score
- allowed outputs: summaries, candidates, checklists, adapter notes, risk notes
- forbidden outputs: copied source code, incompatible license text, secrets, private tokens
- mandatory human review

`agent_runtime/skills/incubation.py` implements:

```python
propose_internal_skill_candidates(registry, usage_ledger, policy, task_context=None)
```

Candidates are written as `internal_skill_candidates.yml` only by explicit caller action. P1-A does not generate a complete internal skill file. Every candidate marks:

- `source_code_copied: false`
- `human_review_required: true`
- `license_review_required: true` when the external license is unknown or review-required
