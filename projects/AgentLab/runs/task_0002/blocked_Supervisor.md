# User Decision Required

Status: blocked_user_decision
Reason: deepseek unavailable for required brain work.

Failure class: provider_error

Error:
Request timed out.

AgentLab policy requires DeepSeek to perform the brain/planning/review layer.
Codex must not silently take over this brain stage. Ask the user whether to:

1. Pause and retry after DeepSeek is available.
2. Explicitly change policy for this task and allow Codex manual simulation.
