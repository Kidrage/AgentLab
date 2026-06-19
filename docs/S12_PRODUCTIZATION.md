# S12 Productization and Service Factory

## Purpose

S12 turns AgentLab into a demonstrable local-first service factory. A rough customer request is matched to a service catalog entry, then converted into quote, timeline, risk, and delivery package artifacts.

## CLI

```bash
./agentlab.sh service-factory-plan \
  --prompt '客户想做一个本地文件整理助手，给报价、周期和交付方案。' \
  --out acceptance_runs/s12_productization/service_factory_demo
```

Generated artifacts:

- `service_match.yml`
- `quote_estimate.yml`
- `timeline_estimate.yml`
- `delivery_package/final_summary.md`
- `delivery_package/acceptance_history.md`
- `delivery_package/risks_and_limitations.md`
- `delivery_package/reproduction_commands.md`
- `delivery_package/next_steps.md`
- `delivery_package/artifacts/`
- `delivery_package/evidence/`

## Service Catalog

Configuration lives in `config/service_catalog.yml` and includes at least these service types:

- repo_cleanup
- bug_fix_plan
- longform_novel_blueprint
- company_research_report
- document_summary
- spreadsheet_cleanup
- local_file_organization
- audio_analysis_plan
- multimodal_review
- personal_automation_workflow

Each service declares:

- service_id
- description
- required_capabilities
- default_workflow_template
- estimated_phases
- quality_rubric
- deliverables
- human_approval_points
- risk_notes

## Quote and Timeline

The estimator is deterministic and local-only. It uses service phase count, requested complexity, risk notes, and human approval count to assign a quote band and timeline shape. It does not price with external APIs and does not execute the service.

## Delivery Package

The delivery package is a reproducible skeleton for final handoff. It separates final summary, acceptance history, risks, reproduction commands, next steps, artifacts, and evidence.

## Safety Notes

- No private paths in generated YAML.
- No external execution.
- No network calls.
- No automatic capability install.
- Real project execution remains gated by mission/workflow/capability/executor approval.
