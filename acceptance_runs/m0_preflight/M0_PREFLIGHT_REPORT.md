# AgentLab M0 Preflight Report

## Verdict

PASS

## Baseline

- Repository: `<repo-root>`
- Branch: `main`
- Baseline commit before M0 edits: `ecd8bb41dbdb2fc88e256c01c0e7c9cbf525854f`
- Remote: `origin https://github.com/Kidrage/AgentLab.git`
- Remote `main` at archive time: `ecd8bb41dbdb2fc88e256c01c0e7c9cbf525854f`
- Backup tag: `m-series-pre-m0-backup`
- Backup tag pushed: yes
- Untracked local-only item intentionally not archived: `.codex/`

## Scope Freeze

Created `docs/M_SERIES_SCOPE.md`.

Scope summary:

- M1 = project governance, not UI polish or business automation.
- M2 = operator control, transparency, observability, and cost visibility, not commercial growth.
- M3 = asset, production, channel, revenue, compliance, client, and SOP loops, not unsafe platform automation.

## Commands Run

```bash
git status --short --branch
git rev-parse HEAD
git ls-remote origin main
git log --oneline -5
git tag -a m-series-pre-m0-backup -m "Backup before M-series M0 repairs"
git push origin m-series-pre-m0-backup
python -m compileall agent_runtime agentlab_app.py
python -m pytest -q
./agentlab.sh --help
./agentlab.sh run-pipeline --help
python scripts/audit_text_integrity.py --fail-on-suspicious
```

## Results

- `python -m compileall agent_runtime agentlab_app.py`: PASS.
- `python -m pytest -q`: PASS, `1202 passed, 2 skipped, 11 warnings in 75.47s`.
- `./agentlab.sh --help`: PASS.
- `./agentlab.sh run-pipeline --help`: PASS.
- `python scripts/audit_text_integrity.py --fail-on-suspicious`: PASS, `Total files scanned: 667`, `Suspicious files: 0`.

## Issues Found And Fixed

- Text integrity initially flagged `docs/AGENTLAB_M_SERIES_MAINLINE_HANDOFF.md` for a literal private-path pattern in a warning bullet.
- Fixed the wording from a concrete private path example to `literal private absolute paths`.
- Re-ran text integrity with `--fail-on-suspicious`; result passed with `0` suspicious files.

## Safety Notes

- No model API calls were required for M0.
- No external tools, external skills, MCP servers, browser automation, or networked execution were used except Git/GitHub upload and GitHub API/status checks.
- No secrets were found in the archived handoff documents.
- The M-series backup point is recoverable through the pushed tag `m-series-pre-m0-backup`.

## Known Limitations

- `python -m compileall agent_runtime agentlab_app.py` traverses the local `agent_runtime/.venv` directory when present, producing noisy output. It passed, but a future M-series cleanup should consider a narrower compile command or repo-local gate wrapper that excludes ignored virtual environments.
- CI for the M0 commit must be checked after this report is committed and pushed.

## Next Recommended Stage

Proceed to M1-1: External Project Registry + Capability Mapping.

M1-1 should add deterministic, disabled-by-default registry/config/runtime/CLI/test coverage for external capability providers without cloning, vendoring, installing, or executing external project code.
