# Recovery Plan

## Summary

Failure in pytest stage classified as test_failure. Recovery plan generated with 1 hypothesis(es).

## Failure Category

Primary: **test_failure**
Confidence: **0.8**

## Evidence

- Error output captured from failed command
- Standard output captured from failed command

## Likely Root Cause

- A regression test failed, likely due to recent code changes.

## Recommended Action

**retry -> fix and rerun relevant tests**

## Safe Commands

```bash
./agentlab.sh check
```
```bash
python -m compileall agent_runtime agentlab_app.py
```
```bash
./agentlab.sh context-smoke --project AgentLab
```
```bash
python -m pytest -q tests/ -v --tb=short
```
```bash
python -m compileall agent_runtime agentlab_app.py
```
```bash
python -m pytest -q
```
```bash
bash -n agentlab.sh
```

## Unsafe Commands Requiring Approval

- rm -rf
- git reset --hard
- curl
- git push
- git clean -fdx

## Validation Plan

- Run full pytest suite
- Run text integrity checker
- Run context-smoke
- Run agentlab.sh check
- Verify specific test file passes

## Stop Conditions

- If new errors are introduced - STOP
- If recovery takes longer than expected - STOP and review
- If destructive recovery action is required - STOP and get approval
