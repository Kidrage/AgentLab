# P2-G Context Governance & Information Processing Kernel

AgentLab needs Context Governance because different tasks require different evidence handling. Code, tests, legal text, tables, logs, web pages, screenshots, crawler batches, narrative prose, and abstract strategy prompts should not be packed into one generic prompt shape.

## Relationship to Other Governors

- **Task Router** decides which agents should work. Context Governance decides what information shape those agents receive.
- **Budget Governor** controls token/cost envelopes. Context Budget turns the information profile into max input/output and source/file limits.
- **Provider Governor** chooses safe provider behavior. Context Governance remains deterministic and does not call providers.
- **Skill Vault** can later consume context profiles to decide which skills are relevant, but P2-G does not implement Skill Governance.

## C0-C6 Compression Levels

- C0_direct: original short input, no compression.
- C1_trim: remove obvious noise/repetition.
- C2_extractive: exact source snippets only, no rewriting.
- C3_query_focused_compression: deterministic query-focused filtering placeholder.
- C4_hierarchical_summary: chunk/chapter summary placeholder.
- C5_graph_or_tree_index: entity/repo/decision graph or tree index placeholder.
- C6_externalize_and_drilldown: keep raw source external and pass refs/index.

## Scenario Table

| Scenario | Strategy | Lossy |
| --- | --- | --- |
| Code repository | repo map / refs / extractive snippets | no |
| Long report | query-focused + hierarchical placeholder | yes |
| Novel / narrative | chapter summaries + graph placeholder | yes |
| Image / screenshot | OCR/layout/crop mock refs | partial/extractive |
| Web search | clean markdown citation pack | yes |
| Crawler batch | schema batch summary + externalize | yes |
| Data/table/stream | schema/profile/local execution refs | no |
| Log/CI/stderr | error clusters + stack trace extract | extractive |
| Abstract reasoning | decision matrix + limited branches | yes |
| Tool output | filter + externalize full output | yes |
| Task history | structured condensation | yes |

## Exact Evidence Rules

Code, legal text, config, and tests forbid lossy compression because correctness depends on exact syntax, clauses, and assertions. They use C0/C2/C5/C6 only.

## Data Tasks

Data/table tasks should be profiled and executed locally because full tables can exceed context budgets and LLMs are not reliable database engines. P2-G externalizes full data and includes schema/sample/profile placeholders.

## Tool Output

Huge tool output often contains noisy progress lines. P2-G filters/tails/extracts stack traces while externalizing the full output for drilldown.

## Future Integrations

This deterministic kernel can later connect to LLMLingua, GraphRAG, RAPTOR, Crawl4AI, Firecrawl, Playwright MCP, LiteLLM, and Langfuse.

## P2-G Limits

No real web, no real OCR, no real crawler, no LLM compression, no external API calls, no external skill execution.
