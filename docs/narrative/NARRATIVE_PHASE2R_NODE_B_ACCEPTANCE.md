# Phase 2R Node B — Writer packet preview review

## Verdict

Not accepted. Independent Standards and Spec review rejected the first Node B
claim: its custom packet was not the registered Writer envelope, the measurement
omitted the root word-count contract and current Writer template, detailed Crown
content was committed as evidence, Writer bytes included other role slices, and
the production boundary was declarative rather than enforced.

Correction 1 closes those false-greens. The provider-free preview now uses the
schema-v2 `agentlab_sealed_role_session` envelope, rejects any output beneath the
project Production directory before compilation, measures only shared plus Writer
records, inherits the source plan's character ranges, and includes the current
prose-only Writer template.

The corrected Ch25–Ch27 input-only preview has a median 62,448-byte payload,
versus the frozen legacy median 100,218 bytes: a 37.69% reduction. This is useful
engineering evidence, but it is not Phase 2R acceptance.

## Remaining blockers

- The registered live Writer path does not yet consume this compiled packet.
- There is no structured, chapter-selected `narrative_memory_snapshot.yml` for
  voice examples, emotional debts, life-detail anchors, recent scene signatures,
  and unresolved reader questions.
- No provider output or blind review has established quality equivalence.

Until those gaps close, `quality_equivalent_comparison_available` and
`phase_acceptance_met` remain false.

## Reproduction and safety

Run:

```bash
PYTHONPATH=agent_runtime:. python -m \
  agent_runtime.narrative.production.writer_packet_measurement \
  acceptance_runs/narrative_efficiency/phase2r_node_b/frozen_inputs.yml \
  --repository-root .
```

The command verifies every declared source hash and derives chapter-local brief
sources only below the ignored Crown candidate tree. Checked-in evidence contains
paths, selectors, sizes, and hashes—not manuscript text. Provider calls and
Production writes are both zero.

## Evidence

- Inputs: `acceptance_runs/narrative_efficiency/phase2r_node_b/frozen_inputs.yml`
- Metrics: `acceptance_runs/narrative_efficiency/phase2r_node_b/preview_metrics.json`
- Driver: `agent_runtime/narrative/production/writer_packet_measurement.py`
- Tests: the Writer preview and frozen-measurement cases in
  `tests/test_narrative_efficiency.py`
- Independent Standards review: pass after Correction 1.
- Independent Spec review: preview implementation passes; Node B remains
  blocked on the two product requirements above.
- Focused efficiency suite: 45 passed.
- Narrative-domain suite: 184 passed.
- Full repository: 2,908 passed, 2 skipped, 0 failed, 11 warnings in 326.30s.

## Rollback

Revert the Node B commit. Local derived sources are candidate-only and can be
regenerated; no manuscript or Production artifact requires restoration.
