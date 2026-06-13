# Router Policy Patch Diff

## Summary
- operations: 1
- priority changes: 0
- provider field changes: 1
- provider priority task types currently configured: 3

## Operations
- op_001: add_watchlist_note for agentlab.mock_patch; approval=True

## Provider Priority Changes
- None

## Provider Field Changes
- executor_router.providers[agentlab.mock_patch].notes: ['Deterministic test-only executor.'] -> ['Deterministic test-only executor.', 'watchlist_recommended_by_governance']

## Safety Invariants
- production router policy not modified
- human approval required
- rollback plan generated
- auto execution not enabled
- disabled external providers not enabled
- safety constraints retained

## Blocked Operations
- None
