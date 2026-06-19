# Service Factory Model

AgentLab's service factory model maps rough customer intent into a safe production contract:

```text
rough_request
→ service catalog match
→ quote estimate
→ timeline estimate
→ capability plan
→ approval gates
→ delivery package
```

## Relationship to Other AgentLab Stages

- S1 mission compiler identifies task type, risks, unknowns, and required artifacts.
- S2 domain workflows select the production method.
- S7 project brain handles long project continuity.
- S8 executor connector packages work for agents or humans.
- S9 capability fabric checks tool/media/backend availability.
- S10 eval gates prove offline generalization.
- S11 ops console gives the user visibility.
- S12 service factory turns the stack into repeatable services.

## Catalog Entry Schema

```yaml
service_id:
description:
required_capabilities:
default_workflow_template:
estimated_phases:
quality_rubric:
deliverables:
human_approval_points:
risk_notes:
```

## Current MVP Boundary

The S12 MVP does not sell, price in currency, execute external tools, or start paid workflows. It creates deterministic planning and delivery artifacts that can be reviewed before any real execution.
