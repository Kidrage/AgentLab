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
write_incubation_artifacts(...)
render_incubation_report(...)
```

Candidates are written only by explicit caller action. P1-A.1 writes task-scoped artifacts:

```text
projects/AgentLab/runs/<task_id>/artifacts/internal_skill_candidates.yml
projects/AgentLab/runs/<task_id>/artifacts/skill_incubation_report.md
```

These runtime artifacts are ignored by git. P1-A.1 does not generate a complete internal skill file. Every candidate marks:

- `source_code_copied: false`
- `human_review_required: true`
- `license_review_required: true` when the external license is unknown or review-required

The report contains candidate id, source skill id, reason, proposed target path,
`source_code_copied: false`, license review, human review, and warnings. It must
not include third-party source code or long external source text.

Run:

```bash
./agentlab.sh external-skills incubate --task-id task_xxx
```
