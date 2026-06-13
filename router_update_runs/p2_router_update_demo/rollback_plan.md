# Router Patch Rollback Plan

- Patch ID: router_patch_20260613T131914Z
- Restore Method: Replace the patched copy with original_router_policy from rollback_plan.yml, or reapply listed original values manually.

## Affected Providers
- agentlab.mock_patch

## Affected Task Types
- None

## Restore Operations
- op_001: restore executor_router.providers[agentlab.mock_patch].notes to ['Deterministic test-only executor.']
