# Router Patch Approval Request

## Patch ID
router_patch_20260613T131914Z

## Why Approval Is Required
- router policy patch changes require human approval

## Operations Requiring Approval
- op_001: add_watchlist_note executor_router.providers[agentlab.mock_patch].notes

## Safety Constraints
- Production router config is not modified by staging.
- Disabled external providers cannot be enabled.
- Auto execution cannot be enabled.
- Rollback plan is required before apply.

## How To Approve
Create a file named APPROVE_ROUTER_PATCH containing APPROVED in the output directory.

## Allowed Apply Targets
- copy
