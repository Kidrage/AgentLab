# Phase 2R Node C — structured literary memory

## Verdict

Correction 1 is complete and awaiting independent Standards/Spec re-review.
The first review rejected the implementation for schema-v1 output, hash/parse
TOCTOU reads, repeated source loads, declarative locators and an unsafe output
boundary. Those findings were treated as hard acceptance failures rather than
warnings.

The corrected deep narrative module reads legacy v1 and current v2 selections,
but writes only schema-v2 snapshots. New v2 selections contain no submitted
excerpt: the compiler extracts text from a verified YAML path or bounded line
range using the same bytes it hashes. Each unique source is loaded once, and
malformed, stale, oversized or non-UTF-8 input returns `blocked` without writing.

## Chapter-selection contract

Every current item must declare a category-specific reason, source chapter and
affected characters or concern. The source chapter must lie inside the bounded
five-chapter lookback, and one locator cannot satisfy more than one memory
category. This mechanically validates a narrow, explicit editorial selection;
it does not claim that a program can prove literary relevance.

The five required categories remain voice examples, emotional debts,
life-detail anchors, recent scene signatures and unresolved reader questions.
Missing categories block `quality_equivalent_memory_complete`.

## Crown candidate replay

Committed, excerpt-free recipes for Ch25–Ch27 live under
`acceptance_runs/narrative_efficiency/phase2r_node_c/selections/`. They identify
the exact source path, source hash, locator and relevance declaration. Generated
snapshots remain only under the ignored Crown candidate tree. The content-free
receipt records selection and snapshot hashes, byte counts, full source
inventory, compiler limits and read metrics in
`acceptance_runs/narrative_efficiency/phase2r_node_c/memory_snapshot_metrics.yml`.

All three snapshots contain five distinct categories. Each uses two unique
sources, performs exactly two source reads and reports zero duplicate reloads.

## Safety

- Candidate-only: true
- Production modified: false
- Provider calls: 0
- Production writes: 0
- Output must match
  `projects/<project>/candidates/**/narrative_memory_snapshot.yml`.
- Runtime writes use the atomic I/O helper.
- Selection and source size, count, excerpt and line-window limits are explicit.

## Tests

- Public-interface red tracer reproduced before correction.
- Focused efficiency suite: 54 passed.
- Narrative-domain suite: 194 passed.
- Adversarial coverage includes stale hash, missing categories, unsafe output,
  malformed chapter id, duplicate evidence, old source chapter, item overflow
  and non-UTF-8 source input.
- Full repository regression is deferred until independent re-review accepts
  the correction and the separate live Writer adapter node is complete.

## Quality boundary

The snapshots close a Writer-input contract. They do not prove better prose,
revision uplift or Gate 1 success. Those require the live adapter, external
candidate generation, independent audit and human blind comparison.

## Rollback

Revert the independent Node C commit. Candidate snapshots can be regenerated
from the committed recipes; no Production artifact needs restoration.
