# Skill Discovery Roadmap

AgentLab intentionally keeps external skill discovery disabled in this phase.
Future discovery work must remain manual-approval-first and safe by default.

## P2-G: Research/Search Ingestion

- 接入 Researcher 的搜索资料摄取。
- Generate `research_notes.md` and `source_ledger.yml`.
- 不允许自动安装 skill。

## P2-H: External Skill Discovery / Reliable Skill Radar

- 搜索 GitHub / 指定 skill registry / raw `SKILL.md`。
- 计算 trust score。
- 做 allowlist / license / dangerous content / conflict check。
- 生成 `discovery_candidates`。
- 必须人工审批。
- 不允许自动 promote。

## Deferred

No full GitHub skill repo search, automatic unapproved external skill learning, production-grade supply-chain scanner, real sandbox execution, automatic external skill promote, real web search provider HTTP call, or production external adapters are implemented here.
