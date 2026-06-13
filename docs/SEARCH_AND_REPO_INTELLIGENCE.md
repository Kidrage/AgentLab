# Search And Repo Intelligence

AgentLab now has two independent optional provider layers:

- AnySearch: external web/search/URL intelligence.
- CodeGraph: local checkout code intelligence.

They are separate adapters and neither depends on the other. Both are disabled
by default and must leave evidence artifacts when planned, skipped, rejected, or
used. ArtifactGate checks claims such as "searched web", "used AnySearch",
"indexed repo", and "queried CodeGraph" against their ledgers.

Repeated successful usage can propose internal skill candidates:

- `internal.web_research_checklist_from_anysearch`
- `internal.repo_indexing_strategy_from_codegraph`

Candidate records set `source_code_copied: false` and keep license review
flags conservative. No external SDK, MCP server, LiteLLM proxy, multimodal
pipeline, database, dashboard, or heavy service is added.

