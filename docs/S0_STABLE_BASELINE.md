# S0 Stable Baseline

S0 is the repository health and stable baseline gate for the new AgentLab
mainline. Its purpose is to keep the repository trustworthy before S1+ compiler
work expands the system.

## Goals

- Preserve Python, YAML, CI, test, and documentation text integrity.
- Keep CI workflow YAML valid and readable.
- Re-accept P0/P1/P2 import and CLI smoke coverage.
- Keep checks local-first and deterministic.
- Avoid new feature expansion while stabilizing the baseline.

## Text Integrity Check

Run:

```bash
python scripts/audit_text_integrity.py
```

The output includes:

```text
files_scanned
suspicious_count
suspicious_files
verdict
```

For CI-style failure behavior, run:

```bash
python scripts/audit_text_integrity.py --fail-on-suspicious
```

Expected S0 result is `suspicious_count: 0` and `verdict: PASS`.

## Remote Raw Integrity Check

Run either form:

```bash
python scripts/check_remote_raw_integrity.py --ref main
python scripts/check_remote_raw_integrity.py --branch main
```

The default repository is `Kidrage/AgentLab`. The script checks critical raw
files for line counts, extreme long lines, and sha256 agreement with the local
git blob for the selected ref when available.

If local work has not been pushed yet, remote raw may not match local edited
files. In that case, run local integrity checks first, push the accepted commit,
then re-run remote raw integrity against the pushed branch/ref.

## Stable Baseline Smoke

Run:

```bash
python scripts/s0_stable_baseline_check.py
```

Expected output shape:

```json
{
  "verdict": "PASS",
  "checks": [],
  "warnings": []
}
```

The smoke imports key P0/P1/P2 modules and checks CLI help. It does not execute
ECC, call external APIs, clone remote repositories, start the MCP server, or run
external tools.

## Compile, Test, and CLI Smoke

Run:

```bash
python -m compileall agent_runtime agentlab_app.py
python -m pytest -q
./agentlab.sh --help
./agentlab.sh run-pipeline --help
```

These commands ensure Python parseability, test coverage, and entrypoint
readiness.

## P0/P1/P2 No-Regression Signal

The stable baseline smoke imports representative modules for:

- P0/P0.1: cost ledger, budget gate, repo manifest, clone guard, resource
  ledger, artifact contract, and pipeline wiring;
- P1: skill registry, external handoff, ECC inventory, AnySearch local/mock
  fallback, local URL reader, and CodeGraph dry-run/local-only adapter;
- P2: reviewer, retry, governance/router feedback, context governance,
  recovery, closure feedback, and closure runner.

Passing import and CLI smoke is not a full behavioral proof, but it provides a
lightweight deterministic no-regression gate for the sealed P0/P1/P2 baseline.

## CI Baseline

The CI workflow must remain valid multi-line YAML and run at least:

```bash
python scripts/audit_text_integrity.py --fail-on-suspicious
python -m compileall agent_runtime agentlab_app.py
python -m pytest -q
python scripts/s0_stable_baseline_check.py
./agentlab.sh --help
./agentlab.sh run-pipeline --help
```

On pushes to `main`, CI also runs remote raw integrity for the main branch.

## Non-Expansion Rule

S0 is not a feature-expansion phase. It should not implement Mission Compiler,
Skill OS, Capability Fabric, Native Web Intelligence, multimodal execution,
OpenClaw adapters, dashboards, or external execution paths.