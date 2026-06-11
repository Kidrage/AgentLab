# AgentLab Skill And Feedback Roadmap

This document separates current scaffold behavior from production AgentOps behavior.

## Current: Implemented

### Skill Evolution Scaffold

- `skills/registry.yml` is the local skill registry scaffold.
- `projects/<Project>/skill_requests/` stores pending Skill Adoption Requests.
- `projects/<Project>/runs/<task_id>/skill_candidates/` stores trace-to-skill candidates.
- `skill-request` creates a pending request with risk metadata and cost preview.
- `skill-status` summarizes active skills and pending requests.

### Feedback Loop Scaffold

- `task_events.jsonl` stores a per-task event timeline.
- `decision_cards/*.yml` stores pending approval cards.
- `feedback_status.json` stores a machine-readable feedback summary.
- Pipeline node starts/completions write events.
- Pipeline blocked paths write `USER_DECISION_REQUIRED.md`, a decision card, task events, and feedback status.
- `decision-list`, `decision-approve`, `decision-reject`, and `decision-resume` provide a CLI approval protocol.

## Current: Not Yet Production Ready

### Skill Evolution

- No GitHub or skill hub search.
- No automatic SKILL.md/package parsing.
- No sandbox learning or script validation.
- No promotion workflow from staging to active.
- No skill retrieval/injection during task planning.

### Feedback And Intervention

- No long-running watchdog daemon.
- No SSE/WebSocket event stream.
- No webhook/Telegram/OpenClaw/Hermes push channel.
- No chat-native approval parser.
- Web UI is not yet fully backed by decision cards.

## Next Implementation Targets

1. Connect Web UI decision handling to `decision_cards/*.yml`.
2. Add `GET /api/task/events/stream` using Server-Sent Events.
3. Add a watchdog command that scans running tasks and emits `STALE_RUNNING`.
4. Add skill staging and fake sandbox validation.
5. Add task startup skill retrieval and explicit load-cost budgeting.
