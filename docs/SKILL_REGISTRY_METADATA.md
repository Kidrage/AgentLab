# Skill Registry Metadata (R2)

## Overview

R2 extends the AgentLab external skill registry with governance-grade metadata.
Each skill record now supports lifecycle management, input/output schemas, quality
tracking, and validation helpers.

## Schema Extensions

### lifecycle_status

Controls where a skill is in its governance lifecycle:

| Status | Description |
|--------|-------------|
| `draft` | Initial registration, not reviewed |
| `candidate` | Proposed for promotion, awaiting review |
| `pending_review` | Under active governance review |
| `staging` | Approved for limited testing |
| `active` | Fully approved and enabled |
| `disabled` | Explicitly disabled |
| `rejected` | Rejected during review |
| `deprecated` | Retired, no longer available |

### inputs / outputs

```yaml
inputs:
  artifacts:
    - text | repo | url | image | pdf | audio | video | screenshot | json | yaml
  context_required:
    - string

outputs:
  artifacts:
    - markdown | json | yaml | patch | report | index | candidate
```

### quality

```yaml
quality:
  success_count: 0
  failure_count: 0
  last_used_at: null
  quality_score: null
```

## Validation Rules

1. **Duplicate skill_id** — rejected on write.
2. **Unknown license** — `license_review_required` is set to true.
3. **External source** — defaults to `enabled: false`.
4. **Active skills** — must have `lifecycle_status: active` AND `enabled: true`.
5. **Pending/staging** — cannot execute via `assert_dispatchable_with_lifecycle`.
6. **Disabled/rejected/deprecated** — cannot execute.

## Registry Summary API

```python
from skills.metadata import build_registry_summary

summary = build_registry_summary(registry)
# summary.total — total skills
# summary.by_lifecycle — count by status
# summary.by_source — count by source
# summary.by_risk_level — count by risk level
# summary.active_skills — list of active skill IDs
# summary.candidates — list of candidate skill IDs
# summary.blocked_or_review_required — list of blocked/review skill IDs
```

## Backward Compatibility

- Existing `schema_version: 1` registry files load without modification.
- R2 fields are added via `enrich_skill_dict()` with sensible defaults.
- Old code using `ExternalSkill` dataclass continues to work unchanged.
- New fields are opt-in for validation (use `validate_skill_metadata()` explicitly).

## Module

`agent_runtime/skills/metadata.py`
