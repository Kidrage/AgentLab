# Risk Register

## task_0001

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Static sample data can drift from runtime config. | Medium | Generate the snapshot from `config/agent_registry.yml` in a future CLI command. |
| Browser visual verification was unavailable in this session. | Low | HTTP loading and JSON validation were completed; run visual QA when the in-app browser is available. |
| Codex Plus exact quota cannot be read automatically. | Medium | Keep quota handling ledger-based until a reliable API/status source exists. |
