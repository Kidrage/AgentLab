# AgentLab Skill And Feedback Roadmap

This document separates current scaffold behavior from production AgentOps behavior.

## Current: Implemented

### Skill Evolution — Local Lifecycle MVP

- `skills/registry.yml` is the local skill registry (status: `local_lifecycle_mvp`).
- `projects/<Project>/skill_requests/` stores pending Skill Adoption Requests.
- `projects/<Project>/runs/<task_id>/skill_candidates/` stores trace-to-skill candidates.
- `skill-request` creates a pending request with risk metadata and cost preview.
- `skill-import-url` imports a real external `SKILL.md` from an allowlisted URL (network must be explicitly enabled).
- `skill-status` summarizes active skills and pending requests.
- `skill-list` lists all skill requests with status counts (pending/approved/staging/validated/rejected).
- `skill-approve` transitions `pending_user_approval → approved`.
- `skill-reject` transitions `pending_user_approval → rejected` with a reason.
- `skill-stage` transitions `approved → staging`, creating `skills/staging/<skill_id>/` with metadata.yml, adapted_skill.md, and validation_plan.yml.
- `skill-validate` runs fake sandbox validation (`staging → validated`), creating sandbox_report.yml without executing external code.
- `skill-promote` transitions `validated → active`, copying content to `skills/active/<skill_id>/` and updating the registry.
- `skill-retire` transitions `active → retired`, moving content to `skills/retired/<skill_id>/`.
- Filesystem layout: `skills/staging/`, `skills/active/`, `skills/retired/`.
- `skill-match` retrieves active skills for a task goal by triggers, applies_to, and summary overlap.
- `skill-inject` writes selected/rejected active skills into `workflow_plan.yml`.
- `prepare --write-plan` and pipeline `PREPARE_PLAN` perform active skill retrieval/injection.
- Run-local `skill_usage.yml` records selected/rejected skills and normalized usage entries.
- `skills/active/<skill_id>/` is immutable after promotion; runtime evidence follows run retention and never writes back into the tracked skill package.
- High-risk skills are rejected for injection when policy requires approval.

### External Skill Import MVP

- `agent_runtime/external_skill_importer.py` implements `fetch_skill_markdown_from_url`, `parse_skill_frontmatter`, `build_external_skill_request`, and `import_skill_from_url`.
- `config/external_skill_import_policy.yml` controls allowlist, network access, byte limits, and snapshot settings.
- External URLs must be in the allowlist; network access is off by default.
- Primary smoke URL: `https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md` (`skill-creator`).
- Import always creates `pending_user_approval` requests; zero external code execution.
- Source snapshots are saved under `projects/<Project>/skill_requests/<request_id>/source_snapshot/SKILL.md`.
- `tests/fixtures/external_skills/skill-creator/SKILL.md` provides a no-network fixture.
- `tests/test_external_skill_importer.py` covers no-network fixture tests.
- `tests/test_external_skill_importer_live.py` provides an optional live smoke test using `skill-creator`, gated by `AGENTLAB_RUN_EXTERNAL_SKILL_LIVE_TEST=1`.
- Fallback URL candidates (documented only; AgentLab does not automatically fetch fallback URLs):
  - `https://raw.githubusercontent.com/openclaw/skills/main/skills/bowen31337/create-agent-skills/SKILL.md`
  - `https://raw.githubusercontent.com/openclaw/skills/main/skills/gitgoodordietrying/skill-writer/SKILL.md`
- Imported external skills enter the normal lifecycle: request → approve → stage → fake validate → active.
- Active imported skills can be retrieved and injected into matching tasks, writing only run-local usage evidence.

### Trace-to-Skill MVP

- `learning-review` writes `learning_review.yml` for a completed or inspected task.
- Blocked events, validation failures, recovery actions, repeated approvals, repo-specific repair procedures, and artifact contract workarounds can create `skill_candidates/*.yml`.
- Pipeline completion runs post-task learning review after `FINALIZE`.
- `skill-candidates` lists task candidates.
- `skill-candidate-approve` turns a candidate into a `source_type=self_learned` Skill Adoption Request.
- `skill-candidate-reject` records rejection metadata.

Complete lifecycle:

```
pending_user_approval → approved → staging → validated → active → retired
                      ↘ rejected
```

### Feedback Loop Scaffold

- `task_events.jsonl` stores a per-task event timeline.
- `decision_cards/*.yml` stores pending approval cards.
- `feedback_status.json` stores a machine-readable feedback summary.
- Pipeline node starts/completions write events.
- Pipeline blocked paths write `USER_DECISION_REQUIRED.md`, a decision card, task events, and feedback status.
- `decision-list`, `decision-approve`, `decision-reject`, and `decision-resume` provide a CLI approval protocol.
- Web UI Decision Center is backed by real decision cards and task events.
- `GET /api/tasks/<task_id>/events/stream` provides an SSE MVP with polling fallback in the frontend.
- `watchdog-scan` and `watchdog-status` detect stale running, stale event, waiting approval, and stale lock conditions.
- Watchdog stale handling appends `STALE_RUNNING`, refreshes feedback status, and can create a recovery decision card.
- Optional webhook notification channel is implemented and disabled by default.
- Webhook is primarily intended for same-host / localhost / private Docker network feedback to OpenClaw or another chat adapter.
- AgentLab dispatches outbound events; OpenClaw receives them locally.
- Do not expose AgentLab directly to the public internet or publish an AgentLab webhook receiver.
- `webhook-test`, `webhook-status`, and `webhook-redeliver` manage delivery testing and logs.
- `docs/WEBHOOK_INTEGRATION.md` documents local-first OpenClaw/Hermes/chat gateway integration.
- Optional MCP-style stdio tool server is implemented in `agent_runtime/mcp_server.py`.
- MCP tools cover task status/events/reports, decision approval, task controls, skill requests, webhook status, and watchdog scan.
- `docs/MCP_INTEGRATION.md` documents local stdio configuration and security policy.
- OpenClaw should call AgentLab through CLI or MCP stdio in the same runtime; AgentLab is not a public SaaS API.

## Current: Not Yet Production Ready

### Skill Evolution

- No full GitHub skill repo search.
- No multi-file external skill package parser.
- No real sandbox execution (only fake sandbox file checks).
- No model-based candidate synthesis; Trace-to-Skill MVP uses deterministic event/report pattern detection.
- No automatic unapproved external skill learning; candidates still require approval and the existing lifecycle.
- No production-grade supply-chain risk scanner.
- No full skill ROI/conflict/retirement automation.

### Feedback And Intervention

- No long-running watchdog daemon.
- No Telegram-specific bot adapter.
- No real OpenClaw/Hermes/Telegram adapter.
- No production daemon service manager.
- No full MCP SDK wrapper; current MVP is a minimal dependency-free stdio JSON-RPC tool server.
- WebSocket is not implemented; current real-time MVP uses Server-Sent Events.

## Next Implementation Targets

1. Add full MCP SDK wrapper if a target client requires strict SDK behavior.
2. Add Telegram/OpenClaw/Hermes-specific chat command parsers.
3. Add a long-running watchdog daemon/scheduler.
4. Add real sandbox validation with isolated execution.
5. Add GitHub/skill-hub discovery and SKILL.md package ingestion.
