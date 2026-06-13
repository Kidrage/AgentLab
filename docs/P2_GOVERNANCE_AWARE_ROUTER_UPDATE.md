# P2-E Governance-Aware Router Update

## Positioning

P2-E converts P2-D routing recommendations into staged router policy patches.
It does not automatically modify production router config.
Human approval and rollback plan are required.

P2-D is recommendation-only provider performance and cost governance. P2-E is
the reviewable bridge from those recommendations to a router policy patch.

## Flow

stage recommendation -> patch plan -> diff -> approval request -> approval token -> apply to copy -> validate -> rollback plan

The standard deterministic command flow is:

```bash
python scripts/p2_router_update_check.py stage \
  --recommendations governance_runs/p2_provider_governance_demo/routing_recommendations.yml \
  --router-policy config/executor_router.yml \
  --output router_update_runs/p2_router_update_demo

echo APPROVED > router_update_runs/p2_router_update_demo/APPROVE_ROUTER_PATCH

python scripts/p2_router_update_check.py apply-copy \
  --router-policy config/executor_router.yml \
  --patch router_update_runs/p2_router_update_demo/router_policy_patch.yml \
  --output router_update_runs/p2_router_update_demo/patched_executor_router.yml \
  --approval-dir router_update_runs/p2_router_update_demo

python scripts/p2_router_update_check.py validate \
  --router-policy router_update_runs/p2_router_update_demo/patched_executor_router.yml
```

## Artifacts

- `router_policy_patch.yml`: staged operations derived from P2-D recommendations.
- `router_policy_patch.md`: human-readable operation plan.
- `router_policy_diff.md`: field and priority changes plus safety invariants.
- `approval_request.yml` and `approval_request.md`: approval instructions.
- `rollback_plan.yml` and `rollback_plan.md`: original values and restore method.
- `router_update_ledger.yml`: stage, approval, apply, blocked, and validation events.
- `patch_result.yml`: apply-copy result envelope.

## Recommendation Mapping

- `require_manual_approval`: sets `requires_approval: true` when needed.
- `watchlist`: adds a governance watchlist note without disabling providers.
- `insufficient_data`: adds a conservative watchlist note and does not change execution mode.
- `downgrade`: moves the provider later in `provider_priority` by at most one slot.
- `prefer`: moves the provider earlier by at most one slot only when safe.
- `quarantine`: requires approval, adds a quarantine note, and downgrades priority without disabling the provider.
- `keep`: emits no policy-changing operation.

## Safety Boundaries

- no production config overwrite by default
- no enabling disabled external providers
- no enabling auto execution
- no removing safety constraints
- no empty provider priority
- no automatic apply
- no real provider execution
- no network access
- no secrets recorded in ledgers

## Approval

By default, approval uses a deterministic file token. Create a file named
`APPROVE_ROUTER_PATCH` containing `APPROVED` in the output directory. Without
that token, `apply-copy` exits nonzero and does not write a patched policy copy.

Production router writes are disabled by `config/router_update_policy.yml`.
P2-E only applies to a requested output copy unless the policy is explicitly
changed by a human.

## Rollback

Every successful apply creates a rollback plan before writing the patched copy.
The YAML plan includes the original router policy, patched router policy,
affected providers, affected task types, and per-operation restore values.
