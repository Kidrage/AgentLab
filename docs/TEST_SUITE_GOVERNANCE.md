# AgentLab Test Suite Governance

## Purpose

The suite should maximize unique behavioral coverage while minimizing repeated
setup, subprocess launches, config parsing, and accidental live work. A smaller
file count is not itself an optimization: pytest schedules test functions, not
filenames.

## Current Baseline

- Top-level test modules: 329.
- Current collection after the pruning changes: 2738 tests.
- Final pruning verification:
  `2736 passed, 2 skipped, 11 warnings in 208.35s`.
- The earlier broad baseline in this worktree was
  `2714 passed, 2 skipped, 11 warnings in 549.10s`.
- Historical same-worktree runs reached about 901 seconds before YAML/config
  caching and repeated setup removal. Timings vary with filesystem cache and
  machine load, so compare medians or clearly label one-shot runs.

The final full-suite result for a release replaces, rather than accumulates
beside, this baseline in `docs/AGENTLAB_PRUNING_REPORT_20260718.md`.

## Collection Boundary

`pytest.ini` is authoritative:

```ini
testpaths = tests
norecursedirs = tests/fixtures
```

Fixture repositories may intentionally contain `test_*.py`; they are input
data, not AgentLab tests. Any test that needs them must open the fixture
explicitly. Live provider tests must remain opt-in behind their documented env
gate and must never run in the default full suite.

## Deduplication Gates

`tests/test_cleanup_refactor_invariants.py` fingerprints top-level test
functions and test methods by normalized Python AST. Exact duplicate
implementations fail the suite.

The gate intentionally does not reject tests that look similar but prove
different contracts, error boundaries, routes, models, or artifact ownership.
Those cases should be parameterized only when the setup, action, and assertion
shape are genuinely the same.

## When To Merge Tests

Merge or parameterize when at least one is true:

- the tests repeat the same expensive subprocess or config bootstrap;
- only table data differs and one failure still identifies the case clearly;
- two modules cover the same public contract and have no distinct ownership;
- shared fixtures eliminate measurable runtime or maintenance duplication.

Keep separate when at least one is true:

- ownership follows different runtime modules or production packs;
- the failure boundary, security rule, or regression history is distinct;
- merging would require condition-heavy assertions or hide the failing case;
- the change only reduces filenames and does not reduce collected work.

Do not create omnibus test files. A cohesive module can be small.

## Runtime Discipline

- Focused edit loop: run the directly affected test module(s).
- Shared-contract change: run the affected route/pack/lifecycle slice.
- Broad authority, loader, state, or artifact change: run one complete suite
  before delivery.
- Use `--durations=40` for periodic performance audits, not every edit loop.
- Cache immutable YAML snapshots by file identity and return isolated copies to
  callers; never let test speed introduce shared mutable config state.
- Prefer deterministic validators over model calls for schemas, paths, hashes,
  state transitions, route membership, and promotion boundaries.

## Review Checklist

Before adding or merging tests, verify:

1. The test covers a user-visible or governance contract, not an implementation
   detail already covered elsewhere.
2. No default provider, CLI model, production task, network call, or promotion
   can start.
3. Temporary files stay under pytest's temp directory.
4. Failure output names the route, role, artifact, or policy that regressed.
5. The focused test passes and collection still passes the duplicate gate.
