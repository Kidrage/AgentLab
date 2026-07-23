# Narrative efficiency baseline (Phase 0)

> requested_agent: codex · invoked_agent: codex · reporting_agent: codex

Status: completed historical baseline; isolated live probe blocked pending explicit
external-context disclosure approval. Source of record:
`acceptance_runs/narrative_efficiency/baseline_metrics.json`.

## Method

The frozen manifest binds 34 files by SHA256 and defines these evidence sets:

- Ch01-Ch03, Ch01-Ch10, and Ch01-Ch30 historical generation;
- the Ch01-Ch03 heavy-audit pilot;
- Ch21-Ch30 pre-repair and post-repair heavy audits;
- the known-negative Ch26 revision run;
- background heavy-audit attempts 0008-0011;
- the attempted isolated Ch25-Ch27 live probe.

Every numeric metric in the JSON uses this envelope:

```json
{
  "value": 123,
  "unit": "seconds",
  "measurement": "exact | derived | lower_bound | missing",
  "source": ["evidence path"],
  "confidence": "high | medium | low"
}
```

`model_active_seconds` is unavailable because the configured providers do not
separate model compute from network and process overhead. The historical number
reported below is `provider_process_wall_seconds`: the exact CLI/API process
start/end span, not pure model-active time.
Historical generation has no complete pipeline lifecycle, so its wall-clock value
is a lower-bound span from the first recorded command to the last recorded command;
the difference includes queue/idle gaps, retry delay, file I/O, and orchestration
and must not be labelled pure local CPU time.

Provider receipts are preferred for all-model usage and cost. Cost-ledger values
are retained separately because the ledger is demonstrably incomplete.

## Generation baseline

| Frozen set | Chapters | Provider calls | Derived repeated-role calls | Provider-process seconds | Observed elapsed span (lower bound) | All-model tokens | Receipt cost | Cost-ledger calls / cost | Packet bytes | Repeated source-byte ratio (lower bound) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ch01-Ch03 | 3 | 6 | 3 | 1,402.923 | 19,520.241 | 432,317 | $2.813345 | 1 / $0.367804 | 264,120 | 49.39% |
| Ch01-Ch10 | 10 | 18 | 8 | 4,563.789 | 46,548.610 | 1,275,790 | $9.663902 | 3 / $1.694983 | 916,381 | 66.32% |
| Ch01-Ch30 | 30 | 50 | 20 | 11,638.927 | 81,533.439 | 4,772,583 | $26.903531 | 12 / at least $4.798659 | 2,829,440 | 69.81% |

Findings:

- The average historical Writer/governance provider-process time is 388 seconds
  per chapter across Ch01-Ch30. It includes process/network overhead and is not
  model compute time or total system time.
- There are 50 provider process records for 30 retained candidates. Repeated role
  calls account for 20 derived retries/redos.
- All 30 runs contain the deterministic delivery files, but “final usable
  candidate count” remains missing because no literary scorecard, blind A/B, or
  human acceptance binds those candidates.
- The surviving Writer manifests show a 69.81% repeated-source-byte lower bound
  across 30 chapters. Retry manifests can be overwritten, so this is not a
  complete high-confidence reuse measurement.
- The historical cost ledger records only 12 of 50 provider processes in the
  30-chapter set and at least $4.80 versus $26.90 in immutable receipts. A failed
  or superseded paid attempt can therefore disappear from the product cost view.
- Cache-read tokens exist in receipts, so “there is no model cache” is false. The
  current evidence cannot bind cache hits to context-bundle hashes, so cache
  effectiveness is not explainable.

## Heavy-audit baseline

| Audit | Wall seconds | Provider seconds | Calls | All-model tokens | Known cost (lower bound) | Packet bytes | Repeated source bytes | Fiction findings / blocking | Exact-evidence findings | Rewrite proposals |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ch01-Ch03 pilot | 1,564.568 | 674.567 | 5 | 219,210 | $1.558130 | 503,858 | 48.56% | 10 / 0 | 10 | 0 |
| Ch21-Ch30 pre-repair | 956.272 | 701.288 | 5 | 385,096 | $2.460080 | 708,406 | 36.46% | 12 / 2 | 12 | 7 |
| Ch21-Ch30 post-repair | 646.967 | 612.465 | 4 | 324,983 | $2.067835 | 713,397 | 36.45% | 19 / 5 | 19 | 5 |

The post-repair run is faster than the pre-repair run: wall time fell 32.3%,
provider time 12.7%, call count 20%, all-model tokens 15.6%, and known cost 15.9%.
That is an efficiency result, not a quality-uplift result. The post-repair audit
still reports five blocking findings and asks for another rewrite. The two audits
also differ in exact outputs and evidence requirements, so the increase from two
to five blocking fiction findings cannot be used alone to claim the rewrite made
the prose worse.

The post-repair role breakdown is:

| Role | Provider seconds | Node seconds | Payload bytes | Ledger input/output tokens | Known cost |
|---|---:|---:|---:|---:|---:|
| Supervisor | 312.610 | 316.345 | 145,023 | 34,624 / 5,422 (estimated) | unknown |
| Reviewer | 177.487 | 181.256 | 345,971 | 87,637 / 10,889 | $1.150950 |
| Scribe | 59.246 | 63.001 | 105,927 | 30,738 / 4,330 | $0.419385 |
| Verifier | 63.123 | 66.851 | 116,476 | 34,122 / 5,162 | $0.497500 |

Supervisor is the largest wall-time role even though it does not judge prose.
Reviewer is the only role that reads the complete bounded chapter context.
Scribe and Verifier operate on derived reports but still add 122 seconds of
provider time and use the same DeepSeek Pro model family as Reviewer. Their
independence is procedural, not model-independent.

The pre-repair audit executed Scribe twice. Five provider process records exist,
but only four cost-ledger calls; the superseded invocation is absent from the
ledger. Current node-level retry therefore avoids restarting the entire pipeline,
but observability loses the paid failed/superseded node.

## Rework-uplift baseline

Ch26 is a user-reported negative sample after automated repair and a stronger
model retry:

| Metric | Ch26 observed value |
|---|---:|
| Provider calls | 2 |
| Provider-process seconds | 287.364 |
| First-to-last recorded span | 4,487.769 seconds (lower bound) |
| Receipt total tokens | 144,919 |
| All-model tokens | 146,728 |
| Receipt cost | $0.841700 |
| Cost-ledger calls / cost | 1 / $0.390939 |
| Final context packet | 100,218 bytes, 19 files |

This proves that “use Pro after Flash” does not by itself solve the reported
intelligence/interest problem. It does not prove the Pro draft is worse: there is
no versioned literary scorecard, scene-level repair contract, anonymous A/B
preference, or accepted human verdict. Current artifacts can prove that a repair
was made and schemas passed, but not that readers preferred it.

The required uplift metrics are currently missing:

- original versus revised six-dimensional literary score;
- unresolved and newly introduced blocking findings;
- independent blind-judge preference;
- human blind-review preference;
- cost and time per accepted improvement.

`positive_calibration_status` is deliberately
`missing_user_samples`. No random chapter has been promoted to a positive sample.

## Background/recovery baseline

Attempts 0008-0011 contain 7 provider process records and zero cost-ledger calls.
They consumed 677.398 provider seconds within 755.706 lifecycle seconds. Attempts
0008-0010 spend roughly 95% of their lifecycle in provider processes and end
blocked; attempt 0011 records 38.295 provider seconds and 42.367 non-provider
seconds. The state machine has retry/recovery scaffolding, but historical attempt
cost and token attribution is not recoverable from the cost ledger.

The persisted background event stream yields scheduling/queue wait separately
from provider-process time. It still cannot split lease acquisition from local
file I/O, and model-active compute remains unavailable; those fields stay
explicitly missing rather than guessed.

For the frozen 200-chapter job, nine closed scheduling intervals total 16.443
seconds; no persisted `capacity_wait` or `retry_wait` interval occurred in that
sample. This is controller scheduling latency, not provider or model time.

## Isolated live Ch25-Ch27 probe

The trial ran in a temporary AgentLab root, with a hash-valid Ch24 predecessor,
`candidate_only=true`, no Production write permission, and a $10 cap. The Writer
contract limits each call to $1; the configured maximum of two contract attempts
per chapter bounded the planned three-chapter chargeable path to $6 before
capacity-unavailable calls.

Ch25 attempted one Writer invocation:

- 207,910-byte packet, 21 sources, 211,207 source bytes;
- 173.956 seconds before returning `network_required`;
- zero provider-reported input/output tokens and zero cost;
- no chapter candidate was materialized.

The sandboxed call could not access the provider. The requested unsandboxed call
was denied because it would disclose Crown manuscript/canon context to an external
model without an explicit disclosure approval. No workaround was attempted. The
Production tree SHA256 remained
`95a3061eb41360cbd905581e2dc79792e0c2242dcbfdaa4c9a2da723ee4dda75`
before and after.

The live result is therefore
`blocked_external_disclosure_approval_required`, not pass and not an efficiency
comparison. Completing the live three-chapter sample requires explicit approval
to send Ch25-Ch27 and their necessary canon context to the configured external
Writer provider.

## Reproduction

```bash
python3 -m agent_runtime.narrative.diagnostics.baseline \
  --root . \
  --manifest acceptance_runs/narrative_efficiency/frozen_samples.yml \
  --output acceptance_runs/narrative_efficiency/baseline_metrics.json
```

This command is read-only with respect to project artifacts. It rewrites only the
generated baseline JSON. It does not invoke a model, modify Production, or repair
the confirmed defects.

## Phase 0R v2 Rebaseline (2026-07-20, correction2)

Phase 0R re-established the efficiency baseline under the corrected
`codebase_build_project` governance route. No efficiency measurements changed —
the v1 frozen file hashes, metric cases, and sample groups remain authoritative.

- **v2 manifest**: `acceptance_runs/narrative_efficiency/frozen_samples_v2.yml`
  adds calibration v2 references, red/green replays, and SHA256 recomputability
  notes without overwriting v1.
- **v2 metrics**: `acceptance_runs/narrative_efficiency/baseline_metrics_v2.json`
  records the v2 calibration structure. Coder execution (claude_code / deepseek-v4-pro)
  is recorded separately from provider prose generation. Provider-prose timing, token,
  and retry fields are explicitly unavailable (no provider prose call occurred in
  Phase 0R). Focused tests: 58 passed / 0 failed / 0 skipped.
- **Calibration**: v1 had `positive_calibration_status: missing_user_samples`;
  v2 records four diagnostic candidates (Ch01/Ch04/Ch09/Ch17) pending user review —
  NOT user-approved positives. `positive_calibration_status` remains
  `missing_user_samples`. Structural-fatigue probes (Ch05/Ch07/Ch14) and conflict
  holdout (Ch30) are frozen with real SHA256 values.
- **Provider prose generation**: 0 calls, 0 candidates, 0 tokens, 0 cost.
  Production unchanged.
- **All artifact hashes**: recomputed at HEAD `9799ba0` via `shasum -a 256` and
  recorded in `calibration_manifest_v2.yml`.

## Phase 0R v2 Correction3 (2026-07-20)

Correction2 was rejected because the v2 baseline lacked a complete 30-chapter
source and outbound-context-bundle hash inventory. Correction3 completes it.

- **Complete hash table**: `baseline_metrics_v2.json` `chapter_inventory` now
  freezes all 30 chapters (1–30 in order). Every chapter entry has verified
  `source_sha256`, `source_bytes`, `bundle_sha256`, and `bundle_bytes` computed
  from live filesystem at HEAD `9799ba0`. All 60 paths (30 source + 30 bundle)
  exist and independently hash-match.
- **Field rename**: `positive_samples` renamed to `diagnostic_candidates_pending_user_review`.
  No misleading field name while `positive_calibration_status` is `missing_user_samples`.
- **Ch23 heading**: Corrected to exact `# 章二十三 · 铁线破晓`.
- **v1 coverage**: Updated to truthfully note v1 covers only 13 prose drafts.
- **No efficiency measurement, source, config, Production, or release changes**.
- **Focused tests**: 58 passed, 0 failed, 0 skipped.
