# AgentLab Company Model

AgentLab is evolving from a local agent runtime into a local-first AgentOps control layer.

It can coordinate external skill providers such as ECC, AnySearch, CodeGraph, Cline/Codex, but it does not blindly depend on them. AgentLab tracks cost, resources, evidence, skill usage, and internal skill incubation.

The operating model is:

```text
AgentLab
  → scans external skill / harness / agent packs
  → records an inventory
  → imports disabled external skill metadata
  → marks source, capability, risk, license, cost, fallback
  → records planned / used / skipped / rejected / distilled events
  → proposes internal_skill_candidate entries for high-value workflows
```

Strategic rule:

```text
External open-source skills can be used, but AgentLab must not become dependent on uncontrolled providers. It should learn from repeated high-value workflows by distilling methods, process templates, checklists, adapter experience, and safety constraints—not third-party source code.
```

P1-A explicitly does not support:

- No ECC execution yet.
- No AnySearch API execution yet.
- No CodeGraph indexing yet.
- No external IDE handoff yet.
- No automatic source code copying.
- No license bypass.
- No enabling hooks/MCP/commands by default.
- No LiteLLM Proxy, database, Redis, Postgres, dashboard, multimodal stack, or heavy dependency.

P1-A.1 closes the lightweight external skill workflow without changing those
boundaries. The supported loop is static inventory → disabled metadata import →
usage ledger → internal candidate proposal → read-only MCP inspection. Runtime
scan and incubation artifacts live under `artifacts/` or task `artifacts/`
directories and are not long-lived repository root files.
# Search And Repo Intelligence Providers

AnySearch is modeled as an optional external intelligence department for web
search, vertical search, URL extraction, and batch search. CodeGraph is modeled
as an optional local code intelligence department for repo indexing and symbolic
query metadata. Both departments are disabled by default, evidence-gated, and
tracked through cost/resource/skill ledgers with unknown costs represented as
unknown/null rather than zero.
