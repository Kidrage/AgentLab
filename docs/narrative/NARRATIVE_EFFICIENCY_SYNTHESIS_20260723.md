# Narrative Efficiency Synthesis — 2026-07-23

## Decision

Use the existing candidate-only Crown background delivery controller with a
10-chapter batch and one full-window heavy audit. Keep one Writer candidate per
ordinary chapter, deterministic chapter checks, one primary batch Reviewer, and
additional judges only for chapters carrying explicit risk signals.

The default prose route is `claude_code` + `claude_writer` +
`deepseek_v4_pro` on capacity route `Writer`, with no automatic provider
fallback. Agy remains bounded to its proven observation, review, and narrative
planning roles; the unproven candidate `agy_writer` expansion is not merged.

## Version evidence

| Iteration | Observed model work | Measured result | Decision |
| --- | --- | --- | --- |
| Runtime-v2 Brain-governed first prose | 6 successful calls plus 2 failed calls for one accepted chapter; at least USD 3.085404 in DeepSeek receipts, excluding Brain cost | Strong governance, but the artifact was later marked `rejected_pre_v3` | Do not use per chapter |
| Agy-first V3 parity r8 | Agy failed with `network_required`, then DeepSeek ran 3 full Writer attempts | USD 1.306565, 154,438 input tokens, 21,375 output tokens, about 469 seconds; no independent heavy literary acceptance | Keep Agy opt-in only |
| Narrative Phase2R Node D | One bounded prose Writer packet plus deterministic validation | 68,051-byte packet; accepted targeted revision was 4,762 Han characters, USD 0.631672, 260.39 seconds, deterministic 7/7 | Reuse bounded-context principle |
| Rejected compact experiment | Exact Ch1 Writer packet, provider not started | 51,519 bytes, but the declared full `project_fact_snapshot.yml` authority was omitted | Rejected for quality/authority incompleteness |
| Current synthesis preflight | Exact Ch1 Writer packet, provider not started | 108,305 bytes, 11 sources, zero secret-pattern hits; includes the 54,924-byte fact snapshot and is stable across two rebuilds | Selected authority-complete packet |

## Preserved production rules

- V3 chapter contracts remain authoritative.
- `character_intent_gate`, `must_not_repeat`, `forbidden_facts`, and
  `fact_invention_policy` are unchanged.
- Candidate output cannot write or promote Production.
- Writer contract retries remain bounded and same-route.
- The heavy audit must cover exactly Ch1-10 and bind the audited candidate
  hashes before the candidate set can seal.
- Any blocking audit finding enters the existing targeted rewrite and
  independent re-audit path.

## Implemented efficiency corrections

1. `chapter_relevance_v1` supplies only the active chapter contract, retrieved
   authority fragments, real prior candidate continuity, Writer template, and
   selected Writer skill.
2. The first strict V3 chapter retains every declared must-read authority,
   including the full fact snapshot. Later chapters derive continuity from the
   accepted candidate outputs plus their own hash-bound chapter contracts.
3. A generation-side `network_required`, `provider_error`, or `timeout` enters
   durable retry wait instead of immediately re-running the batch, and the
   retry count is bounded by `max_retries_per_action`.
4. Blueprint seal validation verifies the complete sealed range and separately
   checks that a requested 10-chapter window is inside it.
5. The Ch1 provider call requires both its exact payload SHA-256 and a
   deterministic Ch1-10 Writer scope SHA-256. Ch2-10 may use only that same
   approved scope when their continuity is derived by the recorded rule.
6. The Writer task refuses both direct CLI/API fallback and capacity-route
   fallback; it cannot silently switch from `Writer` to `WriterFlash`.
7. The later primary Reviewer call is not covered by the Writer scope. It
   requires a separately compiled exact payload SHA-256 before the one large
   Ch1-10 audit can start.

## Current governed run

- Job: `crown-efficiency-v7-ch001-010-20260723`
- Range: Ch1-10
- Batch size: 10
- Heavy-audit cadence: 10
- Writer: DeepSeek V4 Pro through Claude Code
- Fallback: disabled
- Status: preflight passed on knowledge snapshot
  `idx_f9d0bda5a5ac5b42f59824e78720b8786937c7577623aa9ab9c0b288f0338fdb`;
  paused before provider execution, pending exact external-context authorization
- Exact payload SHA-256:
  `5782a3e41504fe56bfa8362e1ce30f2aa0455fca55a394625c173ab2530c3e7a`
- Writer Ch1-10 scope SHA-256:
  `7e54637d0fffa959327e21a1a1fa32428068f028b37af7bd7568c10d9988014c`
- Exact manifest:
  `projects/Crown_of_Ash/runs/task_narrative_eval_ch01_crown-efficiency-v7-ch001-010-20260723/outbound_context_manifest_writer.yml`
- Writer scope:
  `acceptance_runs/narrative_eval/Crown_of_Ash/crown-longform-reset-v1/crown-efficiency-v7-ch001-010-20260723/writer_authorization_scope.yml`
- Stability proof: two independent safe compilations produced the same chapter
  packet hash `4176752a6f1c2dd778a56d85a60ad52d2c8fceb2c382584a886f026cec3d082a`,
  exact provider payload hash, scope hash, byte count, and source inventory.

The efficiency decision is based on the accepted call topology rather than on
the smallest byte count alone: one ordinary Writer candidate per chapter,
bounded same-contract redos only when the output contract fails, deterministic
checks, and one primary full-window audit at the batch boundary. The 51,519-byte
experiment is preserved only as rejected evidence and must not be authorized.
