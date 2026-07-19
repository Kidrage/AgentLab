# Narrative Gate 1 Acceptance

## Verdict

Gate 1 was started with explicit user authorization and stopped safely before
provider execution. Status: `blocked_external_execution_policy`.

The 2026-07-19 legacy-integration retry reached a stronger pre-provider state:
the candidate blueprint now carries hash-bound legacy character lineage, a
three-chapter state plan, and explicit accepted/rejected legacy rules. The first
Writer process then returned `network_required`; the approved unsandboxed retry
was denied by the host security layer before execution. No valid provider result
or new chapter was produced, so Gate 1 remains blocked rather than failed or
passed.

The configured live Writer route would disclose the private Crown Ch25–27
manuscript window and necessary canon context to an external provider. The
execution environment rejected that outbound action. No workaround, alternate
external provider, or indirect execution was attempted. This is a valid blocked
Gate 1 result, not a failure of the manuscript and not a pass.

## Scope and Safety

- Project: `Crown_of_Ash`
- Requested chapters: Ch25–27
- Isolation: temporary AgentLab root
- Predecessor: hash-valid Ch24 candidate with passing Writer provenance
- Mode: candidate-only
- Production permission: false
- Budget cap: `$10`
- Writer contract: `$1` per attempt, at most two contract attempts per chapter
- Raw manuscript/runtime artifacts: local-only and not committed

The legacy-integration retry's Production tree remained at SHA256
`4da6e59984a9d6b87ee500625f14e77aeb675b69185d4239a0d38c21dd6d7a86`
before and after the attempt.

## Preflight Evidence

- Model doctor: pass, 135 resolved profiles, 0 issues.
- Claude authentication: logged in with OAuth.
- Writer→`claude_code` role binding and role-session generation: pass.
- Ch24 narrative delivery: valid.
- Ch24 Writer execution contract: pass; `deepseek/deepseek-v4-pro`, no fallback.
- L0 Crown fact-source health in the isolated root: pass.
- Three-chapter state-plan requirement: correctly skipped because the sample is
  not larger than five chapters.
- L3 governance-only 1,500-chapter simulation: pass.

The audit-only preflight returned `warn` solely because live L2 generation was
intentionally skipped and historical reset evidence remains audit-only.

## Live Attempt

- External disclosure approval from user: present.
- Execution authorization from environment: denied.
- Local Writer worker process started: true.
- External provider result received: false (`network_required`).
- Completed provider calls: 0.
- Input/output/cache tokens: 0 / 0 / 0.
- Observed cost: `$0`.
- Attempted chapters: none.
- Completed chapters: none.
- Candidate produced: none.
- Audit eligible candidate: none.
- Production modified: false.

Because execution stopped before a provider process began, there is no valid
wall-time, token, literary score, revision-uplift, or A/B comparison measurement.

## Gate Checks

- Structured candidate-only command: prepared.
- External Writer execution: blocked.
- Candidate hash chain: not created.
- Deterministic precheck: not applicable without a candidate.
- Independent literary audit: not run.
- Verified rewrite uplift: unavailable.
- False-green seal: no seal attempted.
- Production contamination: none.

## Remaining Blockers

1. The current agent execution environment does not permit private Crown context
   to be sent to the configured external Writer provider.
2. No approved local Writer model with an equivalent frozen quality contract is
   installed. `qwen-local` is configured as an endpoint, but replacing the
   frozen Writer route would change the experiment and cannot count as Gate 1.
3. User-positive calibration remains `missing_user_samples`.
4. Human blind-review progress remains 0/10.

## Legacy Blueprint Integration

- Current world, faction, magic, and plot-blueprint files are byte-identical to
  the accepted 2026-06-30 rebuilt legacy sources.
- Legacy female-character cards were preserved but were not previously present
  in the Ch25–27 Writer `must_read` inventory.
- Candidate overlay
  `projects/Crown_of_Ash/candidates/gate1_legacy_integrated_ch25_ch27_20260719/legacy_story_authority_overlay.yml`
  now records source hashes, accepted behavioral anchors, current canon
  overrides, rejected unsafe/conflicting rules, and Ch25–27 scene requirements.
- The frozen three-chapter state plan references that overlay. The generated
  Writer packet and outbound manifest included and hashed both files.
- The reused Ch24 predecessor is bound to its exact chapter packet, draft,
  continuity ledger, and state-transition hashes; post-receipt drift blocks use.
- The integration remains candidate-only. Production tree SHA256 stayed
  `4da6e59984a9d6b87ee500625f14e77aeb675b69185d4239a0d38c21dd6d7a86`.
- Existing Ch01–Ch30 candidates were combined for human positive-sample
  selection at
  `/Users/saintpeter/Desktop/Crown_of_Ash_Gate1_人工审读/01_正样本候选_Ch01-Ch30_合订本.txt`.

## Next Safe Action

Do not start Gate 2 or Phase 5. Gate 1 can resume only on an execution surface
authorized to process the private Crown context under the same frozen model,
budget, candidate-only, and receipt contracts, or after a separately approved
local-model calibration plan is established. Preserve this blocked receipt and
resume from Ch25; no candidate work needs rollback.
