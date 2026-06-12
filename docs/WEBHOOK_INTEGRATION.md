# AgentLab Webhook Integration

Webhook delivery is an optional reverse feedback channel for same-host chat
adapters. It is primarily intended for localhost or private Docker-network
feedback to OpenClaw or another chat adapter. It is disabled by default and must
be enabled in `config/webhook_policy.yml`.

AgentLab dispatches outbound events; OpenClaw receives them locally. Do not
expose AgentLab directly to the public internet, and do not expose an AgentLab
webhook receiver publicly.

## Configuration

Example:

```yaml
enabled: false
endpoints:
  - name: openclaw
    url_env: AGENTLAB_OPENCLAW_WEBHOOK_URL
    secret_env: AGENTLAB_OPENCLAW_WEBHOOK_SECRET
    events:
      - ACTION_REQUIRED
      - BLOCKED
      - STALE_RUNNING
      - FAILED_RECOVERABLE
      - COMPLETED
      - SKILL_REQUEST_PENDING
retry:
  max_attempts: 3
  backoff_seconds: 2
security:
  sign_payload: true
  redact_secrets: true
```

Set endpoint URLs and secrets through the environment. For local OpenClaw
integration, prefer a localhost URL or a private Docker service URL:

```bash
export AGENTLAB_OPENCLAW_WEBHOOK_URL="http://127.0.0.1:19118/agentlab/events"
export AGENTLAB_OPENCLAW_WEBHOOK_SECRET="local signing secret"
```

No secret value should be committed to config.

## Payload

```json
{
  "event": "ACTION_REQUIRED",
  "project": "AgentLab",
  "task_id": "task_0001",
  "stage": "implementation",
  "severity": "ACTION_REQUIRED",
  "summary": "Approval required",
  "reason": "Need user approval before continuing.",
  "decision_card": {
    "id": "decision_...",
    "options": []
  },
  "links": {
    "status": "...",
    "report": "..."
  },
  "created_at": "2026-06-11T00:00:00+00:00"
}
```

When signing is enabled and a secret env var is configured, AgentLab sends:

```text
X-AgentLab-Signature: sha256=<hmac-sha256>
```

## Events

Dispatchable events:

- `ACTION_REQUIRED`
- `BLOCKED`
- `BUDGET_WARNING`
- `STALE_RUNNING`
- `FAILED_RECOVERABLE`
- `COMPLETED`
- `SKILL_REQUEST_PENDING`
- `SKILL_CANDIDATE_READY`
- `SKILL_PROMOTED`

Current trigger points include decision-card creation, watchdog stale detection,
pipeline completion, skill request creation, skill candidate creation, and skill
promotion.

## Logs

Task-level deliveries:

```text
projects/<Project>/runs/<task_id>/webhook_delivery_log.yml
```

Project-level skill deliveries:

```text
projects/<Project>/webhook_delivery_log.yml
```

Logs include endpoint name, event, status, attempt count, response/error
metadata, and the redacted payload.

## CLI

```bash
./agentlab.sh webhook-test --event ACTION_REQUIRED --project AgentLab --task-id task_0001
./agentlab.sh webhook-status --project AgentLab --task-id task_0001
./agentlab.sh webhook-redeliver --project AgentLab --task-id task_0001
```

If no endpoint URL is configured, dispatch succeeds with a skipped delivery.

## Local-First Security

- Webhook is primarily intended for same-host / localhost / private Docker network feedback to OpenClaw or another chat adapter.
- Do not expose AgentLab webhook receiver publicly.
- AgentLab dispatches outbound events; OpenClaw receives them locally.
- Do not put API keys or private tokens in webhook payloads.
- Keep endpoint URLs in environment variables, not committed config.
