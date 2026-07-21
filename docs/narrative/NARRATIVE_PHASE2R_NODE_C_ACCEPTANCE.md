# Phase 2R Node C — structured literary memory

## Verdict

Accepted. Correction 3 passed both independent Standards and Spec review after
the resumed independent reviews rejected
commit `05e9ecf` and the Standards correction-2 re-review found two narrower
boundary seams. Full repository regression is green.
The first review rejected the implementation for schema-v1 output, hash/parse
TOCTOU reads, repeated source loads, declarative locators and an unsafe output
boundary. Those findings were treated as hard acceptance failures rather than
warnings.

The resumed review then rejected remaining authority seams: caller-stated source
chapters were not bound to source metadata, sources and output were not bound to
one explicit project, and distinct locators could reuse identical text or
overlapping line ranges. Malformed path-like inputs could also escape before the
guarded resolver. Correction 2 adds explicit project identity, derives source
chapters from source paths or located YAML nodes, blocks mismatches, normalizes
text reuse, detects overlapping source ranges and returns `blocked` for
unresolvable paths.

The correction-2 Spec review passed, but the Standards replay showed that
conflicting YAML ancestor/node chapter metadata fell back to a chapter-looking
filename, and an already-rejected outside-root selection was still read before
the compiler returned `blocked`. Correction 3 treats conflicting authorities as
an explicit veto and performs no selection I/O after the root-boundary check
fails, including a resolved symlink escape.

The corrected deep narrative module reads legacy v1 and current v2 selections,
but writes only schema-v2 snapshots. New v2 selections contain no submitted
excerpt: the compiler extracts text from a verified YAML path or bounded line
range using the same bytes it hashes. Each unique source is loaded once, and
malformed, stale, oversized or non-UTF-8 input returns `blocked` without writing.

## Chapter-selection contract

Every current item must declare a category-specific reason, source chapter and
affected characters or concern. The source chapter must lie inside the bounded
five-chapter lookback and equal chapter metadata derived from the source path or
located YAML node. Sources and output must belong to the requested project.
Identical normalized text or overlapping line ranges cannot satisfy more than
one memory category. This mechanically validates a narrow, explicit editorial selection;
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

All three correction-3 replays preserve their prior snapshot hashes and contain five distinct categories. Each uses two unique
sources, performs exactly two source reads and reports zero duplicate reloads.

## Safety

- Candidate-only: true
- Production modified: false
- Provider calls: 0
- Production writes: 0
- Output must match
  `projects/<requested_project>/candidates/**/narrative_memory_snapshot.yml`.
- Runtime writes use the atomic I/O helper.
- Selection and source size, count, excerpt and line-window limits are explicit.

## Tests

- Public-interface red tracer reproduced before correction.
- Focused efficiency suite: 62 passed.
- Extended narrative-domain suite: 208 passed.
- Full repository: 2,974 passed, 2 skipped, 0 failed, 11 warnings in
  235.27 seconds.
- Adversarial coverage includes stale hash, missing categories, unsafe output,
  malformed chapter id, duplicate evidence, old source chapter, item overflow
  and non-UTF-8 source input.
- Correction-2 adversarial coverage adds malformed paths, cross-project source
  and output attempts, forged source chapters, duplicate text under distinct
  YAML keys and overlapping line ranges.
- Correction-3 coverage adds conflicting root/located-node YAML chapter
  authorities and proves an outside-root selection has zero reads and zero
  loaded bytes.
- Independent Standards review: pass.
- Independent Spec review: pass.

## Quality boundary

Node C closes the structured-memory input contract. It does not prove better prose,
revision uplift or Gate 1 success. Those require the live adapter, external
candidate generation, independent audit and human blind comparison.

## Rollback

Revert the independent Node C commit. Candidate snapshots can be regenerated
from the committed recipes; no Production artifact needs restoration.
