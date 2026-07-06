# AgentLab 250 Gemini Rough Worker Plan

## Current State

- 250 workspace is `/home/admin/AgentLab`.
- Latest verified 250 sync baseline before this activation patch was commit
  `5ad88d0b88e0c568d4ac99d803c37d6676682bd5`.
- 250 CLI inventory verified:
  - `hermes`
  - `gemini`
  - `qwen`
  - `agy`
  - `claude`
  - `codex`
  - `bl`
  - `openclaw`
- `./agentlab.sh models doctor` passes on 250 with existing non-blocking
  warnings: `status: pass`, `issue_count: 23`.
- Gemini API and Gemini CLI live smoke tests pass through the 250 local proxy.
- Hermes can use Gemini through the 250 local proxy when `HERMES_INFERENCE_PROVIDER=gemini`
  and `HERMES_INFERENCE_MODEL=gemini-2.5-flash` are set.

## Network State

- 250 has proxy environment variables pointing at `127.0.0.1:8123`.
- `mihomo` is installed at `/home/admin/.local/bin/mihomo`.
- `mihomod` is installed and can start `mihomo` in direct process mode.
- `mihomo` listens on `127.0.0.1:8123`; systemd user services remain inactive
  because this activation uses direct process mode.
- 250 can reach GitHub API directly when stale proxy env variables are unset,
  but GitHub release asset downloads may fail or hang from 250. The activation
  used locally downloaded `mihomo`, `Country.mmdb`, and `GeoSite.dat` files.
- The Clash subscription endpoint returns 404 with the default `mihomo`
  subscription user-agent, but returns valid YAML with a Clash-compatible
  user-agent. The activation script falls back to `clash-verge/v2.0.0` and
  rewrites `mixed-port` to `8123`.

## Gemini Flash Worker Policy

Gemini Flash is registered as a rough-work worker, not a default trusted Coder.

Allowed work:

- first-pass log scanning
- issue bucketing
- long output summarization
- duplicate-intent detection
- rough checklist generation
- disposable draft analysis
- low-risk RepoScout support when deterministic `rg` already scoped the input

Forbidden work:

- direct project file edits
- shell command execution
- production artifact promotion
- secret handling
- final verification claims
- high-risk architecture decisions
- longform fiction canon authority

## Workflow Placement

Use Gemini Flash before expensive or high-authority workers:

1. Deterministic tools gather scoped evidence (`rg`, tests, logs).
2. Gemini Flash compresses or buckets the evidence.
3. Hermes/Codex/Claude receives the compressed packet for decisions or edits.
4. TesterAuditor/Verifier validates with deterministic commands.

Do not put Gemini Flash after Verifier or Archivist; it is not an authority
for final acceptance.

## Activation Gates

Gemini rough worker may be promoted from candidate to active only after:

- `gemini --version` works on target endpoint.
- Gemini API key is configured in a private env file.
- A one-prompt `gemini-2.5-flash` smoke test returns a valid response.
- AgentLab invocation contract parse tests pass.
- A rough-work audition task produces useful output with no file edits.

## 250 Remaining Activation Items

- Investigate the existing `models doctor` warnings when they become relevant
  to routing quality; they are non-blocking for Gemini rough-work activation.

After explicit approval, use:

```bash
scripts/activate_250_runtime.sh
```

The script prompts for the Clash subscription URL and Gemini API key without
echoing them, writes only private remote env files, then attempts mihomo and
Gemini smoke tests.

For read-only status checks before or after activation, use:

```bash
scripts/activate_250_runtime.sh --status-only
```

Latest pre-activation status-only baseline:

- 250 git head: `7ed77bca25ef5e09454f3a5d55b4e3e44bf62b0c`
- 250 worktree: clean
- `gemini`: present, `0.49.0`
- `mihomod`: present
- `mihomo`: missing
- `mihomo` and `clash` user services: inactive
- Gemini and Clash secret keys: not present in checked private env locations
- `./agentlab.sh models doctor`: `status: pass`, `issue_count: 23`

Latest live activation result:

- Private env files configured without embedding secrets in the repository.
- `mihomo_config` may report a 404 from the default subscription fetch; this is
  expected for the current subscription service and is followed by the
  `mihomo_config_fallback` path.
- `mihomo_config_fallback`: `code: 0`, method `clash-verge user-agent`.
- `mihomo_start`: `code: 0`, direct process mode.
- `gemini_api_smoke`: `code: 200`, response contains `OK`.
- `gemini_cli_smoke`: `code: 0`.
- `hermes --safe-mode --provider gemini -m gemini-2.5-flash -z ...` returns
  `OK`.
- `--status-only` reports `mihomo_direct_process: true` and
  `proxy_8123_listening: true`.
- Read-only rough-work audition:
  - Gemini CLI task-packet prompt reached API retry but timed out on longer
    prompt; short CLI smoke remains healthy.
  - Contract fallback via Gemini HTTP API returned `code: 200`.
  - The audition produced findings, confidence, and escalation points from a
    task packet without file edits or command execution.
