# AgentLab 250 Gemini Rough Worker Plan

## Current State

- 250 workspace is `/home/admin/AgentLab`.
- Initial verified 250 sync baseline was commit
  `0ddda8fd5fdbf7c97438957006d23f94d6b40f9d`.
- 250 CLI inventory verified:
  - `hermes`
  - `gemini`
  - `qwen`
  - `agy`
  - `claude`
  - `codex`
  - `bl`
  - `openclaw`
- AgentLab CLI executor/model tests passed on 250:
  `69 passed`.
- `./agentlab.sh models doctor` passed on 250 with existing non-blocking warnings.

## Network State

- 250 has proxy environment variables pointing at `127.0.0.1:8123`.
- No Clash/mihomo service is currently active on that port.
- Direct GitHub and Docker Hub access from 250 timed out.
- npm registry access works when proxy variables are unset.
- `mihomod` is installed, but mihomo core download timed out before completion.

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

- Configure Clash/mihomo subscription after explicit secret-write approval.
- Start Clash/mihomo on `127.0.0.1:8123` to satisfy current proxy env.
- Configure Gemini API key after explicit secret-write approval.
- Run live Gemini smoke test on 250.
- Run one AgentLab role-session or task packet through `gemini` in read-only
  rough-work mode.

After explicit approval, use:

```bash
scripts/activate_250_runtime.sh
```

The script prompts for the Clash subscription URL and Gemini API key without
echoing them, writes only private remote env files, then attempts mihomo and
Gemini smoke tests.
