# AgentLab 250 Runtime Activation Notes

This file records the current 250 activation boundary. Historical Gemini rough-worker
smoke results are not evidence for the current remote state.

## Authorities

- `config/runtime_cli_requirements.yml`: required/optional CLI inventory and probes.
- `docs/AGENTLAB_CLI_REQUIREMENTS.csv`: copyable installation and verification table.
- `docs/AGENTLAB_FULL_CLI_MATRIX.csv`: role, CLI, model, fallback, and binding table.
- `config/agent_model_profiles.yml`: runtime role/model selection.

Regenerate the two CSV files with:

```bash
python3 scripts/generate_agent_cli_matrix.py
```

## Current Gemini Policy

- The default AgentLab Gemini worker is `agy`.
- Agy uses the remote machine's own Gemini OAuth session.
- The expected Writer model is Gemini 3.5 Flash High.
- OAuth state is not copied from another host by the activation script.
- Gemini 2.5 Flash API-key access is an optional explicit fallback.
- Hermes must not be globally forced to the Gemini API provider through environment
  overrides.

## Activation Modes

Read-only remote inventory:

```bash
scripts/activate_250_runtime.sh --status-only
```

Network/proxy activation plus Agy installation preflight:

```bash
scripts/activate_250_runtime.sh
```

The default activation asks only for the Clash/mihomo subscription URL. It writes the
subscription to `~/.agentlab_secrets/network.env`, writes non-secret proxy variables to
`~/.agentlab_runtime/network.env`, and never selects Gemini API-key auth.

Explicit non-default Gemini API fallback:

```bash
scripts/activate_250_runtime.sh --enable-gemini-api-fallback
```

This additional mode asks for a Gemini API key and stores it in private fallback files.
It does not change AgentLab's default Writer path from Agy OAuth.

## Deployment Gates

Before running Crown production on 250, all of the following require fresh evidence:

1. Remote framework checkout equals the accepted `origin/main` commit and is clean.
2. The Crown project asset tree is synchronized through the private workspace path.
3. Required deterministic tools and required CLI rows in
   `AGENTLAB_CLI_REQUIREMENTS.csv` pass version and safe probes.
4. The remote Agy OAuth session is authenticated and `./agentlab.sh agy-cli-smoke
   --live` succeeds through the US-capable proxy.
5. `./agentlab.sh models doctor`, the full test suite, and narrative candidate gates
   pass on the remote checkout.
6. Candidate generation does not write `production/manuscript` before audit and user
   promotion.

The status audit reports only key presence booleans, never credential values. Old
commit hashes and old live-smoke outcomes must not be reused as current acceptance.
