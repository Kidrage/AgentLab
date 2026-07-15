# AgentLab Current-Version Capability Reference

Language: [English](CURRENT_VERSION_CAPABILITIES.en-US.md) | [中文](CURRENT_VERSION_CAPABILITIES.zh-CN.md)

This manual describes the AgentLab capability surface implemented by the governance revision dated 2026-07-15. It is a reference for operators, reviewers, and contributors, not a promise that every configured provider is currently reachable.

## Contents

1. [Snapshot, positioning, and maturity](#1-snapshot-positioning-and-maturity)
2. [Architecture, governance, and lifecycle](#2-architecture-governance-and-lifecycle)
3. [The 15 roles, models, and boundaries](#3-the-15-roles-models-and-boundaries)
4. [Mission compilation, routing, and production chains](#4-mission-compilation-routing-and-production-chains)
5. [Writer, Ultracode, Supervisor, and Researcher](#5-writer-ultracode-supervisor-and-researcher)
6. [Multimodal observation, media production, and visual acceptance](#6-multimodal-observation-media-production-and-visual-acceptance)
7. [ArtifactTask and non-code deliverables](#7-artifacttask-and-non-code-deliverables)
8. [Capacity, windows, and checkpoint routing](#8-capacity-windows-and-checkpoint-routing)
9. [Pricing, budgets, usage, and execution economy](#9-pricing-budgets-usage-and-execution-economy)
10. [CLI, protocol, receipts, and errors](#10-cli-protocol-receipts-and-errors)
11. [Memory, context, handoff, skills, and recovery](#11-memory-context-handoff-skills-and-recovery)
12. [Safety and prohibited behavior](#12-safety-and-prohibited-behavior)
13. [Tests, doctors, CI, and acceptance](#13-tests-doctors-ci-and-acceptance)
14. [Operator command guide](#14-operator-command-guide)
15. [Current limits and unsupported paths](#15-current-limits-and-unsupported-paths)
16. [Authoritative source index](#16-authoritative-source-index)

## 1. Snapshot, positioning, and maturity

### Documented source snapshot

| Field | Value |
|---|---|
| Repository | `Kidrage/AgentLab` |
| Source revision | Dynamic runtime and CLI-shell governance change; merge target `main` |
| Commit identity | The commit containing this document and its implementation |
| Snapshot date | 2026-07-15 |
| Product stage | Active development; M-series alignment |
| Full local test baseline | `2734 passed, 24 skipped, 11 warnings` |
| Acceptance evidence | Private-workspace reports are historical; clean-checkout aggregation depends on local run assets |
| Live calls made for this verification | None |

Only tracked content in the implementation commit is authoritative for this manual. Private project runs and ignored local acceptance assets are not portable repository evidence and are identified as historical where referenced.

AgentLab has no semantic release tag for this snapshot. “Current version” means the documented implementation commit, not later local edits and not a claim that GitHub `main` already contains this branch before merge.

### Product position

AgentLab is a local-first AI Production OS and Project-to-Revenue OS. It governs long-running work while specialized CLIs, direct APIs, deterministic tools, mocks, or approved humans perform bounded execution.

It does not replace Codex, Claude Code, Hermes, Agy, Qwen, Grok, Cline, OpenClaw, Aider, or other front ends. It owns the durable truth around their work.

AgentLab retains authority over:

- mission and task contracts;
- route and production-pack selection;
- role-session packets and worker bindings;
- project brain, task state, and durable memory;
- evidence, cost, resource, and decision ledgers;
- validation, acceptance, recovery, and replanning;
- artifact lineage, candidate status, and promotion;
- final delivery state.

Executors retain only the bounded work delegated by their packet, CLI contract, allowed paths, and role boundary.

### Implemented maturity map

| Line | Implemented capability |
|---|---|
| P0 | CostLedger, pricing, BudgetGate, RepoManifest, CloneGuard, ResourceLedger, artifact evidence gate, pipeline runner |
| P1 | Disabled-by-default external skills, scan-only ECC inventory, external-agent handoff, local/dry-run adapters |
| P2 | 3E review, retry, routing feedback, context governance, failure capture, diagnosis, recovery, human decisions |
| S7 | Long-project brain, roadmap, phases, next action, acceptance, replan, summary, snapshot |
| S8 | Phase-aware executor packets, connector contracts, result ingestion, evidence review |
| S9 | Mock-first capability registry, permission gate, gap cards, provider passports, broker planning |
| S10 | Offline generalization suite and local CI gates |
| S11 | Read-only local ops snapshot and policy-checked local server plan |
| S12 | Service matching, deterministic quote/timeline estimate, risk notes, delivery skeleton |
| M1 | Project governance kernel and CLI-executor coordination are substantially implemented |
| M2 | CLI, TUI, WebUI, config, cost, event, approval, assistant, and control-plane surfaces exist at mixed maturity |
| M3 | Project-to-revenue concepts remain a roadmap; service and asset foundations do not yet equal a complete revenue OS |

Acceptance labels have narrow meanings:

- `pass`: the cited contract or deterministic behavior is proven for its stated scope.
- `candidate`: evidence exists, but production acceptance or a strict returned live closure is incomplete.
- `blocked`: a declared path exists but cannot proceed safely under current prerequisites.
- `unknown`: AgentLab lacks evidence and does not invent a positive status.

## 2. Architecture, governance, and lifecycle

### Governed flow

```text
user goal
-> mission contract
-> domain and risk classification
-> route decision
-> production pack
-> lifecycle profile
-> role-session or ArtifactTask packets
-> bounded executor work
-> receipts and evidence ingestion
-> review, retry, recovery, or replan
-> acceptance decision
-> explicit memory or artifact promotion
-> final delivery state
```

The system separates four identities that older agent frameworks often merge:

| Identity | Meaning |
|---|---|
| AgentLab role | Responsibility and authority, such as Supervisor or Writer |
| Worker | Concrete CLI, API, tool, or human executor |
| Invocation contract | Exact command shape, packet type, parser, and receipts |
| Model capacity route | Model, provider pool, fallback edges, modality limits, and breaker state |

### Runtime layers

| Layer | Main responsibility | Representative sources |
|---|---|---|
| Mission | Parse a request into goal, constraints, risk, project type, and deliverables | `agent_runtime/brain/`, `agent_runtime/goals/`, `agent_runtime/run_task.py` |
| Routing | Choose the smallest safe route and production pack | `agent_runtime/task_router.py`, `config/routing_rules.yml`, `config/domain_route_packs.yml` |
| Lifecycle | Activate only the nodes required by the selected pack | `agent_runtime/lifecycle_graph.py`, `agent_runtime/pipeline_runner.py` |
| Roles | Bind responsibilities to permitted workers and sessions | `config/agent_registry.yml`, `config/agent_role_bindings.yml` |
| Execution | Resolve exact CLI/API contracts and enforce scope | `agent_runtime/agent_runner.py`, `agent_runtime/cli_executor.py` |
| Evidence | Validate outputs, manifests, receipts, hashes, and gates | `agent_runtime/artifact_contract.py`, `agent_runtime/pipeline_runner.py` |
| Governance | Budget, approvals, capacity, recovery, and policy | `agent_runtime/model_capacity.py`, `agent_runtime/approvals/`, `agent_runtime/recovery/` |
| Memory | Persist task state, project brain, handoff, ledgers, and accepted facts | `agent_runtime/state_store.py`, `agent_runtime/project_brain/`, `agent_runtime/repository_handoff.py` |

### Canonical 24-node lifecycle

The graph has 24 ordered nodes. A production pack activates a subset; inactive optional nodes are marked skipped with a reason.

| # | Node | Primary evidence |
|---:|---|---|
| 1 | `INIT_TASK` | `user_request.md`, `state.yml` |
| 2 | `CONTEXT_PROFILE` | `context_profile.yml` |
| 3 | `CONTEXT_BUDGET` | `context_budget.yml` |
| 4 | `CONTEXT_PACK` | `context_pack.yml`, `compression_trace.yml` |
| 5 | `PREPARE_PLAN` | `workflow_plan.yml` |
| 6 | `SUPERVISOR_PLAN` | `01_supervisor_plan.md` |
| 7 | `REPO_CONTEXT` | `02_reposcout_report.md` |
| 8 | `RESEARCH_OPTIONAL` | `03_research_notes.md` |
| 9 | `OBSERVATION_OPTIONAL` | `observation_report.yml` |
| 10 | `INTERFACE_OPTIONAL` | `04_interface_map.md` |
| 11 | `WRITER_DRAFT` | `fiction_draft.md` |
| 12 | `FICTION_REVIEW` | `fiction_review.yml` |
| 13 | `SCRIBE_LEDGER` | `continuity_ledger.yml` |
| 14 | `CODER_IMPLEMENTATION` | `06_implementation_report.md` |
| 15 | `ARTIFACT_PRODUCTION` | `artifact_producer_report.md` |
| 16 | `VISUAL_OBSERVATION` | `visual_observation_report.yml` |
| 17 | `VISUAL_REVIEW` | `visual_review_report.yml`, `media_qc_report.yml` |
| 18 | `VALIDATION` | `07_validation_report.md` |
| 19 | `AUDIT` | `08_audit_report.md` |
| 20 | `VERIFY` | `verification_report.md` |
| 21 | `ARCHIVE` | lineage, promotion plan, archive receipt, archive update |
| 22 | `SELF_CHECK` | `self_check_report.yml` |
| 23 | `SYNC_OPTIONAL` | `sync_report.yml` |
| 24 | `FINALIZE` | `task_card.yml`, `artifact_manifest.yml` |

Lifecycle state supports `new`, `planned`, `in_progress`, `paused`, `blocked`, `recoverable`, validation/audit/archive/sync states, `completed`, and `failed`.

Atomic state updates, checkpoints, progress files, locks, heartbeats, stale-lock recovery, and resume logic make interrupted work inspectable instead of chat-dependent.

### Seven configured production packs

| Pack | Purpose | Active shape |
|---|---|---|
| `code_factory` | Build, repair, refactor, test, and audit codebases | Repo context and optional research/interfaces, Coder, validation, audit, verify, archive |
| `narrative_longform` | Candidate chapters, bounded chapter batches, and heavy narrative audit | Writer path or Reviewer/Scribe/Verifier audit path with continuity memory |
| `article_light` | Short prose, report, or article draft | Supervisor, ArtifactProducer, structure check, self-check |
| `read_only_observation` | Assigned long text, image, video, audio, PDF, or document inspection | Read-only staging, hash checks, Observer evidence, no project write |
| `media_series_production` | Multi-episode image/video continuity | Story/visual bibles, shot and asset ledgers, generation, independent visual acceptance |
| `media_generation` | Single image/video generation or edit | Backend contract, generation receipts, real-asset QC, explicit promotion boundary |
| `generic_artifact` | Safe fallback for a simple non-code deliverable | ArtifactTask, validation, verification, candidate delivery |

Known domains reuse a configured pack. A simple one-shot non-code request may use `generic_artifact`.

An unknown complex non-code domain enters synthesis mode. It must create `production_pack_proposal.yml`, `domain_memory_contract.yml`, and `lifecycle_profile.yml`.

The synthesized pack is proposal-only. `pack-candidate-validate` checks it, and `pack-candidate-promote` requires approval before catalog or production use.

## 3. The 15 roles, models, and boundaries

The model column below shows the canonical `full_cli` performance default. Full and low tiers may select different models or skip optional roles.

| Tier | Role | Current performance default | Responsibility | Hard boundary |
|---|---|---|---|---|
| T1 | Supervisor | Hermes JSON-RPC + OpenAI Codex OAuth, GPT-5.5, `high` | Mission, plan, route, scope, budget, recovery, synthesis | No source edits; no producer takeover |
| T2 | RepoScout | Claude Code + DeepSeek V4 Pro | Repository map, dependencies, code context | Read-only inspection |
| T2 | Researcher | Agy OAuth + Gemini 3.5 Flash High | Sourced external evidence | No code, prose production, media generation, or uncited authority |
| T2 | Observer | Agy OAuth + Gemini 3.5 Flash High | Assigned-input multimodal evidence | No browsing, mutation, production, or self-approval |
| T2 | InterfaceMapper | Claude Code + DeepSeek V4 Pro | Interfaces, schemas, contracts, cross-layer seams | Read-only; no implementation |
| T2 | PromptEngineer | Claude Code + DeepSeek V4 Flash | Reproducible implementation prompt from approved context | No source edits or shell execution |
| T3 | Coder | Claude Code shell + DeepSeek V4 Pro | Approved source implementation and candidate code artifacts | Only Supervisor-approved scope and non-destructive commands |
| T3 | ArtifactProducer | Claude+DeepSeek for text; approval-gated Bailian/Ark for media | Typed non-code candidate production | No generic untyped work, code ownership, self-acceptance, or promotion |
| T3 | Writer | Claude Code + DeepSeek V4 Pro | Final-quality candidate longform prose and narrative ledgers | No planning takeover, browsing, source edit, or fact promotion |
| T3 | NarrativePlanner | Claude Code + DeepSeek V4 Pro | Evidence-bound continuity repair and rewrite proposals | Proposal-only; no direct candidate or production edits |
| T4 | Reviewer | Claude+DeepSeek for text; Agy/Gemini for visual | Independent narrative or visual quality review | Does not rewrite by default; no generation or promotion |
| T4 | Scribe | Claude Code + DeepSeek V4 Flash | Continuity, character, timeline, item, relation, and foreshadowing ledgers | Proposed state is not accepted project fact |
| T4 | TesterAuditor | Claude Code + DeepSeek V4 Pro | Test evidence, diff interpretation, risk and behavior audit | Evidence only; no unsupported pass claim |
| T4 | Verifier | Claude Code + DeepSeek V4 Pro | Output contract, handoff completeness, integrity, independence | Does not patch implementation or pretend to perceive media |
| T5 | Archivist | Claude Code + DeepSeek V4 Flash | Accepted memory, archive, changelog, index, durable continuity | No archive or promotion before acceptance |

The public operating model and role-chain audit both cover 15 governed roles, including PromptEngineer and NarrativePlanner.

### Role/worker separation

- Every formal role assignment requires a role session.
- Frontdesk profiles cannot be reused as worker-role sessions.
- A worker must be explicitly allowed for the assigned role.
- A role name does not authorize a worker, model, tool, shell, or write path by itself.
- CLI workflow shells may coordinate internal steps, but AgentLab still owns every role receipt and final acceptance.

Important worker restrictions:

| Worker | Allowed role scope | Explicitly important exclusions |
|---|---|---|
| Agy | Observer, Reviewer | Never Supervisor, Coder, ArtifactProducer, Writer, Scribe, TesterAuditor, Verifier, or Archivist |
| Grok worker | Explicit quarantined Researcher or ArtifactProducer canaries only | Never selected automatically; never Writer, Coder, Reviewer, Verifier, or Supervisor |
| OpenClaw | Frontdesk only | No worker roles |
| Codex | RepoScout, InterfaceMapper, Coder, ArtifactProducer, Scribe, TesterAuditor, Verifier | No Supervisor, Observer, Researcher, Writer, Reviewer, or Archivist |
| Claude Code | Most reasoning/code/text/artifact/review/archive roles, including NarrativePlanner | Not Observer |
| Hermes | Supervisor, Researcher, PromptEngineer, Coder, TesterAuditor, Verifier, Archivist | Not Observer, ArtifactProducer, Writer, Reviewer, or Scribe |
| Qwen | Registered multimodal or metered fallback for Supervisor, Researcher, PromptEngineer, ArtifactProducer, Reviewer, and Scribe | Not a default generic-text route; not Observer, Coder, Writer, TesterAuditor, Verifier, Archivist, or NarrativePlanner |

Deterministic workers are also role-bound: `rg` for RepoScout, `ast_grep` for InterfaceMapper, `pytest` for TesterAuditor, linters/type checkers for Verifier, and `git` for Archivist.

## 4. Mission compilation, routing, and production chains

### Route decision

AgentLab classifies project size, task domain, required capabilities, risk, interfaces, research needs, budget, and output type. The routing strategy is `smallest_safe_route`.

Code sizes are L1, L2, and L3. Keyword and structural signals select small, medium, interface-sensitive, research-sensitive, evaluation, or large/risky paths.

Non-code tasks are routed by domain before code assumptions are applied. A media or narrative task must not inherit a Coder report, code diff, interface map, or code-only archive gate merely because AgentLab began as a code factory.

### Main route families

| Route | Default chain | Notes |
|---|---|---|
| `observation_task` | Supervisor -> Observer | Analysis-only assigned-input path |
| `small_task` | Supervisor -> Coder | TesterAuditor may be added by policy |
| `medium_task` | Supervisor -> RepoScout -> Coder -> TesterAuditor -> Verifier -> Archivist | Standard code route |
| `interface_sensitive_task` | Medium chain + InterfaceMapper | Contract and cross-layer changes |
| `research_sensitive_task` | Supervisor -> Researcher -> Coder -> TesterAuditor -> Verifier -> Archivist | External facts required |
| `large_or_risky_task` | Supervisor -> RepoScout -> Researcher -> InterfaceMapper -> Coder -> TesterAuditor -> Verifier -> Archivist | L3 architecture/security/migration path |
| `evaluation_task` | Supervisor -> RepoScout -> Researcher -> InterfaceMapper -> TesterAuditor -> Verifier -> Archivist | Analysis-only; no Coder |
| `artifact_production_task` | Supervisor -> ArtifactProducer -> TesterAuditor -> Verifier -> Archivist | Typed non-code artifact route |
| `media_generation_task` | Supervisor -> ArtifactProducer -> Observer -> Reviewer -> TesterAuditor -> Verifier | Candidate media and independent acceptance |
| `narrative_light_chapter` | Supervisor -> Writer | Candidate chapter plus minimal continuity closure |
| `narrative_batch_chapters` | Supervisor -> Writer | Bounded candidate batch plus batch ledgers |
| `narrative_heavy_audit` | Supervisor -> Reviewer -> Scribe -> Verifier | Audits existing prose; does not draft by default |
| `article_light_draft` | Supervisor -> ArtifactProducer | Draft plus structure check |

The legacy `fiction_chapter_pipeline` remains for compatibility. New work should use light Writer routes and a separate heavy audit instead of activating every narrative role on every chapter.

### Inspecting and persisting routes

`route-probe` reads natural language and shows the route, agents, pack, and source without creating task evidence or launching a worker.

`route-task` resolves AgentLab roles to concrete workers for an existing task packet and persists assignment evidence. It is a different, later decision.

`assign-role` performs one policy-governed assignment. ArtifactProducer requires `--artifact-type`; an untyped generic assignment is rejected.

`init-task` is route-aware when it receives a concrete request. It creates only relevant placeholders. A blank request keeps the legacy shell because no safe domain decision is possible.

`prepare` writes the mission-aware workflow plan, filters inactive roles, records the production pack, and derives route-specific artifact intent and validation gates.

### Candidate-first production

Non-code outputs and media are produced under the run directory first. Their ledgers may propose project memory or production paths, but they do not write accepted production state automatically.

Code can also be materialized as a run-local candidate under an approved artifact root. Production source edits remain governed by Supervisor scope and patch policy.

## 5. Writer, Ultracode, Supervisor, and Researcher

### Ordinary Writer

The ordinary Writer is Claude Code running DeepSeek V4 Pro through `claude_writer`. The sealed packet permits prose and declared narrative ledgers, not a general Claude workspace session.

The exact contract pins:

- selected model;
- `--effort max`;
- `--max-budget-usd 1.00`;
- `--permission-mode plan`;
- `--output-format json`;
- an empty tool list;
- one sealed packet path;
- no browsing, source edits, subagents, or role planning.

Required outputs are route-dependent. The single-chapter baseline includes `fiction_draft.md`, `continuity_ledger.yml`, `state_transition_proposal.yml`, and `narrative_delivery_receipt.yml`.

Writer model choice is recomputed at checkpoints. Pro satisfies the current
full/performance floors; Flash is eligible only when the active floor permits
it. A failed Writer call is never rerun on another model in the same call.

### Developmental Ultracode

Ultracode is a separate developmental route. It is not a stronger ordinary Writer setting and cannot be inferred from a request for higher quality.

Activation requires a sealed packet with:

```yaml
ultracode_opt_in: true
writer_mode: developmental_ultracode
work_type: developmental_edit | structure | continuity | revision_plan
```

`final_prose_draft` is always forbidden. The contract permits bounded developmental subagents, has a `$2.00` ceiling, and requires `ultracode_activation_receipt.yml` plus a revision plan.

`WriterUltracode` has no automatic fallback to ordinary drafting. A missing shell capability stops and reports.

Operator entrypoint:

```bash
./agentlab.sh run-agent Writer \
  --project <Project> \
  --task-id <task_id> \
  --writer-ultracode \
  --writer-work-type revision_plan \
  --execute
```

### Supervisor

The canonical Supervisor uses the local Hermes loopback JSON-RPC service with provider `openai-codex`, model `gpt-5.5`, and reasoning `high`.

The registered reasoning level is `high`; AgentLab does not invent unsupported effort labels.

Runtime preflight verifies the profile state and exact argv prefix. Provider, model, fallback provider, and fallback model overrides are rejected when they depart from the sealed contract.

When Codex is ineligible, the next checkpoint may select Claude Code + DeepSeek
V4 Pro. That is a new route decision, not an in-call retry, and it retains the
Supervisor boundary.

Each invocation creates an isolated Hermes role session, reads normalized exact usage when available, and closes the session. Approval requests or provider/model drift fail closed.

### Researcher

The default Researcher uses Agy/Gemini OAuth. Grok remains a registered explicit contract but is quarantined from automatic routing until a fresh canary passes.

Its report must preserve URLs and retrieval timestamps, separate sourced facts from inference, and include an explicit Sources section.

Research evidence stays run-local until reviewed. The Researcher cannot write authoritative project memory, code, longform prose, media output, or aesthetic judgments.

Research output remains candidate evidence. Media generation uses a separate approval-gated production route; research success never authorizes media generation.

### Longform narrative delivery and heavy audit

The `narrative_longform` pack separates story authority, chapter packets, candidate prose, continuity ledgers, state proposals, review, rewrite planning, verification, and promotion.

A chapter packet reads the project fact snapshot, artifact index, production bible, current outline, candidate fact ledger, and at most three recently accepted candidate chapters.

The light-chapter candidate contract requires:

- `chapter_packet.yml`;
- `fiction_draft.md`;
- `continuity_ledger.yml`;
- `state_transition_proposal.yml`;
- `narrative_delivery_receipt.yml`.

Review gates cover continuity, character state, timeline, POV, style, scene goal, chapter hook, and word count.

Any blocking fiction review or a `fail`, `rejected`, or `needs_revision` verdict blocks archive and promotion.

Narrative evaluation has four levels: L0 source health, L1 historical-text audit, L2 candidate chapter execution, and L3 governance-scale simulation.

L2 supports audit-only, mock, and live modes, bounded chapter ranges, verified-chapter resume, and stop/continue policies.

At this snapshot, `narrative-eval run` defaults to live. Offline checking must select `audit-only` or `mock` explicitly.

Heavy audit assigns fiction/continuity reports to Reviewer, state proposals to Scribe, and revision/rewrite proposals to Verifier.

All outputs remain `candidate_only:true` and `production_modified:false`. The audit cannot directly edit production prose.

A blocking continuity report requires a nonempty rewrite proposal with `direct_draft_edits:false`.

Crown heavy-audit preparation bundles at most 20 chapters, records every source hash and character count, requires an empty production manuscript, and makes no provider call.

The 1,500-chapter L3 check is `governance_ledger_only`. It validates arc, chapter-state, foreshadowing, character, timeline, cadence, and promotion ledgers while generating zero prose chapters.

## 6. Multimodal observation, media production, and visual acceptance

### Read-only Observer

The primary Observer route uses Agy with Gemini 3.5 Flash High and supports text, image, video, audio, and PDF inputs.

A compatible checkpoint route can use the same Agy shell with Claude Sonnet
4.6 in a separate pool. It supports text, image, and PDF only.

Route reselection must preserve required modalities. A video or audio task cannot silently drop those inputs to use Claude.

The Observer reads only explicitly assigned staged inputs. It reports evidence, locators, uncertainty, scientific context, limitations, and actionable suggestions.

Required locators are:

| Medium | Locator evidence |
|---|---|
| Image | keyframes |
| Video | keyframes and timestamps |
| Audio | timestamps |
| PDF | pages |

The Observer cannot browse, generate media, write prose as Writer, modify project files, or approve its own conclusion.

### Media production and quarantined Grok canaries

The default image/video route uses the approval-gated Bailian CLI, with Ark as a configured premium option. The `grok_media` contract remains registered only for an explicit bounded canary while xAI is quarantined.

Registered generation models are `grok-imagine-image-quality` and `grok-imagine-video-1.5`.

A text response is not a media artifact. Success requires actual paths, sizes, SHA-256 hashes, prompt/parameter records, reference assets, validation notes, and generation receipts.

All media outputs are candidate-only. The producer must not write `media_qc_report.yml`, review aesthetics, or promote its result.

Configured backend routing also includes:

| Backend | State and boundary |
|---|---|
| `hermes_grok_oauth` | Quarantined; explicit bounded canary only |
| `grok_direct` | API-key fallback; explicit approval required |
| `bailian_cli` | Primary approval-gated image/video generation CLI |
| `ark_cli` | Configured premium generation CLI; activation and approval required |
| `agy_media` | Text-only visual preproduction observer; not a renderer |

These entries are backend options, not an automatic cross-provider fallback promise. The selected ArtifactTask, policy, auth state, approval, and capability contract remain authoritative.

At this snapshot, the executable adapter allowlist contains only local Grok CLI aliases and xAI Imagine REST. Catalog registration alone is not executable support.

### Independent visual acceptance

```text
ArtifactProducer creates a run-local candidate
-> Observer inspects the actual asset
-> Reviewer records four quality dimensions
-> Verifier checks integrity and independence
-> human or Supervisor explicitly promotes
```

Reviewer dimensions are:

- aesthetic quality;
- continuity;
- technical quality;
- factual safety.

Verifier checks are:

- asset integrity;
- evidence-chain completeness;
- reviewer independence;
- preservation of the promotion boundary.

The Verifier does not repeat aesthetic judgment or claim visual perception. It verifies the bound evidence and asset identity.

Policy requires path, nonzero size, SHA-256, workspace confinement, asset binding, session separation, and distinct reviewer identities.

Producer identity/backend/model cannot be reused as the reviewer. Observer and Reviewer may use the same Agy backend/model only in separate role sessions; the Verifier remains a distinct role and judgment.

`pending`, `unknown`, `missing`, failed, blocked, or incomplete evidence blocks promotion. The real asset is checked again at promotion time.

### Mock contracts

`vision-contract`, `audio-contract`, and `document-contract` are mock-only contract commands. They validate S9 evidence shapes and do not call a real perception backend.

Real media execution is disabled by default. `media-backend-execute` requires explicit live intent and all selected-backend gates.

## 7. ArtifactTask and non-code deliverables

ArtifactProducer accepts a typed `agentlab_artifact_task`, not a free-form role prompt.

Required contract fields are:

- `artifact_type`;
- `output.path`;
- `output.format`;
- `requirements`;
- `validation`;
- `routing`.

### Supported types and effective providers

| Artifact type | Formats | Current effective path |
|---|---|---|
| Text | Markdown, TXT, DOCX | Claude Code + DeepSeek V4 Pro; full-API text is limited to contracts without assigned local files |
| Image | PNG, JPG, WebP | Media production route: approval-gated Bailian/Ark |
| Video | MP4, MOV | Media production route: approval-gated Bailian/Ark |
| Spreadsheet | XLSX, CSV | Claude Code + DeepSeek V4 Pro |
| Presentation | PPTX, PDF | Claude Code + DeepSeek V4 Pro |
| Audio | WAV, MP3 in schema | No current executable ArtifactTask provider; fail closed |
| Mixed | Directory in schema | No cross-provider composite adapter; fail closed |

Qwen artifact capacity follows a declared chain:

```text
Qwen 3.7 Max
-> Qwen 3.6 Plus on model_unavailable
-> Qwen 3.6 Flash on model_unavailable
```

Each edge is explicit. Quota, auth, arbitrary errors, or a desire to reduce cost do not authorize that chain.

### Assigned-input isolation

Assigned inputs are declared by relative source path, staged path, size, SHA-256, and read-only status.

The runtime rejects directories, symlinks, duplicate staged paths, traversal outside the allowed root, missing inputs, hash mismatch, and unlisted host reads.

The Qwen CLI runs in an isolated workspace. Directories are hardened to mode `0500`, files to `0400`, and only declared outputs may be copied back.

After the provider exits or times out, postflight checks the exact input set, symlink state, modes, inode, size, mtime, ctime, and SHA-256. Mutation blocks output materialization.

The same staged-input postflight boundary applies to Observer, visual Reviewer, and visual Verifier inputs.

### Structural validation

- XLSX, DOCX, and PPTX must be valid ZIP packages with `[Content_Types].xml` and their core Office entry.
- PDF, PNG, JPEG, WebP, MP4, and MOV must match their file signatures.
- YAML must parse; Markdown, TXT, CSV, and JSON must decode as UTF-8.
- Empty files, empty directories, and materialization above 512 MiB fail.

These checks prove structural delivery, not formula correctness, presentation aesthetics, or factual accuracy. Reviewer, Verifier, or human acceptance remains required.

### Failure contract

ArtifactTask returns explicit failure states:

| State | Meaning |
|---|---|
| `capability_mismatch` | Selected worker cannot satisfy the declared capability or format |
| `needs_fallback` | A policy-recognized reason requires an approved alternative |
| `validation_failed` | Files exist but fail declared validation |

An output claim without a real file is invalid. Candidate delivery requires the artifact manifest, materialization receipt, validation evidence, and role-specific delivery receipt.

## 8. Capacity, windows, and checkpoint routing

`config/runtime_registry.yml` is the Full CLI authority for routes, providers,
models, and credential pools. `model_capacity_ledger.yml` is the atomic,
run-local state ledger. The legacy capacity policy still supplies persistence
and compatibility commands, but it no longer performs same-call fallback for
dynamic Full CLI routes.

OAuth pools are probed through bounded interactive `/usage` sessions with the
exact profile or Agy model label. AgentLab persists only normalized remaining
percentages, windows, reset timestamps, and observation times. It does not
persist raw terminal output. Admission is denied at or below the five-percent
reserve, or when predicted unit usage plus risk reserve needs more headroom.
Long batches fail closed without fresh, parseable remaining quota. An observed
reset triggers a new probe; time alone never proves recovery.

Selection is deterministic: hard state/modality/privacy/provider/quota filters,
then a quality floor, then predicted cash, quota scarcity, retry, latency, and
switch costs. `full`, `performance`, and `low` are quality floors rather than
fixed model matrices.

A provider failure is normalized and recorded, then that call ends. AgentLab
does not change shell or model and rerun inside the same call. Only the next
completed checkpoint invokes selection again. Pool-scoped failures are
`auth_missing`, `quota_exhausted`, and `rate_limited`; `model_unavailable` is
model-scoped; `unknown` never authorizes a switch.

The default candidates are Hermes/Codex then Claude+DeepSeek for Supervisor;
Agy Gemini then the independent Agy Claude pool for compatible Observer and
visual-review inputs; and paid Qwen Max/Plus/Flash routes selected by their
actual quality floor when needed. Video/audio cannot silently drop to a
text/image/PDF-only route. Writer uses Pro for full/performance and may use
Flash only when the active quality floor permits it. Grok remains quarantined
at the route, shell, adapter, provider, and model layers.

## 9. Pricing, budgets, usage, and execution economy

`config/model_pricing.yml` is the single numeric runtime-pricing authority. Other model and provider catalogs may identify models but must not duplicate prices.

`config/pricing_catalog.yml` is a runtime projection: it stores model mappings,
billing modes, and versioned FX only. Metered entries resolve safe `source_ref`
links to the numeric authority at load time. Receipts preserve supplier-native
currency and perform one conversion through the named FX snapshot.

### Text-token pricing at this snapshot

Prices are USD per one million tokens. Cache is shown only when separately declared.

| Model | Input | Cache read | Output | Runtime note |
|---|---:|---:|---:|---|
| Qwen 3.7 Max | 1.650 | — | 4.951 | China-first DashScope reference |
| Qwen 3.6 Plus | 0.276 | — | 1.651 | DashScope reference |
| Qwen3 Coder Next | 0.144 | — | 0.574 | Qwen Coder reference |
| Qwen3 Coder Plus | 0.574 | — | 2.294 | 0–32K pricing tier |
| Qwen 3.6 Flash | 0.165 | — | 0.990 | DashScope reference |
| DeepSeek V4 Flash | 0.140 | 0.002800 | 0.280 | Cache-miss input plus cache-hit rate |
| DeepSeek V4 Pro | 0.435 | 0.003625 | 0.870 | Cache-miss input plus cache-hit rate |
| Grok 4.3 | 1.250 | 0.200 | 2.500 | API reference only; do not charge Hermes xAI OAuth as API usage |

### Media unit pricing

| Model | Unit | USD |
|---|---|---:|
| Grok Imagine Image Quality | Input image | 0.01 |
| Grok Imagine Image Quality | Output image, 1K | 0.05 |
| Grok Imagine Image Quality | Output image, 2K | 0.07 |
| Grok Imagine Video 1.5 | Input image | 0.01 |
| Grok Imagine Video 1.5 | Output video, 480p second | 0.08 |
| Grok Imagine Video 1.5 | Output video, 720p second | 0.14 |
| Grok Imagine Video 1.5 | Output video, 1080p second | 0.25 |

Media units must never be fed into a text-token estimator.

### Unknown pricing

Subscription-backed runtime work stays `unavailable` for exact per-token cost unless the provider reports a billable metric. A known public API price does not convert an OAuth subscription call into API billing.

Numeric zero is treated as unknown unless a row explicitly declares a free model. Missing usage is not reconstructed from prompt length when reported telemetry is required.

### Budget and cost controls

| Control | Behavior |
|---|---|
| Budget modes | `brain_allocated`/performance, `max_quality`/full, `frugal`/low |
| Project size | L1, L2, L3 influences route and tier |
| Budget planner | Allocates model and context budgets before execution |
| BudgetGate | Blocks work that exceeds approved policy |
| CostLedger v2 | Records reported usage, attribution, estimates, and status |
| Execution economy | Estimates activation cost, spawn cost, context reuse, cache profile, escalation, and marginal utility |
| Alerts | Surfaces configured thresholds without fabricating spend |
| Efficiency review | Compares work and evidence against cost records |

Model execution receipts bind role, route, model key, provider, attempt, capacity route, pricing source, session data, and reported usage when available.

Writer has a `$1.00` per-invocation contract ceiling. Developmental Ultracode has a separate `$2.00` ceiling.

## 10. CLI, protocol, receipts, and errors

### Command-surface inventory

At this snapshot, `./agentlab.sh --help` exposes exactly 253 top-level commands. Nested command families, such as `config` and `goal`, have additional subcommands.

The table lists every top-level command once, grouped by purpose.

| Group | Top-level commands |
|---|---|
| Interfaces, capabilities, roles | `tui`, `webui`, `capability-list`, `capability-check`, `capability-gap`, `capabilities`, `role-requirements`, `role-inspect`, `role-compatible-workers` |
| Entry, handoff, sessions, protocol, ArtifactTask | `repository-handoff`, `workspace-entry`, `frontdesk-context`, `frontdesk-session`, `role-session`, `frontdesk-doctor`, `frontdesk-write-gate`, `role-doctor`, `protocol-doctor`, `artifact-task-plan`, `artifact-doctor`, `cli-entrypoint-scan`, `cli-entrypoint-bootstrap`, `cli-entrypoint-install`, `cli-entrypoint-doctor`, `cli-entrypoint-status` |
| Routing, mock media contracts, backend, runtime hygiene | `route-probe`, `assign-role`, `route-task`, `route-explain`, `vision-contract`, `audio-contract`, `document-contract`, `media-backend-preflight`, `media-backend-execute`, `m2-operator-demo`, `runtime-doctor`, `runtime-layout`, `runtime-audit-symlinks`, `runtime-secret-scan` |
| Workers, execution economy, capability broker | `worker-scan`, `worker-list`, `worker-inspect`, `worker-doctor`, `worker-contracts`, `worker-contract-validate`, `worker-invocation-probe`, `worker-invocation-report`, `worker-audition`, `worker-scorecard`, `activation-plan`, `activation-explain`, `execution-economy-report`, `estimate-spawn-cost`, `cache-profile-report`, `capability-providers`, `capability-provider-inspect`, `skill-discover`, `mcp-discover`, `capability-broker-plan`, `provider-trust-report` |
| Evaluation, CI, operator console, service factory | `eval-generalization`, `ci-gates`, `ops-console-status`, `ops-console-serve`, `service-factory-plan` |
| Tasks, skill lifecycle, production-pack lifecycle | `init-task`, `task-clear`, `task-list`, `brain-status`, `harness-status`, `skill-status`, `skill-distill`, `skill-draft-list`, `skill-draft-approve`, `skill-draft-reject`, `skill-vault-list`, `skill-vault-status`, `skill-vault-migrate`, `skill-vault-backup`, `skill-vault-backup-status`, `skill-request`, `skill-list`, `skill-approve`, `skill-reject`, `skill-stage`, `skill-validate`, `skill-promote`, `skill-retire`, `pack-candidate-validate`, `pack-catalog-audit`, `pack-candidate-promote`, `production-pack-synthesis-smoke`, `production-pack-role-session-request`, `production-pack-role-session-audit`, `skill-match`, `skill-inject`, `skill-usage`, `skill-import-url` |
| Feedback, watchdog, webhooks, decisions, learning, policy | `feedback-status`, `watchdog-scan`, `watchdog-status`, `webhook-test`, `webhook-status`, `webhook-redeliver`, `task-event`, `decision-list`, `decision-approve`, `decision-reject`, `decision-resume`, `learning-review`, `skill-candidates`, `skill-candidate-approve`, `skill-candidate-reject`, `skill-candidate-list`, `skill-candidate-show`, `skill-registry-validate`, `policy-status`, `request-traversal`, `request-coder-quota`, `log-event` |
| Prepare, context, models, execution, task control, sync, providers | `prepare`, `status`, `project-workflow-plan`, `context-profile`, `context-budget`, `context-pack`, `context-show`, `context-audit`, `context-build`, `context-status`, `context-smoke`, `models`, `model-doctor`, `run-agent`, `run-pipeline`, `budget-eval`, `workspace-scan`, `performance-eval`, `progress`, `pause`, `resume`, `guard-status`, `recover`, `providers`, `chat`, `check`, `sync`, `sync-status`, `migration-doctor`, `migration-init`, `truenas-status`, `truenas-sync`, `backup-status`, `provider-test`, `provider-smoke`, `grok-cli-smoke`, `agy-cli-smoke` |
| Task discovery, artifacts, acceptance, WebUI smokes | `task-index`, `task-find`, `task-open`, `task-resume-candidates`, `task-map`, `task-artifacts`, `lifecycle-status`, `artifact-check`, `capability-acceptance`, `frontdesk-boundary-audit`, `web-ui-candidate-smoke`, `web-ui-browser-smoke`, `web-ui-interaction-smoke`, `web-ui-api-smoke`, `web-ui-visual-smoke`, `web-ui-responsive-smoke`, `production-chain-audit`, `agent-role-chain-audit`, `live-unblock-plan`, `external-acceptance-readiness`, `internal-live-readiness`, `frontdesk-live-handoff`, `cli-shell-coalescing-plan`, `cli-shell-coalescing-status`, `cli-shell-coalescing-runner-request`, `cli-shell-coalescing-runner`, `cli-shell-coalescing-collect`, `trusted-live-runner-request`, `trusted-live-runner-status`, `trusted-live-runner-operator-handoff`, `trusted-live-runner-collect`, `trusted-live-runner-preflight`, `acceptance-report-hygiene`, `goal-completion-audit`, `objective-requirement-audit`, `crown-live-candidate-audit`, `crown-scale-governance-audit`, `crown-completion-batch-audit`, `crown-heavy-audit-prepare`, `media-series-scaffold-audit` |
| Lifecycle driver, Codex bridge, daemon, P2, failure recovery | `run-next`, `doctor`, `codex-start`, `codex-status`, `codex-handoff`, `codex-resume`, `codex-verify-artifacts`, `continue-with-api`, `daemon`, `daemon-status`, `p2-capability-map`, `p2-closure`, `failure-diagnose`, `failure-status`, `recovery-plan`, `recovery-smoke` |
| Long projects, executor loop, ingestion, human recovery | `project-brain-init`, `project-plan`, `project-next`, `phase-accept`, `phase-replan`, `project-summarize-phase`, `project-snapshot`, `m1-demo`, `executor-task-create`, `executor-result-ingest`, `executor-review`, `ingest-artifact`, `ingest-repo-memory`, `recovery-brain-plan`, `recovery-approve`, `recovery-reject`, `recovery-stop`, `recovery-status`, `recovery-feedback`, `configure-agent` |
| Cost, approvals, timeline | `cost-status`, `cost-estimate`, `cost-alerts`, `cost-efficiency-review`, `approvals`, `approve`, `reject`, `timeline`, `event-log-tail` |
| Nested workflow families | `external-skills`, `search`, `repo-index`, `external-projects`, `mission-compiler`, `config`, `assistant`, `goal`, `governance`, `narrative`, `narrative-eval` |

### Strong protocol gates

| Gate | Requirement |
|---|---|
| Workspace entry | A worker receives the repository handoff, rules, scope, and local entry packet before project work |
| Frontdesk session | User-facing chat can talk, read state, create tasks, or propose changes; it is not a worker session |
| Role session | Formal role, worker binding, task packet, inputs, outputs, and permissions are explicit |
| Role binding | Every worker/role pair is allowlisted and reciprocal |
| ArtifactTask | ArtifactProducer receives a typed contract with exact output and validation |
| Delegation | Relay-only and explicit; no invisible authority expansion |
| Repository handoff | Discovered before deep reads and refreshed after material change |
| Git discipline | Scope, dirty files, evidence, commit, push, and CI are audited |

Protocol doctor treats missing strong docs/configs, mixed frontdesk/worker invocation, unbound workers, or roles without workers as failures. Handoff and Git discipline findings are warnings in the policy schema.

### Receipt hierarchy

| Receipt | What it proves |
|---|---|
| Workspace/frontdesk/role-session receipt | Which identity and governed session ran |
| Outbound context manifest | Exact files and hashes disclosed to an external worker |
| Model execution chain | Approved route attempts and fallback history |
| Model execution receipt | Actual argv-bound worker/model/provider/attempt and usage envelope |
| Capacity route receipt | Selected pool, route, capacity status, and fallback authority |
| Artifact materialization receipt | Exact declared files copied from an isolated workspace |
| Generation receipt and ledger | Producer, backend, model, prompt, parameters, references, and asset hashes |
| Review/verification receipt | Evidence dimensions, integrity checks, and identity separation |
| Promotion/archive receipt | Explicit acceptance and durable destination |
| Ultracode activation receipt | Explicit developmental opt-in and allowed work type |

Receipts are necessary but not interchangeable. Auth is not capacity, generation is not acceptance, review is not promotion, and a text response is not a file artifact.

### Error classes

| Error | Typical evidence | Default response |
|---|---|---|
| `invalid_cli_invocation` | Exit 2, usage, unrecognized or invalid choice | Stop and report command-contract failure |
| `auth_required` | Unauthorized, login, missing key/token | Stop or consult the declared capacity route |
| `network_required` | DNS, proxy, connection, timeout | Stop; retry only under approved network policy |
| `permission_denied` | Sandbox, filesystem, or access denial | Stop; do not widen scope silently |
| `quota_exhausted` | Explicit quota/subscription limit | Open pool breaker; follow approved edge only |
| `model_unavailable` | Unknown, unsupported, unavailable model | Block route; follow model-approved edge only |
| `rate_limited` | 429 or rate-limit response | Open pool breaker; honor observed reset |
| unknown | Unclassified failure | Preserve unknown and stop; no fallback inference |

## 11. Memory, context, handoff, skills, and recovery

### Local-first truth

The authoritative task state is `projects/<Project>/runs/<task_id>/`. Chat history is not a task database.

Typical task records include the request, workflow and Supervisor plan, role reports, state, progress, lifecycle, artifacts, costs, decisions, checks, and delivery receipts.

Authoritative project memory lives under `projects/<Project>/agent_docs/` and project-brain directories. Only validated or accepted evidence may update durable facts.

The memory policy tracks handoff, context pack, repository map, task ledger, decision log, interface registry, changelog, risk register, development log, dialogue log, cost ledger, and sync ledger.

### Context governance

| Length tier | Maximum characters | Strategy |
|---|---:|---|
| S | 2,000 | Direct |
| M | 12,000 | Trim and direct |
| L | 80,000 | Retrieve and compress |
| XL | 500,000 | Hierarchical summary |
| XXL | Unbounded by fixed threshold | Index and drill down |

Context classification covers code, long text, narrative, image, web, crawl, data, logs, abstract reasoning, tool output, and history.

Code uses repository-map context and does not allow lossy source substitution. Narrative uses narrative graphs. Data uses schema profiling and local execution. Tool output is filtered and externalized.

`context_profile.yml`, `context_budget.yml`, `context_pack.yml`, and `compression_trace.yml` make compression inspectable.

### Repository handoff

Before deep repository reads, AgentLab searches for `PROJECT_HANDOFF.md`, `.agentlab/HandOff.md`, `agent_docs/HandOff.md`, and compatible names.

The safe scan uses Git metadata, tracked paths, targeted search, and file metadata. It avoids recursive content dumps, binaries, secrets, dependency caches, symlink traversal, and full history dumps.

The handoff generator writes a root-visible copy, repository-local copy, compatible project-memory copy, and shared repository-memory copy where policy permits.

It preserves manual notes while refreshing deterministic identity, state, progress, directory routes, entrypoints, changes, validation, risks, and agent notes.

### Long-project brain

S7 stores mission, roadmap, milestone graph, phase plans, acceptance history, next actions, summaries, and snapshots without requiring a model call.

Phase acceptance can choose accept, retry, redesign, split, rollback, or ask the user. Replanning remains durable and traceable.

S8 turns a phase into an executor packet, ingests returned evidence without accepting it, and routes it back through phase review.

### Skills and learning

The skill lifecycle is request -> approve -> stage -> validate -> promote -> active -> retire. No discovery or draft becomes active automatically.

AgentLab can distill project memory into a skill draft, store candidates in the central Skill Vault, match active skills, inject them into a plan, and record usage.

Trace-to-Skill learning reviews task events and produces candidates. A human or governed decision must approve or reject them.

External skill import is network- and approval-gated. Validation does not imply trust, installation, or execution.

### Feedback, decisions, and recovery

Task events, decision cards, watchdog scans, webhook delivery, timelines, and event-log tails expose project progress and intervention points.

The failure stack captures an event, classifies it, diagnoses cause, proposes a recovery route, records a verdict, applies retry policy, and waits for human review when required.

Human recovery decisions are durable: approve retry, reject retry, or stop permanently. Resume follows the recorded decision and lifecycle checkpoint.

The daemon is an MVP background supervisor with a safe `--once` mode. It does not erase approval boundaries.

### Local operations and UI

- `tui` starts the terminal interface.
- `webui` starts the Web UI.
- S11 writes a read-only ops snapshot covering projects, phases, tasks, skills, capabilities, recovery, evidence, budget, and resources.
- Public bind addresses are rejected by default.
- Web UI candidate, browser, interaction, API, visual, and responsive smokes test run-local candidates.
- The CLI remains the primary reliable control surface.

TrueNAS and backup commands support status, migration preflight, push-oriented sync, manifests, and checksums. Commercial assets and credentials are excluded from public GitHub.

## 12. Safety and prohibited behavior

AgentLab is fail-closed by default.

It does not automatically:

- execute an external tool, model, worker, or provider;
- install a skill, package, dependency, plugin, or MCP server;
- browse, crawl, post, upload, or publish;
- bind a server publicly;
- switch worker, provider, model, role, or modality outside policy;
- accept an external result without evidence;
- promote a candidate artifact or proposed fact;
- infer subscription availability from auth;
- store a raw broad status response;
- put credentials in project memory, handoffs, logs, or public Git history.

Source and artifact writes require different authority:

- Coder may edit only Supervisor-approved source scope.
- ArtifactProducer may write only ArtifactTask-declared outputs.
- Observer, Reviewer, Researcher, TesterAuditor, and Verifier are non-mutating for their governed inputs.
- Archivist writes durable memory only after acceptance.
- Frontdesk may propose a change but cannot reuse that conversation as a worker session.

External agents and executor results remain evidence until validation and acceptance pass. A worker's confidence is not proof.

Secret scans, redaction, path confinement, symlink audits, Git ignore policy, outbound context manifests, and safe probes reduce accidental disclosure.

## 13. Tests, doctors, CI, and acceptance

### Verification baseline

| Check | Result |
|---|---|
| Full pytest | `2734 passed, 24 skipped, 11 warnings` |
| Focused dynamic runtime, pricing, Hermes, quota, and shell-governance set | `56 passed` |
| Model doctor | `pass`; 7 warnings for API keys absent from this worktree environment |
| Artifact doctor | `21/21 checks passed` |
| Protocol doctor | `110/110 checks passed` |
| Role/production-chain audit | Passed |
| Compile and diff integrity | `compileall` and `git diff --check` passed |
| Live provider or model calls during this validation | None |

The test numbers prove the committed orchestration, policy, and deterministic seams covered by the suite. They do not prove current subscription capacity or subjective quality of a future live output.

### Checked-in acceptance snapshot

`acceptance_runs/agentlab_capability_acceptance/current.yml` contains 32 capability rows:

- 27 `pass`;
- 5 `candidate`;
- overall status `candidate`.

The five candidate rows are:

| Capability ID | Why it remains candidate |
|---|---|
| `production_pack_synthesis_role_session` | Strict returned four-role closure and outbound governance evidence are incomplete |
| `crown_live_writer_light_path` | One candidate chapter satisfies its local delivery contract; production acceptance remains separate |
| `grok_xai_media_backend` | Adapter/preflight and historical smoke exist; fresh real-asset acceptance is not proven |
| `trusted_live_runner_status` | Required returned artifacts remain pending |
| `trusted_live_runner_collect` | Collector is waiting for accepted returned artifacts |

`docs/AGENTLAB_CAPABILITY_ACCEPTANCE_MATRIX.md` explains evidence, remaining gaps, and repeatable checks. Its frozen/historical rows must not override current role or capacity policy.

### Acceptance domains

The current evidence covers:

- code-factory orchestration and candidate Web UI materialization;
- non-code/code-shell separation;
- narrative chapter and batch governance;
- media-series scaffolding and visual gates;
- production-pack synthesis and catalog validation;
- package imports and workflow-plan stability;
- production-chain and role-binding consistency;
- frontdesk/worker separation;
- CLI shell capability and command-surface governance;
- task, handoff, context, cost, recovery, and acceptance reporting.

Provider smokes and historical live artifacts are scoped evidence. They are never a blanket promise of provider availability, quota, quality, private-project completion, or production promotion.

## 14. Operator command guide

All commands start at the repository root. Inspect `--help` before a live or state-changing operation.

### Read-only orientation

```bash
./agentlab.sh --help
./agentlab.sh doctor
./agentlab.sh policy-status --project AgentLab
./agentlab.sh models show
./agentlab.sh model-doctor
./agentlab.sh providers
./agentlab.sh repository-handoff --repo .
```

### Probe a request without creating a task

```bash
./agentlab.sh route-probe "Create a reviewed image from this reference"
./agentlab.sh role-inspect --role Observer
./agentlab.sh role-compatible-workers --role Observer
./agentlab.sh capability-check --capability generate_image
```

### Create and prepare a task

```bash
./agentlab.sh init-task \
  --project <Project> \
  --task-id <task_id> \
  --request-text "<goal>"

./agentlab.sh prepare \
  --project <Project> \
  --task-id <task_id> \
  --write-plan

./agentlab.sh status --project <Project> --task-id <task_id>
```

### Dry-run before execution

```bash
./agentlab.sh run-agent Supervisor \
  --project <Project> \
  --task-id <task_id>

./agentlab.sh run-pipeline \
  --project <Project> \
  --task-id <task_id> \
  --dry-run
```

`run-agent` and `run-pipeline` are dry-run-oriented by default. `--execute` is the explicit boundary for configured real execution.

### Typed artifact planning

```bash
./agentlab.sh artifact-task-plan \
  --task-text "Create a reviewed spreadsheet" \
  --project <Project> \
  --task-id <task_id> \
  --artifact-type spreadsheet

./agentlab.sh assign-role --role ArtifactProducer \
  --artifact-type spreadsheet

./agentlab.sh artifact-doctor
```

### Media readiness and acceptance

```bash
./agentlab.sh media-backend-preflight \
  --contract projects/<Project>/runs/<task_id>/media_generation_contract.yml

./agentlab.sh artifact-check \
  --project <Project> \
  --task-id <task_id>

./agentlab.sh production-chain-audit \
  --out acceptance_runs/agentlab_capability_acceptance/production_chain_audit.yml
```

Preflight does not generate media. A generated file remains a candidate until Observer, Reviewer, Verifier, and explicit promotion gates pass.

### Task control and recovery

```bash
./agentlab.sh progress --project <Project> --task-id <task_id>
./agentlab.sh pause --project <Project> --task-id <task_id>
./agentlab.sh resume --project <Project> --task-id <task_id>
./agentlab.sh lifecycle-status --project <Project> --task-id <task_id>
./agentlab.sh failure-diagnose --project <Project> --task-id <task_id>
./agentlab.sh recovery-status --project <Project> --task-id <task_id>
```

### Long-project governance

```bash
./agentlab.sh project-brain-init \
  --mission-contract <mission_contract.yml> \
  --project <Project> \
  --out projects/<Project>/project_brain
./agentlab.sh project-plan \
  --project-brain projects/<Project>/project_brain \
  --out <phase_plan_dir>
./agentlab.sh project-next \
  --project-brain projects/<Project>/project_brain \
  --out <next_action_dir>
./agentlab.sh phase-accept \
  --phase-plan <phase_plan.yml> \
  --evidence-dir <evidence_dir> \
  --out <acceptance_dir>
./agentlab.sh project-snapshot --project <Project>
```

### Skills

```bash
./agentlab.sh skill-status --project <Project>
./agentlab.sh skill-distill --project <Project> --task-id <task_id>
./agentlab.sh skill-match --project <Project> --task-id <task_id>
./agentlab.sh skill-usage --project <Project> --task-id <task_id>
```

Approval is required before promotion. External import adds network and trust gates.

### Acceptance and CI-equivalent checks

```bash
./agentlab.sh protocol-doctor
./agentlab.sh agent-role-chain-audit
./agentlab.sh capability-acceptance \
  --out acceptance_runs/agentlab_capability_acceptance/current.yml
./agentlab.sh eval-generalization \
  --out acceptance_runs/s10_generalization_eval
./agentlab.sh ci-gates
```

### Local UI and operations

```bash
./agentlab.sh tui
./agentlab.sh webui
./agentlab.sh ops-console-status \
  --project <Project> \
  --out acceptance_runs/s11_dashboard
./agentlab.sh timeline --project <Project>
```

### Internal sync and backup status

```bash
./agentlab.sh migration-doctor --project <Project> --no-write-probe
./agentlab.sh truenas-status --project <Project> --no-write-probe
./agentlab.sh truenas-sync \
  --project <Project> \
  --task-id <task_id> \
  --dry-run
./agentlab.sh backup-status --project <Project>
```

## 15. Current limits and unsupported paths

1. The overall checked-in capability status is `candidate`, not a production-wide pass.
2. Subscription limits, remaining capacity, and reset timestamps are unknown until safely observed in a run-local ledger.
3. An auth check or smoke does not prove a full task can complete.
4. Agy is read-only Observer/Reviewer infrastructure. It is not a Writer, Coder, renderer, or ArtifactProducer.
5. Agy's Claude fallback cannot accept video or audio; modality-dropping fallback is forbidden.
6. ArtifactTask audio has a schema but no current executable provider route.
7. Cross-provider mixed ArtifactTask output has no composite adapter and fails closed.
8. Full-API execution with assigned local input files is unsupported by the current isolation contract.
9. Grok media success requires a real asset. Text-only output is failure evidence, not media.
10. Media and generic non-code outputs are candidates until independent acceptance and explicit promotion.
11. Production-pack synthesis is implemented, but a synthesized pack cannot execute or enter the catalog without approval.
12. The current strict four-role synthesis live closure is incomplete.
13. Hermes Supervisor execution requires the local loopback service and exact GPT-5.5/high route identity; drift fails closed.
14. Configured Bailian and Ark media paths do not imply current activation, auth, approval, or automatic use.
15. Public Web UI binding, platform posting, web crawling, skill installation, dependency installation, and MCP launch remain disabled by default.
16. S11 and S12 provide deterministic operator/service planning, not a complete hosted control plane or automated commercial service.
17. M3 revenue, CRM, channel, compliance, analytics, and SOP loops remain roadmap work.
18. The 253-command count covers top-level commands only; nested families evolve independently.
19. Historical acceptance artifacts may describe retired bindings. Current config authority always wins.
20. Private creative assets, credentials, runtime state, and internal topology are not GitHub deliverables.

## 16. Authoritative source index

### Product, architecture, and lifecycle

- `README.md` — public positioning and quick start.
- `OPERATING_MODEL.md` — hybrid agent/executor model and acceptance notes.
- `agent_runtime/lifecycle_graph.py` — canonical 24-node graph and required outputs.
- `agent_runtime/pipeline_runner.py` — node execution, progress, and pipeline closure.
- `config/production_packs.yml` — seven packs, memory contracts, lifecycle nodes, and gates.
- `agent_runtime/production_pack_registry.py` — pack validation and promotion boundary.
- `agent_runtime/production_packs.py` — selection and synthesis-candidate shell.

### Mission, routing, and roles

- `config/routing_rules.yml` — size classification, route chains, hints, and skip rules.
- `config/domain_route_packs.yml` — narrative, research, media, and other domain mappings.
- `agent_runtime/task_router.py` — runtime route selection.
- `agent_runtime/workflow_plan.py` — route- and pack-aware plan construction.
- `config/agent_registry.yml` — role duties, inputs, outputs, and source/shell policies.
- `config/agent_role_bindings.yml` — allowed workers and frontdesk/worker separation.
- `config/agent_role_requirements.yml` — capability requirements by role.

### Models, workers, capacity, and cost

- `config/agent_model_profiles.yml` — execution modes and generated Full CLI compatibility view.
- `config/runtime_registry.yml` — Full CLI route/provider/model/pool authority.
- `config/routing_policy.yml` — quality floors, role demand, quota, and cost weights.
- `config/model_catalog.yml` — model identities and capability facts.
- `config/model_providers.yml` — provider facts.
- `config/worker_invocation_contracts.yml` — exact command templates and receipt requirements.
- `config/cli_workflow_shells.yml` — native CLI shell capability governance.
- `config/model_capacity.yml` — legacy-mode capacity configuration and dynamic-ledger compatibility.
- `agent_runtime/runtime_registry.py` — normalized identity, quota snapshots, and compatibility compilation.
- `agent_runtime/routing/dynamic_selector.py` — hard gates, quality floors, and effective-cost selection.
- `agent_runtime/model_capacity.py` — run-local pool/model state ledger and legacy traversal.
- `config/model_pricing.yml` — sole numeric pricing authority.
- `config/pricing_catalog.yml` — numeric-free runtime pricing and FX projection.
- `agent_runtime/costing/` and `agent_runtime/costs/` — budgets, ledgers, alerts, attribution, and efficiency.
- `agent_runtime/execution_economy/` — activation, reuse, cache, coalescing, and marginal-utility policy.

### Artifact and multimodal governance

- `config/artifact_task_policy.yml` — artifact types, formats, providers, and failure contract.
- `agent_runtime/protocols/artifact_task.py` — ArtifactTask validation and packet construction.
- `agent_runtime/cli_executor.py` — isolation, exact argv, materialization, receipts, and postflight.
- `config/media_generation_backends.yml` — backend policies and activation state.
- `config/media_artifact_policy.yml` — candidate-first media policy.
- `config/visual_acceptance.yml` — observer/reviewer/verifier evidence and promotion gate.
- `agent_runtime/visual_acceptance.py` — deterministic acceptance validation.
- `agent_runtime/media_backend_adapter.py` — media backend contract and execution seam.
- `agent_runtime/observation_contract.py` — assigned-input observation packets.
- `agent_runtime/narrative_delivery.py` — chapter candidate packets, ledgers, and delivery receipts.
- `agent_runtime/narrative_eval.py` — L0–L3 narrative acceptance harness.
- `agent_runtime/narrative_heavy_audit.py` — bounded Reviewer/Scribe/Verifier audit materialization.

### Protocol, memory, context, and recovery

- `config/protocol_enforcement.yml` — strong gates and doctor severities.
- `docs/WORKSPACE_ENTRY_PROTOCOL.md` — repository entry rules.
- `docs/FRONTDESK_PROTOCOL.md` — user-facing assistant boundary.
- `docs/ROLE_SESSION_PROTOCOL.md` — governed worker-role sessions.
- `docs/ARTIFACT_PRODUCER_PROTOCOL.md` — ArtifactProducer contract.
- `config/repository_handoff_policy.yml` — safe scan, copies, triggers, and required sections.
- `config/memory_policy.yml` — authoritative task and project records.
- `config/context_governance.yml` — context tiers and modality strategies.
- `agent_runtime/context_governance/` — profile, budget, pack, compression, and packers.
- `agent_runtime/program_manager/` — roadmap, phase, acceptance, replan, and snapshot memory.
- `agent_runtime/recovery/` — failure capture, diagnosis, retry, human review, replanning, and closure.

### Skills, capabilities, integrations, and UI

- `agent_runtime/skills/`, `agent_runtime/skill_*` — lifecycle, vault, distillation, injection, and learning.
- `agent_runtime/capabilities/` — mock-first S9 fabric and permission gates.
- `agent_runtime/capability_broker/` — providers, passports, trust, skill/MCP discovery, routing.
- `agent_runtime/external_agents/` and `agent_runtime/external_projects/` — bounded handoff and registry contracts.
- `agent_runtime/executors/` — S8 connector packets, result ingestion, and review.
- `agent_runtime/control_panel/` — read-only and policy-gated control state.
- `web_ui/` — static status board and local server.
- `agent_runtime/ops_console/` — S11 read-only snapshot and local dashboard seam.
- `agent_runtime/service_factory/` — S12 service planning.

### Acceptance and tests

- `docs/AGENTLAB_CAPABILITY_ACCEPTANCE_MATRIX.md` — human-readable verdict matrix.
- `acceptance_runs/agentlab_capability_acceptance/current.yml` — checked-in 27-pass/5-candidate snapshot.
- `acceptance_runs/agentlab_capability_acceptance/production_chain_audit.yml` — representative chain audit.
- `acceptance_runs/agentlab_capability_acceptance/agent_role_chain_audit.yml` — role/binding consistency.
- `tests/` — unit, integration, regression, protocol, capacity, artifact, and acceptance coverage.
- `config/ci_gate_policy.yml` — local CI-gate commands.
- `agent_runtime/evaluation/` — offline generalization evaluation.

### CLI entrypoints

- `agentlab.sh` — repository command entrypoint.
- `agent_runtime/run_task.py` — Typer command application and top-level command registration.
- `agent_runtime/cli/` — modular command families.
- `config/cli_entrypoint_policy.yml` — project-local wrapper installation policy.
