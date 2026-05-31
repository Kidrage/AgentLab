# Risk Findings

## Identified Risks

- **Task Lifecycle**: 0/20 — needs improvement
- **Artifact Completeness**: 0/15 — needs improvement

## Unresolved Issues

- Budget benchmark uses char/4 estimation, not tiktoken
- Provider failover is simulated, not tested against real API
- Web UI needs full integration with task discovery
- Terminal chat /find commands need REPL integration

## Recommendations

1. Install tiktoken for accurate token counting
2. Implement real fake provider with config-based responses
3. Add Terminal chat /find handler in terminal_chat.py
4. Extend Web UI with task-find API endpoint
