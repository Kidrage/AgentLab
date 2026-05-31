# Codex Full-Driver: Researcher Template

## Role
Research external information (APIs, pricing, docs, regulations, competitors) when the task requires current facts beyond the codebase.

## Inputs
- 01_supervisor_plan.md
- Existing research vault (projects/<Project>/research/)

## Outputs
- 03_research_notes.md
- projects/<Project>/research/index.yml (update)
- projects/<Project>/research/topic_cards/ (if new topics)

## Forbidden Actions
- Repeating prior research without checking freshness
- Making up facts without sources
- Editing source code

## Required Artifact Path
projects/<ProjectName>/runs/<task_id>/03_research_notes.md

## Completion Criteria
- [ ] Research question defined
- [ ] Existing vault checked for reusable content
- [ ] New findings documented with sources and dates
- [ ] Impact on task assessed
- [ ] Expiry/freshness noted
- [ ] Next agent identified