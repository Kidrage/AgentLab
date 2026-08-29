# Narrative visual detail cards

Every new longform narrative blueprint must produce a hash-sealed
`narrative-visual-detail-card-pack/v1` before prose production begins. The pack
is a candidate artifact: it cannot become canon and it cannot authorize image
generation or project writes by itself.

## Source contract

The source is `narrative-visual-detail-spec/v1` YAML stored under the exact
Task's `inputs/` directory. It contains one or more cards with globally unique
`card_id` values. Supported kinds are:

- `character`: locks facial geometry and features, skin, eyes, hair, body
  proportions, hands/nails, signature details, and negative constraints. Every
  wardrobe/state variant must specify garment construction and materials,
  grooming, manicure, and wear state.
- `map`: locks orientation, scale, geography, terrain, water, settlements,
  routes/borders, labels, palette, and prohibited topology drift.
- `location`: locks architecture, terrain/layout, materials, lighting,
  palette, weather states, and fixed landmarks.
- `prop`: locks geometry/dimensions, materials, finish, mechanism, markings,
  damage, and in-hand scale.

The compiler emits all mandatory views for every variant. The same
`identity_lock_prompt` is copied verbatim into every prompt and has its own
digest. Each prompt and the complete pack are SHA-256 sealed. After the first
reference image is accepted, all later prompts require that exact reference
asset as an image condition; text-only resemblance is not treated as
continuity evidence.

## Execution and review boundary

- High-consistency images: `ArtifactProducer/codex` through the explicit
  `codex_imagegen_handoff`; the compiler is not an auto-executable media
  backend.
- Observation and aesthetic/continuity review: independent Agy Observer and
  Reviewer sessions.
- Hash, receipt, and promotion-boundary verification: a Codex Verifier session
  distinct from the producing session and backend/model pair.
- Human acceptance remains required before any visual reference becomes
  authoritative. Cards and generated images stay candidate-only until then.

This does not reactivate historical Grok/Seedance media routes. If no governed
Codex image surface is explicitly available, generation remains pending while
the prompt pack is still valid and reviewable.

## Commands

```bash
./agentlab.sh narrative compile-visual-cards \
  --project PROJECT \
  --task-id TASK_ID \
  --source projects/PROJECT/runtime/tasks/TASK_ID/inputs/visual-detail-spec.yml

./agentlab.sh narrative validate-visual-cards \
  --pack-path projects/PROJECT/runtime/tasks/TASK_ID/artifacts/visual_detail_cards/versions/SHA/visual_detail_card_pack.yml
```

Materialization writes an immutable version, a receipt, and a small candidate
index. Chapter context should normally carry only the candidate index and the
specific cards used by that chapter, not the full historical prompt pack.
