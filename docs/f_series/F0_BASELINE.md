# F0 Baseline

This record freezes the starting point for the F-series repair. It is evidence,
not an acceptance receipt, and does not change any capability status.

## Source

- Repository: `Kidrage/AgentLab`
- Baseline branch: `main`
- Baseline commit: `5c1f9e7c04a53cad9a37e730836fad3b118a2586`
- Repair branch: `agent/f0-baseline-bootstrap`
- Baseline worktree: clean
- Captured: `2026-08-07T03:01:21Z`

## Environment

- OS: Ubuntu 24.04.3 LTS
- Kernel: Linux 6.18.35 x86_64
- Python observed before bootstrap: 3.12.13
- Provider credentials required for this baseline: no

## Reproduced blocker

On the clean checkout, the documented first command failed before its command
logic ran:

```text
$ ./agentlab.sh repository-handoff --repo .
ModuleNotFoundError: No module named 'typer'
```

Root cause: the Quick Start and repository instructions invoked the Python CLI
before declaring an installation/bootstrap step. `requirements.txt` also used
unlocked top-level dependencies.

## Acceptance state preserved

`acceptance_runs/agentlab_capability_acceptance/current.yml` remains the baseline
authority and reports:

- `overall_status: fail`
- `pass: 16`
- `fail: 3`
- `candidate: 9`

No status was promoted or rewritten for F0. GitHub's combined-status endpoint
returned no status contexts for the baseline commit, and the connected workflow
lookup returned no PR-triggered run, so this record does not claim a CI result.

## Initial repair boundary

The first batch is limited to installation, dependency locking, actionable
entrypoint failure, documentation order, and their tests. Runtime behavior,
routes, Providers, domains, and Agent roles are unchanged.

## Test baseline

After the bootstrap changes, the complete offline suite reported:

- 3,371 passed;
- 20 skipped;
- 12 failed;
- 32 warnings.

The same 12 tests were then executed from a clean `git archive` of the baseline
`main` commit and all 12 failed with the same assertions. They are therefore
recorded as inherited F0 blockers rather than regressions from this batch:

- current acceptance/evidence-chain hygiene: 2;
- background retry accounting/limit: 2;
- Qwen narrative structured execution: 2;
- Crown scale-governance evidence: 2;
- Agy capacity policy drift: 1;
- narrative packet schema drift: 1;
- trusted live runner readiness: 2.

Focused bootstrap, handoff, CI-contract, CLI-isolation, and text-integrity tests
pass. F0 remains in progress and no later stage is authorized.
