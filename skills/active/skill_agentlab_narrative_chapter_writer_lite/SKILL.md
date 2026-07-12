---
name: narrative-chapter-writer-lite
version: 1.0.0
description: "Lightweight longform chapter Writer rules for AgentLab narrative_light_chapter."
---

# narrative-chapter-writer-lite

Use this skill only for the `narrative_light_chapter` route. It is distilled from
`story-long-write`, but it must stay small enough for default per-chapter use.

## Load Only What Can Break The Chapter

Before drafting, read only the minimum authoritative memory:

- `project_brain/project_fact_snapshot.yml`
- `project_artifact_index.yml`
- `chapter_packet.yml`
- the run-local `candidate_fact_ledger.yml` when the packet names one
- previous candidate `continuity_ledger.yml` when the packet names one
- current outline or bible files explicitly listed by `chapter_packet.yml`

Do not use `*_rebuild`, `legacy`, archived drafts, or deprecated Ch1-Ch10
sources unless `project_artifact_index.yml` or `chapter_packet.yml` explicitly
marks them current for this task.

Treat the candidate fact ledger as unpromoted continuity memory. It may guide
the chapter, but it does not override the authoritative fact snapshot.

## Chapter Intent First

Start the Writer report with `chapter_intent`:

- emotional_target
- plot_state_change
- character_state_change
- relationship_or_worldline_progress
- foreshadowing_to_introduce_or_payoff
- timeline_position

Draft prose must fulfill this intent and the beat plan from `chapter_packet.yml`.

## Required Outputs

Write only candidate run artifacts, never production files:

- `fiction_draft.md`
- `continuity_ledger.yml`
- `state_transition_proposal.yml`
- `narrative_delivery_receipt.yml`

`state_transition_proposal.yml` is mandatory for every new setting, revealed
fact, character-state change, relationship change, timeline movement, item
state, or foreshadowing status that should survive into later chapters.

Use these exact version-1 candidate envelopes. Add domain fields where useful,
but do not rename or omit the shown gate fields:

```yaml
# continuity_ledger.yml
schema_version: 1
chapter: 1
baseline_mode: reset # reset for Ch1, continuation otherwise
timeline:
  monotonic: true
  chapter_day: 1
plot_state_changes: []
character_changes: []
relationship_or_worldline_changes: []
foreshadowing: []
```

```yaml
# state_transition_proposal.yml
schema_version: 1
status: candidate
chapter: 1
requires_user_promotion: true
events:
  - event_type: chapter_state_change
    scope: candidate_only
    summary: "Concrete fact proposed by this chapter."
```

```yaml
# narrative_delivery_receipt.yml
schema_version: 1
status: pass # blocked when any required check fails
candidate_only: true
checks:
  chapter_and_title: pass
  required_beats: pass
  continuity_outputs: pass
  production_untouched: pass
  deprecated_sources_excluded: pass
```

The local harness validates these envelopes before accepting any Writer output.
Do not invent a new schema version or use synonyms such as `delivery_status` or
`proposed_transitions` for canonical gate fields.

## Local Checks

Before receipt, run deterministic self-checks in text:

- draft answers the requested chapter number and title
- all required beats from `chapter_packet.yml` are represented or explicitly
  marked unavailable
- plot, character, relationship/worldline, foreshadowing, and timeline changes
  are present in the ledger
- candidate facts are proposed instead of silently promoted
- no production path is modified
- no deprecated source is used as baseline memory

If any check fails, mark the receipt `blocked` and explain the missing artifact
or unresolved continuity issue. Do not call Reviewer/Scribe/Verifier from this
route; heavy audit is a separate route.
