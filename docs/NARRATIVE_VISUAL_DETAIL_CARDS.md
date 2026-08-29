# Narrative visual detail cards

Every new longform narrative blueprint must produce a hash-sealed
`narrative-visual-detail-card-pack/v3` before prose production begins. The pack
is a candidate artifact: it cannot become canon and it cannot authorize image
generation or project writes by itself.

## Source contract

The source is project-bounded `narrative-visual-detail-spec/v3` YAML. The CLI
creates or reuses an exact Runtime-v2 Task bound to `narrative.visual.v1`; a
deterministic Attempt verifies the declared source hash and all transitive
source hashes before recording the pack as an immutable ArtifactVersion. A
directory by itself is never accepted as a Task or as production evidence.
The spec contains a `creative_policy` with the work title and an explicit
`female_modern_nail_art_allowed` boolean, plus one or more cards with globally
unique `card_id` values. Version 1 and version 2 packs are historical evidence:
their sealed packs retain version-specific read-only rebuild validators so an
already-ledgered Task remains auditable, but they cannot release image jobs,
accept a new identity reference, or satisfy the prose prerequisite. The compiler
never creates a new v1/v2 pack; production requires version 3. A version 3 pack
also reconstructs and verifies its canonical source-spec hash and source-ref
manifest, while the runtime recompiles the Task-declared spec before releasing
production work.
Supported kinds are:

- `character`: branches on an explicit `gender` value. Both branches lock
  structured facial geometry, brows, eyes/iris/eyelids, nose, lips, ears,
  distinguishing marks, skin, hair colour, hair texture/parting/style,
  hair-accessory material and placement, body proportions, hands, signature
  details, and negative constraints. Every wardrobe/state variant also locks
  its front/back hairstyle and accessory condition.
- Female character cards additionally require a structured makeup identity,
  makeup per state, leg proportions/musculature/skin/marks, foot shape/arch/toe
  arrangement/skin/marks, and per-variant hand and foot nail art. Each manicure
  and pedicure records style, length, shape, base and accent colours, finish,
  design, embellishments, and condition. When the work policy allows it,
  modern French, gradient, cat-eye, jelly, chrome, aurora, marble, magnetic,
  mirror, and similar nail-art language is intentional rather than treated as
  accidental modernization.
- Male character cards use a hand-only detail shot. Their hand description is
  a closed structured profile: hand proportion, joints, callus pattern, marks,
  dominant hand, and optional governed hand armor are selected from versioned
  values and expanded by the compiler. Free-form male hand prose and explicit
  nail/manicure/pedicure language elsewhere in the card are rejected. Hand
  reference poses use a separate governed `hand_pose`; a bounded cross-field
  semantic guard rejects nail-like combinations of digit/quantity, keratinous
  material, trimming, finish, and colour while allowing ordinary martial,
  merchant, and political prose such as pointing, `掌门`, `掌柜`, `高手`, and
  `铁腕`. Pointing, writing, weapon handling, and segmented iron hand armor
  remain explicitly representable through governed values. `hand_pose`
  controls the visual reference pose; ordinary narrative state/action prose
  remains descriptive and is not treated as a deterministic action classifier.
  Downstream shot planning selects the appropriate governed pose instead of
  inferring one from an open-ended prose vocabulary.
- `map`: locks orientation, scale, geography, terrain, water, settlements,
  routes/borders, labels, palette, and prohibited topology drift.
- `location`: locks architecture, terrain/layout, materials, lighting,
  palette, weather states, and fixed landmarks.
- `prop`: locks geometry/dimensions, materials, finish, mechanism, markings,
  damage, and in-hand scale.

The compiler emits gender-appropriate mandatory views for every variant.
Female sheets include calibrated makeup, hair, hand manicure, leg, and bare-foot
pedicure views; male sheets include facial-feature, hair, and hand-structure
views without nail detail. The same
`identity_lock_prompt` is copied verbatim into every prompt and has its own
digest. Each prompt and the complete pack are SHA-256 sealed. After the first
reference image is accepted, all later prompts require that exact reference
asset as an image condition; text-only resemblance is not treated as
continuity evidence.

## Execution and review boundary

- Workers, invocation contracts, models, providers, and fallbacks are resolved
  from the current default mode/tier in `config/agent_model_profiles.yml`; the
  card pack stores only authority-backed profile keys.
- High-consistency generation resolves `artifact_producer` and must resolve to
  Codex before the managed `image_gen.imagegen` handoff is released. The
  compiler is not an auto-executable media backend.
- Observation and aesthetic/continuity review resolve `observer` and
  `visual_reviewer`; producer self-check resolves `artifact_producer` but never
  counts as independent acceptance.
- Hash, receipt, and promotion-boundary verification resolves `verifier` in a
  session distinct from the producer and independent reviewers.
- Missing, retired, or changed role bindings block the batch; the workflow
  never silently substitutes a worker or model.
- Human acceptance remains required before any visual reference becomes
  authoritative. Cards and generated images stay candidate-only until then.

This does not reactivate historical Grok/Seedance media routes. If no governed
Codex image surface is explicitly available, generation remains pending while
the prompt pack is still valid and reviewable.

## Commands

```bash
./agentlab.sh narrative compile-visual-cards \
  --project PROJECT \
  --task-id VISUAL_TASK_ID \
  --source-blueprint-task-id BLUEPRINT_TASK_ID \
  --source projects/PROJECT/runtime/tasks/BLUEPRINT_TASK_ID/inputs/visual-detail-spec.yml

./agentlab.sh narrative validate-visual-cards \
  --pack-path projects/PROJECT/runtime/tasks/VISUAL_TASK_ID/artifacts/versions/VERSION_ID/payload.yml

# First identity sheet: no reference receipt.
./agentlab.sh narrative compile-visual-generation-batch \
  --pack-path projects/PROJECT/runtime/tasks/VISUAL_TASK_ID/artifacts/versions/VERSION_ID/payload.yml \
  --card-id CARD_ID

# After the Codex managed image tool returns, import the real image only with
# the external managed-tool authority's exact signed result attestation.
./agentlab.sh narrative ingest-visual-identity-reference \
  --pack-path projects/PROJECT/runtime/tasks/VISUAL_TASK_ID/artifacts/versions/VERSION_ID/payload.yml \
  --card-id CARD_ID \
  --image-path /PATH/TO/GENERATED_IMAGE.png \
  --attestation-path /PATH/TO/MANAGED_TOOL_ATTESTATION.yml

# Dependent shots: exactly one current signed reference receipt.
./agentlab.sh narrative compile-visual-generation-batch \
  --pack-path projects/PROJECT/runtime/tasks/VISUAL_TASK_ID/artifacts/versions/VERSION_ID/payload.yml \
  --card-id CARD_ID \
  --reference-acceptance-receipt projects/PROJECT/runtime/tasks/REFERENCE_TASK/approvals/CARD_ID.yml
```

The deterministic hash gate is recorded automatically from the successful
projector Attempt. The Task remains `waiting_review` on the separate human
visual-bible gate; the pack cannot pass that gate merely because its own hash
validates. Every `narrative.chapter.v1` Task must name this exact visual Task,
ArtifactVersion, path, and SHA-256, so prose execution fails before an Attempt
if the visual prerequisite is absent or drifted.

The ingest command is the sole public bridge from the managed image tool into
the reference protocol. It validates PNG/JPEG/WebP bytes, the image hash,
prompt hash, Task/Attempt/ArtifactVersion identity, Codex session,
provider/model, tool-result ID, and the workspace-external signature before
starting an Attempt. It then records a real `image/*` ArtifactVersion and the
`managed_imagegen_attested` gate. A text RoleAttempt output or a hand-written
receipt cannot substitute for this bridge.

## Reference-first image production

For each card, the first generation batch contains only the identity-reference
sheet. Dependent poses, costumes, states, maps, location reverses, and prop
details are not released until the deterministic per-card
`narrative.visual.reference.v1` Task has selected one eligible image
ArtifactVersion and the accepted reference receipt binds all of the following
to the exact visual-pack Task, pack ArtifactVersion, pack hash, and card:

- the real project-local image path and SHA-256;
- the identity-reference prompt SHA-256;
- the resolved producer backend/model/session evidence from a successful
  Runtime-v2 Attempt that used the managed Codex image tool and produced the
  exact image ArtifactVersion;
- a workspace-external, pinned managed-tool authority signature over the exact
  Task, Attempt, ArtifactVersion, card, prompt, output image, session,
  provider/model, and tool-result ID; worker-authored labels alone are not
  accepted as imagegen proof;
- separate producer self-check, Observer, visual Reviewer, and Verifier
  evidence with independent session IDs, each matching its current profile;
- immutable Attempt and model-receipt hashes for generation, observation,
  review, and verification; every review Attempt must seal the exact immutable
  image ArtifactVersion as its source;
- machine-validated review output in which identity, wardrobe/state,
  spatial/scale, and prompt/asset integrity dimensions each contain evidence
  and pass with no blocking issue;
- an exact human acceptance over the same pack, card, prompt, image, and
  Runtime-v2 evidence digest, verified against the project's pinned public key
  and an external signature.
- passed `managed_imagegen_attested`, `independent_visual_acceptance`, and
  `human_identity_reference_acceptance` protocol gates, with all five
  reference-task WorkItems accepted against the selected image version.

Every dependent image job carries exactly one current accepted image path/hash
and the acceptance-receipt file/content hashes as input conditions. The
reference Task ID is derived from project, visual Task, and card ID, so a
caller cannot create a second current-reference namespace. Superseding a
reference changes the Task's selected ArtifactVersion and immediately makes
the old receipt ineligible. A symbolic asset name, a caller-supplied list, or a
text-only resemblance prompt is insufficient. Generated files remain
candidate-only and still pass through the repository's independent visual
acceptance workflow before any external promotion.

Chapter context should normally carry only the selected card IDs, prompt
digests, accepted reference hashes, and current visual-state deltas. It should
not include the complete historical prompt pack or all prior image evidence.
