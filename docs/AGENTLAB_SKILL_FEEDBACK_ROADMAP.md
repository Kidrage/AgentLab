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
- `skill_usage.yml` records task-level selected/rejected skills.
- `skills/active/<skill_id>/usage_ledger.yml` records each selected skill usage.
- High-risk skills are rejected for injection when policy requires approval.

### External Skill Import MVP

- `agent_runtime/external_skill_importer.py` implements `fetch_skill_markdown_from_url`, `parse_skill_frontmatter`, `build_external_skill_request`, and `import_skill_from_url`.
- `config/external_skill_import_policy.yml` controls allowlist, network access, byte limits, and snapshot settings.
- External URLs must be in the allowlist; network access is off by default.
- Primary smoke URL: `https://raw.githubusercontent.com/openclaw/skills/main/skills/killerapp/agentskills-io/SKILL.md` (`agentskills-io`).
- Import always creates `pending_user_approval` requests; zero external code execution.
- Source snapshots are saved under `projects/<Project>/skill_requests/<request_id>/source_snapshot/SKILL.md`.
- `tests/fixtures/external_skills/agentskills-io/SKILL.md` provides a no-network fixture.
- `tests/test_external_skill_importer.py` covers 11 fixture tests; `test_external_skill_importer_live.py` provides an optional live smoke test gated by `AGENTLAB_RUN_EXTERNAL_SKILL_LIVE_TEST=1`.

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
- `webhook-test`, `webhook-status`, and `webhook-redeliver` manage delivery testing and logs.
- `docs/WEBHOOK_INTEGRATION.md` documents OpenClaw/Hermes/chat gateway integration.
- Optional MCP-style stdio tool server is implemented in `agent_runtime/mcp_server.py`.
- MCP tools cover task status/events/reports, decision approval, task controls, skill requests, webhook status, and watchdog scan.
- `docs/MCP_INTEGRATION.md` documents local stdio configuration and security policy.

## Current: Not Yet Production Ready

### Skill Evolution

- No GitHub or skill hub search.
- No real sandbox execution (only fake sandbox file checks).
- No automatic SKILL.md/package parsing.
- No model-based candidate synthesis; Trace-to-Skill MVP uses deterministic event/report pattern detection.
- No automatic promotion of learned skills; candidates still require approval and the existing lifecycle.

### Feedback And Intervention

- No long-running watchdog daemon.
- No Telegram-specific bot adapter or OpenClaw/Hermes-specific command parser.
- No chat-native approval parser.
- No full MCP SDK wrapper; current MVP is a minimal dependency-free stdio JSON-RPC tool server.
- WebSocket is not implemented; current real-time MVP uses Server-Sent Events.

## Next Implementation Targets

1. Add full MCP SDK wrapper if a target client requires strict SDK behavior.
2. Add Telegram/OpenClaw/Hermes-specific chat command parsers.
3. Add a long-running watchdog daemon/scheduler.
4. Add real sandbox validation with isolated execution.
5. Add GitHub/skill-hub discovery and SKILL.md package ingestion.
