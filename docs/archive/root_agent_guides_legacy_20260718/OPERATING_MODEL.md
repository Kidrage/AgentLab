# AgentLab Operating Model

## Hybrid Agent-Executor Operating Model

Earlier AgentLab assumed that most runtime roles would be handled by direct model API providers. This is no longer the preferred default.

AgentLab should support a hybrid operating model where each role can be backed by either:

1. a direct model API provider,
2. a local or remote agent harness,
3. a CLI / IDE coding agent,
4. a human-approved manual executor,
5. a mock / dry-run executor for tests and safety.

The key design shift is:

```text
Model Provider ≠ Executor
Agent Harness ≠ Project Owner
AgentLab = Project OS / Truth Source / Governance Layer
```

AgentLab may delegate reasoning, coding, review, research, or artifact production to specialized agents such as Hermes, Claude Code, Codex, Cline, OpenClaw, or a direct model API. However, AgentLab must always retain control of:

* mission contracts,
* workflow plans,
* project brain,
* task packets,
* phase acceptance,
* evidence ledger,
* cost/resource ledger,
* approval gates,
* recovery and replanning,
* asset registration,
* final delivery state.

## Core Positioning

AgentLab is still primarily a strong code factory. Its default strength is
long-running software project governance: repository context, scoped
implementation, validation evidence, review, archive, memory, and recovery.

The code factory is not the correct shell for every task. Non-code generative
work should reuse AgentLab's state governance and lifecycle machinery without
inheriting code-only assumptions such as repository scouting, implementation
reports, patch diffs, or production artifact promotion.

The current operating model is therefore:

```text
mission_contract
-> route_decision
-> production_pack
-> lifecycle_nodes
-> agent required inputs/outputs
-> validation_gates
-> artifact_contract
-> memory/promotion policy
```

`production_pack` is the layer that separates the strong code core from other
task domains. It decides which lifecycle nodes are active, which artifacts are
required, which memory records matter, and which quality gates define success.

Use `./agentlab.sh route-probe <task text>` to inspect this task-domain route
without writing task evidence or launching agents. The probe follows the same
mission-contract and production-pack order as `prepare`, then reports the
selected `route_key`, agents, production pack, and route source. Do not confuse
it with `route-task`, which routes a task packet's AgentLab roles to concrete
worker identities and persists worker-assignment evidence.

## Production Pack Policy

Configured production packs live in `config/production_packs.yml`.

Current packs:

| Pack | Purpose | Default chain |
|---|---|---|
| `code_factory` | Codebase build, repair, refactor, testing, architecture work | Supervisor -> RepoScout/Researcher/InterfaceMapper as needed -> Coder -> TesterAuditor -> Verifier -> Archivist |
| `narrative_longform` | Longform fiction chapter/batch drafting and narrative audit with structured continuity memory | Supervisor -> Writer for light chapters or bounded chapter batches; Supervisor -> Reviewer/Scribe/Verifier for heavy audit |
| `article_light_draft` route / `article_light` pack | Short prose/article/report drafting without long-project governance | Supervisor -> ArtifactProducer -> Self-check |
| `media_series_production` | Multi-episode image/video work with persistent character, scene, shot, and asset continuity | Generation: Supervisor -> ArtifactProducer -> TesterAuditor; promotion gate: Observer + Reviewer + Verifier -> human/Supervisor |
| `media_generation` | Single image/video generation or editing with ledger and QC | Generation: Supervisor -> ArtifactProducer -> TesterAuditor; promotion gate: Observer + Reviewer + Verifier -> human/Supervisor |
| `generic_artifact` | Non-code artifact fallback when no richer configured domain pack applies | Supervisor -> ArtifactProducer -> TesterAuditor -> Verifier -> Self-check |

Promotion is not automatic for non-code candidate outputs. Media and generic
artifact packs deliver candidate artifacts and receipts first. Promotion into a
project's durable production memory or asset tree is a later acceptance step.

If a non-code domain has no configured pack, AgentLab must enter production-pack
synthesis mode instead of forcing the task into `code_factory`. The synthesis
candidate must produce:

```text
production_pack_proposal.yml
domain_memory_contract.yml
lifecycle_profile.yml
```

That candidate is proposal-only until a user or Supervisor accepts it and turns
it into a configured pack.

This does not mean every non-code request needs a hand-built one-off pipeline.
The intended rule is:

```text
known domain -> reuse configured production_pack
nearby domain -> specialize an existing pack with a small contract/profile
unknown complex domain -> synthesize a production-pack candidate
simple one-shot artifact -> generic_artifact
```

For example, "turn this script into a visually consistent episodic video
series" should reuse `media_series_production`: source script, show bible,
character visual bible, scene/asset registry, shot ledger, prompt pack,
generation ledger, continuity QC, and acceptance-before-promotion. It should
not fall back to the code factory and should not require a new bespoke pipeline
unless the domain needs genuinely new memory or lifecycle rules.

## Role Responsibilities

AgentLab roles are not the same thing as worker identities. Worker bindings are
configured separately in `config/agent_role_bindings.yml`.

| Role | Responsibility | Does not do |
|---|---|---|
| Supervisor | Mission contract, route, scope, budget, production-pack selection, approval gates | Edit source or silently execute |
| Observer | Independent multimodal inspection and evidence capture for candidate artifacts | Produce the artifact it accepts or infer unseen quality |
| RepoScout | Read repository structure and code context for code tasks | Mutate files |
| InterfaceMapper | Trace interfaces, contracts, and cross-layer boundaries | Implement patches |
| Researcher | Gather external evidence through the governed research contract | Become a fact source without citation/evidence |
| Coder | Source edits under approved scope for code tasks | Produce non-code media/text artifacts by default |
| ArtifactProducer | Produce candidate non-code artifacts through an artifact-type-dispatched ArtifactTask or production-pack contract | Replace Coder, accept its own output, or promote candidates |
| Writer | Produce governed longform prose and narrative ledgers | Promote facts directly into production memory |
| Reviewer | Narrative audit for continuity, character state, timeline, POV, and style drift | Rewrite prose by default |
| Scribe | Narrative ledger and state-transition proposal writing | Treat unapproved facts as current production facts |
| TesterAuditor | Validation evidence and risk/audit findings | Accept claims without command or artifact evidence |
| Verifier | Final output-contract and handoff completeness check | Patch implementation |
| Archivist | Durable memory/archive updates after acceptance | Archive or promote candidate outputs when the pack excludes archive |

### Current role and capacity baseline

The canonical current bindings come from `config/agent_model_profiles.yml` and
`config/model_capacity.yml`:

| Role | Current executor | Contract and boundary |
|---|---|---|
| Supervisor | Hermes + OpenAI Codex OAuth, GPT-5.6 Sol with `xhigh` reasoning | `hermes_supervisor`; an approved Claude Code + DeepSeek V4 Pro fallback is capacity-gated |
| Observer | Agy + Gemini 3.5 Flash High | `agy_observer`; independent multimodal observation |
| Observer capacity fallback | The same Agy shell + Claude Sonnet 4.6 | Allowed only for governed Gemini `quota_exhausted`, `rate_limited`, or `model_unavailable` outcomes; text, image, and PDF only |
| Writer | Claude Code + DeepSeek V4 Pro | `claude_writer`; exact runtime preflight pins model, effort, budget, plan mode, JSON, and empty tools; DeepSeek V4 Flash requires the declared lower-cost fallback policy |
| Researcher | Grok 4.3 through Hermes + xAI OAuth | `grok_research`; cited research evidence only |
| ArtifactProducer | Dynamic ArtifactTask dispatch: Qwen CLI for text, spreadsheet, and presentation; Grok 4.3 through Hermes + xAI OAuth for image and video | `config/artifact_task_policy.yml` is authoritative; audio and cross-provider mixed artifacts are currently unsupported, and every returned asset remains a non-self-accepted candidate |

`claude_writer_ultracode` is a separate developmental route, not a stronger
default Writer mode. It runs only from a sealed Writer packet containing
`ultracode_opt_in: true`, `writer_mode: developmental_ultracode`, and an
allowlisted `work_type`; runtime writes `ultracode_activation_receipt.yml` and
always forbids `final_prose_draft`.

The task-local operator entrypoint is:

```bash
./agentlab.sh run-agent Writer --project <project> --task-id <task> \
  --writer-ultracode --writer-work-type revision_plan --execute
```

Without both Ultracode flags, the resolver keeps the ordinary pure Writer
contract. The dedicated `WriterUltracode` capacity route has no automatic
fallback to ordinary drafting.

`ArtifactProducer` is not executable as an untyped generic assignment. The
user-facing `assign-role` command requires `--artifact-type`, derives the
required capabilities and provider from `artifact_task_policy.yml`, and blocks
when that exact provider is unavailable. In `AGENTLAB_FULL_CLI_MATRIX.csv`, the
legacy profile columns show the base full-cli media profile while the
`artifact_dispatch` column shows the effective per-type worker, invocation
contract, and capacity route.

The two Agy Observer routes use independent Gemini and Claude subscription
pools. Their five-hour and weekly window durations are user-declared, but
limits, remaining capacity, and reset timestamps are unknown until a safe
run-local observation supplies them. OpenAI Codex and xAI subscription limits,
remaining capacity, and reset timestamps are also unknown.

Authentication or a successful smoke is reachability evidence, not capacity
evidence. Safe discovery is limited to `agy models` and provider-scoped
`hermes auth status <provider>`; broad Hermes status output is forbidden.
Media execution uses the same seam: a pending Grok contract may run only the
exact `hermes auth status xai-oauth` probe, must bind the selected capacity
route to `hermes_grok_oauth`, and writes `media_capacity_route_receipt.yml`
before any adapter execution. Hand-written backends, audio, and composite
image-plus-video requests fail closed; no provider is silently substituted.

Visual output follows a separate acceptance boundary:

```text
Image/video ArtifactProducer/grok_media -> run-local candidate
-> independent Observer inspects the actual asset
-> a distinct Reviewer records aesthetic, continuity, technical,
   and factual-safety evidence
-> a distinct Verifier checks asset integrity, evidence-chain completeness,
   reviewer independence, and the promotion boundary
-> human or Supervisor explicitly promotes
```

The producer cannot accept its own output. Observer, Reviewer, and Verifier
must be independent role sessions; the Verifier does not pretend to perceive
the media or repeat the Reviewer's aesthetic judgment. Missing, `pending`, or
`unknown` evidence blocks promotion.

## Current Acceptance Evidence

Current deterministic evidence should be read as orchestration evidence, not as
a blanket promise of live model output quality.

For the compact capability-by-capability verdict, use
`docs/AGENTLAB_CAPABILITY_ACCEPTANCE_MATRIX.md`. This section keeps the fuller
evidence notes and historical context.

For the Chinese operator-facing summary of AgentLab positioning, agent roles,
production chains, state governance reuse, and current blockers, use
`docs/AGENTLAB_OPERATING_LOGIC.zh-CN.md`.

Verified locally:

- Code path remains covered by `code_factory`; `CODER_IMPLEMENTATION` and code
  gates remain present for code tasks.
- `AgentLab` code-factory UI/app probe
  `projects/AgentLab/runs/task_probe_agentlab_code_ui_app_20260707_v3`
  completed the dry-run lifecycle with route
  `Supervisor -> RepoScout -> InterfaceMapper -> Coder -> TesterAuditor -> Verifier -> Archivist`,
  `production_pack: code_factory`, and artifact pass rate `1.0 (22/22)`.
  `CODER_IMPLEMENTATION`, `VALIDATION`, `AUDIT`, `VERIFY`, `ARCHIVE`,
  `SELF_CHECK`, and `FINALIZE` are all completed in `lifecycle.yml`. This
  proves the code-factory orchestration path still closes after the
  production-pack split; it is not a live model implementation claim.
- `AgentLab` live code-factory Coder smoke
  `projects/AgentLab/runs/task_live_code_ui_app_smoke_20260707_v4`
  used the same `code_factory` route family and completed a real direct API
  Coder call with `qwen-coder` / `qwen3-coder-next`. The call recorded exact
  provider usage (`input_tokens: 5978`, `output_tokens: 4096`,
  `total_tokens: 10074`, estimated cost `$0.00321194`) and wrote
  `06_implementation_report.md` without an artifact-gate block. It is
  candidate-only evidence: `--no-apply-patches` was used, no production files
  were changed, and the report contains a proposed UI/app implementation plan
  plus representative candidate patch snippets.
- The live code-factory Coder probe exposed and fixed two direct-API harness
  defects. First, Coder context previously injected full `workflow_plan.yml`
  plus duplicate handoff/policy documents, producing a 37k-token prompt and a
  stale plan-only placeholder report; Coder now receives a compact execution
  summary, skips its own current output, skips placeholder upstream reports,
  and omits duplicate/generic handoff context. Second, direct API Coder reports
  are now required to say that only injected context was used and that commands
  run by the model call were `none`; the artifact gate accepts this honest
  direct-API candidate evidence while still blocking empty "no implementation
  work" placeholders.
- `AgentLab` live candidate-artifact materialization smoke
  `projects/AgentLab/runs/task_live_code_candidate_materialize_tiny2_20260707`
  proved that direct API Coder can now write run-local candidate artifacts
  without opening automatic production source edits. `prepare` selected
  `production_pack.status: synthesis_candidate` and `pack_id:
  pack_synthesis_candidate`; the live Coder call used `qwen-coder` /
  `qwen3-coder-next`, recorded exact usage (`input_tokens: 5904`,
  `output_tokens: 844`, `total_tokens: 6748`), and applied one scoped edit to
  `runs/task_live_code_candidate_materialize_tiny2_20260707/artifacts/web_ui/index.html`
  (`17` lines). This smoke also fixed three harness issues: candidate artifact
  roots are now accepted as directory-scoped write allowlists, Coder patch
  application is allowed only for run-local candidate artifact roots when the
  global code policy remains `patch_proposal_first`, and truncated/unclosed
  structured edit blocks block patch application instead of partially writing
  files. The applicator also accepts primary full-file blocks without `SEARCH`
  markers for new candidate files, still under the same allowed-root checks.
- `AgentLab` live compact Web UI/app materialization smoke
  `projects/AgentLab/runs/task_live_code_ui_app_materialize_compact_20260707`
  proved a fuller code-factory candidate path: `prepare` kept the request in
  `production_pack.pack_id: code_factory` while `artifact_intent` constrained
  writes to the run-local `artifacts/` tree. The live Coder call used
  `qwen-coder` / `qwen3-coder-next`, recorded exact usage (`input_tokens:
  6139`, `output_tokens: 2210`, `total_tokens: 8349`, estimated cost
  `$0.00215256`), and applied four scoped candidate files:
  `index.html` (`34` lines), `styles.css` (`14`), `app.js` (`36`), and
  `status.sample.json` (`13`). Static verification passed: JSON parsed with
  `python3 -m json.tool`, `node --check app.js` passed, and a local
  `python3 -m http.server` served `index.html`, `app.js`, and
  `status.sample.json` over HTTP 200. This proved multi-file candidate
  materialization and static serving, but exposed a quality gap: `app.js`
  used embedded static data rather than fetching `status.sample.json`.
- `AgentLab` live JSON-binding Web UI/app follow-up
  `projects/AgentLab/runs/task_live_code_ui_app_json_binding_20260707`
  closed that data-binding gap. The live Coder call used `qwen-coder` /
  `qwen3-coder-next`, recorded exact usage (`input_tokens: 6147`,
  `output_tokens: 1916`, `total_tokens: 8063`, estimated cost `$0.00198495`),
  and applied four scoped candidate files under `artifacts/web_ui/`.
  `app.js` contains `fetch('./status.sample.json')` plus a fallback object,
  `python3 -m json.tool status.sample.json` passed, `node --check app.js`
  passed, `curl` returned HTTP 200 for `index.html` and `app.js`, and a
  loopback Node fetch of `status.sample.json` returned `json_fetch_ok` after
  sandbox escalation for the local network call. This proves the candidate app
  can bind to its JSON sample data over HTTP; it still does not prove visual
  polish or production promotion readiness.
- Low-cost code-factory preparation now preserves explicit budget intent.
  `projects/AgentLab/runs/task_prepare_frugal_real_smoke_20260707` was prepared
  with `./agentlab.sh prepare --budget frugal --write-plan --overwrite-plan`;
  the written plan records `budget_mode: frugal`, `budget_profile: frugal_L2`,
  `risk_level: R2`, and `production_pack.pack_id: code_factory`. The prepare
  command now prints a compact workflow summary instead of dumping the complete
  plan with full agent registry and policy payloads to stdout.
- Crown chapter requests route to `narrative_light_chapter` and
  `narrative_longform`, excluding the code shell.
- Live provider smoke tests passed for configured text/code providers:
  `deepseek` (`deepseek-v4-pro`), `qwen-flash` (`qwen3.6-flash`), and
  `qwen-coder` (`qwen3-coder-next`) all returned `OK` through
  `./agentlab.sh provider-test --no-dry-run`. The shell environment variables
  remain absent; AgentLab resolves these keys from its own private config.
- Crown chapter-range requests such as "第1章到第20章" route to
  `narrative_batch_chapters`, with Writer-owned candidate outputs:
  `chapter_batch_plan.yml`, `chapters/`, `batch_continuity_ledger.yml`,
  `state_transition_proposal.yml`, and `narrative_batch_delivery_receipt.yml`.
- Crown audit requests route to `narrative_heavy_audit`.
- Article requests route to `article_light_draft` and use the `article_light`
  production pack.
- Crown media-series requests route to `media_series_production`, exclude
  `CODER_IMPLEMENTATION`, and default-skip `ARCHIVE`.
- `init-task` is now route-aware when a concrete request is provided. It uses
  the mission contract route decision first, then the route catalog fallback, to
  create only the initial placeholder files that belong to the likely route.
  Media/article tasks start with `artifact_producer_report.md` rather than
  `05_coder_prompt.md` / `06_implementation_report.md`; narrative chapter
  tasks start with `fiction_draft.md`; code tasks that include `Coder` retain
  the full legacy implementation shell. Blank requests still use the legacy
  shell because no route can be inferred safely.
- `prepare` / `workflow_plan` is now production-pack lifecycle aware. Configured
  non-code packs filter inactive agents from the route when their lifecycle node
  is absent; for example `media_series_production` excludes `ARCHIVE`, so
  `Archivist` is no longer listed for media-series tasks. Non-code
  production-pack routes also override inherited agent contracts: media,
  article, generic artifact, and pack-synthesis plans no longer give
  `Verifier` or `Archivist` code-shell inputs such as
  `implementation_report.md`, `interface_map.md`, `05_coder_prompt.md`, or
  `agent_docs/01_REPO_MAP.md`. Code-factory routes still retain these code
  contracts.
- `artifact_intent` is now production-pack aware. A project-level manuscript
  production directory no longer leaks into non-manuscript tasks. For
  `Crown_of_Ash`, `narrative_longform` still resolves production artifacts to
  `projects/Crown_of_Ash/production/manuscript`; `media_series_production`
  resolves to `projects/Crown_of_Ash/artifacts/media`; `article_light` resolves
  to `projects/Crown_of_Ash/artifacts`. Candidate outputs still write under
  `runs/<task_id>/artifacts/` first, and promotion remains explicit.
- Media generation contracts now distinguish backend auth from backend
  execution adapters. The configured `grok` worker identity runs through the
  Hermes executable with xAI OAuth. `grok_research` is the Researcher contract;
  `grok_media` is the ArtifactProducer contract. The default route requires no
  `XAI_API_KEY` or `GROK_API_KEY`. `grok_direct` remains an explicitly approved,
  API-key-authenticated fallback adapter. Preflight reports only secret
  references, not secret values.
- Unknown non-code domains enter executable production-pack synthesis candidate
  mode with `ArtifactProducer` and `Verifier`.
- `AgentLab` unknown-domain production-pack synthesis probe
  `projects/AgentLab/runs/task_probe_unknown_pack_synthesis_20260707`
  completed the dry-run lifecycle with `production_pack.status:
  synthesis_candidate`, `pack_id: pack_synthesis_candidate`, and artifact pass
  rate `1.0 (17/17)`. It produced `production_pack_proposal.yml`,
  `domain_memory_contract.yml`, and `lifecycle_profile.yml`; `CODER_IMPLEMENTATION`
  is skipped by the pack, so the task does not fall back to the code shell.
- Production-pack synthesis now has a deterministic validation/promotion
  closure. `pack-candidate-validate` rejects empty fake-provider synthesis
  shells such as
  `projects/AgentLab/runs/task_probe_unknown_pack_synthesis_20260707/production_pack_proposal.yml`
  because they do not contain a real `pack` mapping. It also rejects older
  proposal-only promotion smokes such as
  `projects/AgentLab/runs/task_pack_candidate_promote_smoke_20260707/production_pack_proposal.yml`
  because a candidate pack must now carry the full synthesis triplet:
  `production_pack_proposal.yml`, `domain_memory_contract.yml`, and
  `lifecycle_profile.yml`. The current synthesis smoke under
  `projects/AgentLab/runs/task_production_pack_synthesis_smoke_20260707/`
  validates as `synth_multimodal_asset_generation`. The validator checks pack
  id safety, duplicate ids, lifecycle node names, core lifecycle nodes,
  selector specificity, required outputs, memory contract, lifecycle companion,
  domain-memory companion, quality gates, and unsafe output paths.
- Deterministic synthesis and returned role execution are separate acceptance
  classes. `production_pack_synthesis_smoke.yml` is explicitly a scaffold; it
  cannot prove that role workers researched and authored a new pack.
  `production_pack_role_session_audit.yml` requires the persisted deterministic
  mission, a returned Supervisor plan, an execute-mode Researcher contract, all
  three same-run ArtifactProducer YAML blocks, registry validation, a role-bound
  Verifier receipt, and passing outbound-context manifests for all four roles.
  The current scent-theater run retains real Researcher content/provenance as
  candidate evidence, but predates complete manifest/mission governance; strict
  acceptance therefore requires a fresh governed four-role return.
- Mission compilation and workflow preparation now form one persisted contract.
  `prepare --write-plan` and pipeline `PREPARE_PLAN` write
  `mission_contract.yml` plus capability/artifact/gate/risk companions from the
  same rule-based mission used to select route and production pack. The mission
  remains excluded from serialized `workflow_plan.yml` to avoid duplicate
  context weight.
- Production-pack synthesis role packets are now packet-only. CLI execution
  omits AgentLab/project/run paths, uses an isolated temporary cwd, and can read
  only the exact embedded role messages. Supervisor, Researcher,
  ArtifactProducer, and Verifier each hash the exact outbound payload, inventory
  minimal source files, scan for secret patterns, and require the dedicated
  `AGENTLAB_PRODUCTION_PACK_CONTEXT_APPROVED=1` authorization before any
  provider process or API call. These manifests contain hashes and metadata,
  never task contents or credential values.
- Full-cli synthesis no longer silently falls through to direct API when a
  configured role worker is unavailable. Explicit `full_api` remains possible,
  but is a separately planned provider surface with its own manifest/approval.
  `production-pack-role-session-request` creates a provider-free fresh-run
  handoff and an approval-gated script; it refuses existing target runs and ends
  with `production-pack-role-session-audit --require-pass`.
- Native CLI reports are no longer overwritten by AgentLab's stdout wrapper.
  If a CLI worker writes its declared report, AgentLab preserves that file and
  stores the process wrapper separately as `*_cli_result_capture.md`. Research
  brief cache reuse is bound to the source report hash and provider provenance.
- Pipeline resume now retries a failed or paused lifecycle checkpoint before
  later waiting nodes. CLI failures carry a semantic `failure_class`, and
  user-facing block reasons are compacted and secret/path-redacted while raw
  evidence remains in command logs.
- Skill retrieval now treats explicit negative phrasing such as "不是小说章节"
  as a non-match, preventing narrative Writer skills from being injected into
  unrelated production-pack synthesis tasks.
- `ArtifactProducer` dry-runs now materialize production-pack required outputs,
  so artifact validation checks real candidate files rather than route intent.
  A later audit found the first implementation was still too weak: YAML files
  with only metadata and `items: []` were counted as complete. The artifact
  contract now rejects production-pack required outputs that have no meaningful
  payload beyond metadata.
- The stricter production-pack payload gate intentionally invalidates older
  media-series dry-run evidence. Re-running `artifact-check` now fails
  `task_probe_crown_media_series_pack_20260707b`,
  `task_probe_crown_media_adapter_block_20260707`,
  `task_probe_crown_media_pipeline_backend_auto_20260707`, and
  `task_probe_crown_comic_video_poster_series_20260707` with pass rate
  `0.62 (15/24)` and nine empty-payload issues covering `episode_plan.yml`,
  `shot_list.yml`, `character_visual_bible.yml`, `asset_registry.yml`,
  `prompt_pack.yml`, `generation_ledger.yml`, `media_continuity_ledger.yml`,
  `media_qc_report.yml`, and `narrative_media_delivery_receipt.yml`. Those
  runs remain useful as regression fixtures, not acceptance evidence.
- `Crown_of_Ash` media-series scaffold dry-run
  `projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707`
  replaces the invalidated media dry-run evidence. `prepare` selects
  `route_key: media_generation_task`, agents
  `Supervisor -> ArtifactProducer -> TesterAuditor -> Verifier`,
  and `production_pack.pack_id: media_series_production`; `Coder` is not in
  the route. `run-pipeline --dry-run` completes with artifact pass rate
  `1.0 (24/24)` under the stricter gate. The candidate pack outputs now
  contain structured fields such as `episodes`, `shots`, `characters`,
  `assets`, `prompts`, `generations`, `continuity_checks`, QC `checks`, and a
  delivery receipt, rather than empty `items`.
- `Crown_of_Ash` media route-contract cleanup probe
  `projects/Crown_of_Ash/runs/task_init_shell_media_probe_20260707` confirms
  the deeper contract cleanup. `prepare` now reports agents
  `Supervisor -> ArtifactProducer -> TesterAuditor -> Verifier`; scanning all
  `included_agents.required_inputs` and `required_outputs` finds zero
  occurrences of `implementation_report`, `interface_map`, `05_coder_prompt`,
  or `01_REPO_MAP`. The same scan against the code probe
  `projects/AgentLab/runs/task_init_shell_code_probe_20260707` still finds the
  expected code-factory inputs for `Supervisor`, `InterfaceMapper`, `Coder`,
  `Verifier`, and `Archivist`. Running the media probe pipeline in dry-run mode
  completes with artifact pass rate `1.0 (24/24)`; `ARCHIVE` is skipped because
  the production pack excludes it, while `VERIFY` completes.
- `workflow_plan.memory_policy.records.task_state` is now production-pack
  aware instead of reusing the code-factory global task-state list for every
  route. Media, article, and narrative plans no longer list
  `reposcout_report.md`, `implementation_report.md`, `interface_map.md`, or
  repo-map records as authoritative task state. The same disk smoke confirms
  `media_series_production` records media outputs plus validation/audit/verify
  reports, `article_light` records `article_draft.md` and
  `article_structure_check.yml`, `narrative_longform` records chapter draft and
  continuity/state-transition receipts, and `code_factory` still keeps
  `reposcout_report.md` and `implementation_report.md`.
- Shared validation gates are also rewritten for non-code production packs.
  Media/generic/synthesis plans no longer describe preflight as requiring a
  repo map, and no longer describe authorization as a source-write policy. The
  same code probe still preserves the original code-factory validation gate
  language and implementation gate.
- Lifecycle repair now uses the same production-pack skip logic as fresh
  lifecycle creation. `_ensure_lifecycle_shape` no longer repairs older
  media-series lifecycles by adding `ARCHIVE` as waiting when the workflow plan
  has a `media_series_production` pack that excludes `ARCHIVE`, even if an old
  route still listed `Archivist`. The shared skip helper also covers
  `ARTIFACT_PRODUCTION`, `VALIDATION`, `AUDIT`, `VERIFY`, and code/narrative
  optional nodes consistently.
- `PREPARE_PLAN` no longer revives production-pack-excluded lifecycle nodes
  merely because an old route still lists the agent. During prepare, optional
  nodes are reopened only when both the route agent is present and the active
  production pack allows the lifecycle node. A dry-run smoke confirms
  `task_init_shell_media_probe_20260707` has `ARTIFACT_PRODUCTION: completed`,
  `CODER_IMPLEMENTATION: skipped` because the media pack excludes it, and
  `ARCHIVE: skipped` because the media pack excludes it. The code probe
  `task_init_shell_code_probe_20260707` still has `CODER_IMPLEMENTATION:
  completed`, `ARCHIVE: completed`, and `ARTIFACT_PRODUCTION: skipped` because
  the code route does not include `ArtifactProducer`.
- The real direct-API `ArtifactProducer` prompt path now uses the production
  pack contract instead of the legacy code/report shell. Its prompt no longer
  injects the full `workflow_plan.yml`, which carried global code policy terms
  such as repo map, interface map, and implementation report. It injects
  mission/artifact/media contracts when present, a compact plan summary, the
  production-pack required outputs, and explicit `AGENTLAB_EDIT` instructions
  for text/YAML/JSON/HTML/CSS/JS candidate artifacts. ArtifactProducer direct
  API execution can now apply those edit blocks to run-local candidate artifact
  roots under the same `artifact_intent.allowed_write_roots` allowlist used by
  candidate Coder artifacts; it still cannot edit repository source or
  production artifact paths unless the plan declares them.
- Production-pack candidate validation now rejects code-shell leakage for
  non-code packs before promotion. A synthesized media/article/unknown-domain
  pack cannot include `CODER_IMPLEMENTATION` or require outputs such as
  `implementation_report.md`, `06_implementation_report.md`, coder prompts,
  interface maps, or reposcout reports. Explicit code packs remain allowed when
  their selectors identify code work, such as `codebase_build_project`,
  `coding`, `code_patch`, or code route keys. CLI smoke confirmed
  `pack-candidate-validate` exits non-zero for a `media_generation_task`
  proposal containing `CODER_IMPLEMENTATION` and `implementation_report.md`.
- Production-pack synthesis now includes an explicit domain-research phase.
  Unknown complex non-code domains expand to
  `Supervisor -> Researcher -> ArtifactProducer -> Verifier`, with
  `RESEARCH_OPTIONAL` active in the synthesis candidate lifecycle. Researcher
  must produce `domain_research_brief.md`; ArtifactProducer and Verifier must
  read that brief before proposing or accepting `production_pack_proposal.yml`,
  `domain_memory_contract.yml`, and `lifecycle_profile.yml`. The Researcher
  direct-API prompt for synthesis avoids repo maps, implementation reports,
  interface maps, patches, and source-edit language; it asks for external
  capability/tool needs, durable memory/state requirements, lifecycle phases,
  quality gates, and blocker assumptions. This is the concrete "seek resources
  outward, package governance inward" closure for new non-code domains.
- Synthesis agent ordering is now deterministic and lifecycle-aligned. The
  production-pack candidate and expanded route both put `Researcher` before
  `ArtifactProducer`, so pack proposal cannot precede the domain brief merely
  because the legacy artifact route listed `ArtifactProducer` earlier.
- `artifact_intent` path separation was rechecked with live prepare smoke:
  `task_init_shell_media_probe_20260707` now reports
  `production_dir: projects/Crown_of_Ash/artifacts/media`;
  `task_init_shell_narrative_probe_20260707` still reports
  `production_dir: projects/Crown_of_Ash/production/manuscript`; and
  `task_init_shell_article_crown_probe_20260707` reports
  `production_dir: projects/Crown_of_Ash/artifacts`. This closes the bug where
  a Crown media or article task inherited the long-novel manuscript production
  path.
- An older media-series scaffold smoke selected `grok_direct` for `video` and
  safely blocked on missing xAI/Grok API-key auth. That is historical fallback
  evidence only. Current Researcher and image/video ArtifactProducer routing
  uses the configured Hermes executable with xAI OAuth through distinct
  `grok_research` and `grok_media` contracts. Text, spreadsheet, presentation,
  ArtifactProducer work uses Qwen CLI instead. Cross-provider mixed work blocks until a composite adapter exists. The direct xAI REST adapter still reports only
  secret references such as `XAI_API_KEY` / `GROK_API_KEY` when explicitly
  selected as fallback.
  API-key auth is fallback-only; the default OAuth route does not use API keys
  as the default unblock path.
- `Crown_of_Ash` chapter-batch dry-run
  `projects/Crown_of_Ash/runs/task_probe_crown_batch_ch01_ch20_20260707`
  completed with artifact pass rate `1.0 (17/17)`.
- `Crown_of_Ash` longform scale audit
  `acceptance_runs/narrative_eval/Crown_of_Ash/crown_scale_probe_20260707/crown_scale_1500_20260707`
  completed L0 fact-source health and L3 1500-chapter governance simulation.
  The acceptance status is `warn` because historical narrative runs are
  incomplete and L2 was intentionally skipped in `audit-only` mode. The L3
  report explicitly records `simulation_scope: governance_ledger_only` and
  `draft_chapters_generated: 0`; this is scale-governance evidence, not a claim
  that 1500 manuscript chapters were generated.
- `Crown_of_Ash` mock chapter-chain acceptance
  `acceptance_runs/narrative_eval/Crown_of_Ash/crown_mock_chain_receipt_contract_20260707/mock_chain_receipt_contract_ch01_ch03_20260707`
  completed L0 fact-source health, L2 mock chapters 1-3, and L3 1500-chapter
  governance simulation with `production_modified: false`. L2 now requires
  `chapter_packet.yml`, `fiction_draft.md`, `continuity_ledger.yml`,
  `state_transition_proposal.yml`, and `narrative_delivery_receipt.yml`; all
  three mock chapters pass and `continuity_failure_report.yml` records
  `blocking_failures: []`. The generated chapter packets for chapters 2 and 3
  read prior candidate-run drafts/ledgers rather than deprecated legacy rebuild
  paths. `narrative_delivery_receipt.yml` now records both
  `preflight_required_files` and `external_required_files`, making the receipt
  gate auditable without circularly requiring the receipt before it is written.
  This is deterministic governance-chain evidence, not prose-quality evidence.
- Historical `Crown_of_Ash` live Writer evidence produced a real Chapter 1
  candidate through
  the normal `run-agent Writer` path in
  `projects/Crown_of_Ash/runs/task_narrative_eval_ch01_live_ch01_20260707_cli_fallback`.
  The successful call used `deepseek-v4-flash`, recorded exact API usage
  (`input_tokens: 10939`, `output_tokens: 6855`, `total_tokens: 17794`), and
  produced `fiction_draft.md`. The candidate was then completed into the light
  narrative delivery contract with `continuity_ledger.yml`,
  `state_transition_proposal.yml`, and `narrative_delivery_receipt.yml`;
  `validate_narrative_delivery` reports `valid: true`. This proves live
  Writer generation and light-path delivery closure for one candidate run. It
  does not prove literary quality or promotion readiness.
- `narrative-eval live` exposed and partially fixed three harness defects:
  generated chapter run ids now use the safe `task_...` namespace; reset
  candidates now write `narrative_light_chapter` workflow plans instead of the
  legacy `fiction_chapter_pipeline`; and the live light path no longer calls
  Reviewer by default. Provider retry now uses `provider_guard.is_retryable`,
  and the harness can fall back to the formal `run-agent Writer` CLI path.
  Complete `narrative-eval live` is still blocked by intermittent DeepSeek
  long-context streaming `network_error` on some runs, with evidence in
  `projects/Crown_of_Ash/runs/task_narrative_eval_ch01_live_ch01_20260707_cli_fallback_retry2`.
- Related regression command passed:

```bash
python3 -m pytest -q tests/test_narrative_eval.py tests/test_artifact_gate.py
# 26 passed

python3 -m pytest -q tests/test_narrative_delivery.py tests/test_narrative_eval.py
# 17 passed

python3 -m pytest -q tests/test_media_backend_adapter.py tests/test_m1_mission_compiler_v2.py tests/test_artifact_gate.py
# 132 passed

python3 -m pytest -q tests/test_prepare_cli_budget.py tests/test_agent_runner_cli_integration.py tests/test_artifact_gate.py tests/test_execution_evidence_gate.py tests/test_narrative_eval.py tests/test_workflow_plan_routing.py tests/test_writer_pipeline_nodes.py tests/test_m1_mission_compiler_v2.py tests/test_media_backend_adapter.py tests/test_narrative_delivery.py tests/test_protocol_enforcement.py tests/test_artifact_task_protocol.py tests/test_pipeline_error_handling.py tests/test_run_next_node_semantics.py tests/test_project_artifact_steward.py tests/test_routing_gate_consistency.py tests/test_pipeline_execution_modes.py tests/test_skill_retrieval_injection.py
# 296 passed

python3 -m pytest -q tests/test_production_pack_registry.py tests/test_workflow_plan_routing.py tests/test_artifact_gate.py tests/test_html_archivist_blocks.py tests/test_agent_runner_cli_integration.py
# 80 passed

python3 -m pytest -q tests/test_media_backend_adapter.py tests/test_m1_mission_compiler_v2.py tests/test_artifact_gate.py tests/test_pipeline_execution_modes.py tests/test_workflow_plan_routing.py
# 156 passed

python3 -m pytest -q tests/test_artifact_task_protocol.py tests/test_workflow_plan_routing.py tests/test_routing_gate_consistency.py tests/test_artifact_gate.py tests/test_m1_mission_compiler_v2.py tests/test_pipeline_execution_modes.py
# 196 passed

python3 -m pytest -q tests/test_artifact_task_protocol.py tests/test_workflow_plan_routing.py tests/test_routing_gate_consistency.py tests/test_artifact_gate.py tests/test_m1_mission_compiler_v2.py tests/test_pipeline_execution_modes.py tests/test_media_backend_adapter.py
# 203 passed

python3 -m pytest -q tests/test_project_artifact_steward.py tests/test_workflow_plan_routing.py tests/test_artifact_task_protocol.py tests/test_routing_gate_consistency.py tests/test_artifact_gate.py tests/test_m1_mission_compiler_v2.py tests/test_pipeline_execution_modes.py tests/test_media_backend_adapter.py tests/test_agent_runner_cli_integration.py
# 251 passed

python3 -m pytest -q tests/test_workflow_plan_routing.py tests/test_project_artifact_steward.py tests/test_artifact_task_protocol.py tests/test_artifact_gate.py tests/test_production_pack_registry.py
# 65 passed

python3 -m pytest -q tests/test_workflow_plan_routing.py tests/test_project_artifact_steward.py tests/test_artifact_task_protocol.py tests/test_artifact_gate.py tests/test_production_pack_registry.py tests/test_writer_pipeline_nodes.py tests/test_pipeline_execution_modes.py tests/test_run_next_node_semantics.py
# 84 passed

python3 -m pytest -q tests/test_workflow_plan_routing.py tests/test_project_artifact_steward.py tests/test_artifact_task_protocol.py tests/test_artifact_gate.py tests/test_production_pack_registry.py tests/test_writer_pipeline_nodes.py tests/test_pipeline_execution_modes.py tests/test_run_next_node_semantics.py tests/test_routing_gate_consistency.py
# 120 passed

python3 -m pytest -q tests/test_agent_runner_cli_integration.py tests/test_workflow_plan_routing.py tests/test_artifact_task_protocol.py tests/test_artifact_gate.py tests/test_pipeline_execution_modes.py tests/test_writer_pipeline_nodes.py tests/test_routing_gate_consistency.py
# 134 passed

python3 -m pytest -q tests/test_production_pack_registry.py tests/test_workflow_plan_routing.py tests/test_artifact_task_protocol.py tests/test_artifact_gate.py tests/test_agent_runner_cli_integration.py tests/test_pipeline_execution_modes.py tests/test_writer_pipeline_nodes.py tests/test_routing_gate_consistency.py
# 141 passed

python3 -m pytest -q tests/test_workflow_plan_routing.py tests/test_agent_runner_cli_integration.py tests/test_writer_pipeline_nodes.py tests/test_production_pack_registry.py tests/test_artifact_gate.py tests/test_artifact_task_protocol.py tests/test_pipeline_execution_modes.py tests/test_routing_gate_consistency.py
# 143 passed
```

Still not proved:

- Live Grok/media generation quality, continuity, and cost behavior are not
  accepted. Current evidence proves route readiness, xAI OAuth reachability,
  separate `grok_research` / `grok_media` contracts, backend preflight,
  asset-return structure, and candidate boundaries. A real returned asset must
  still pass independent Observer inspection, distinct Reviewer and Verifier
  judgments, and an explicit human or Supervisor promotion decision.
- Current Claude Code + DeepSeek V4 Pro Writer quality is not proved by the
  historical Agy/Gemini or DeepSeek candidate runs. Those runs remain evidence
  for the governed narrative artifact contract, not for the current executor
  surface or broader literary quality.
- Provider capacity is not proved by authentication or reachability. Current
  limits, remaining capacity, and reset timestamps remain unknown unless a
  safe run-local probe records them.
- The frugal budget/prepare verbosity defect has been fixed for explicit
  budget selection. Broader budget policy still needs separate acceptance if
  the desired behavior changes for default high-risk tasks.

The canonical peer directory and invocation contracts are
`config/shared_agent_directory.yml` and `config/worker_invocation_contracts.yml`.
Every collaborator must identify its endpoint and peers before work begins; it
must never invent a command for another agent.

Every executor and gateway must also enforce
`config/repository_handoff_policy.yml`: discover repository memory before reading
project contents, create it when missing, and refresh the repository-local and
shared-memory HandOff copies after material changes and before final reporting.
The inventory covers all paths and metadata but never bulk-reads repository content.

When a user explicitly asks a front-desk agent to invoke a named agent, the
front desk becomes a relay and reporter only. It may package, dispatch, monitor,
inspect evidence, and report the named agent's result and actual file diff. It
must not implement the delegated task, silently substitute another agent, or
claim the delegate's changes as its own.

### Current high-capability local configuration

The current canonical high-capability role topology is:

```yaml
operating_mode: hybrid_agent_executor

roles:
  project_governor:
    owner: agentlab
    responsibilities:
      - mission_contract
      - workflow_plan
      - project_brain
      - phase_acceptance
      - recovery
      - evidence_review
      - cost_governance

  supervisor_executor:
    type: cli_agent
    shell: hermes
    provider: openai_codex_oauth
    model: gpt-5.6-sol
    reasoning_effort: xhigh
    invocation_contract: hermes_supervisor
    responsibilities:
      - high_level_reasoning
      - route_planning
      - task_decomposition
      - strategy_review
      - replanning_suggestions
    governance:
      bypass_agentlab_state: false
      requires_task_packet: true
      writes_result_report: true

  observer_executor:
    type: cli_agent
    shell: agy
    primary: gemini-3.5-flash-high
    invocation_contract: agy_observer
    capacity_fallback:
      shell: agy
      model: claude-sonnet-4.6
      only_on: [quota_exhausted, rate_limited, model_unavailable]
      modalities: [text, image, pdf]

  writer_executor:
    type: cli_agent
    shell: claude_code
    model: deepseek-v4-pro
    invocation_contract: claude_writer

  researcher_executor:
    type: cli_agent
    worker: grok
    executable: hermes
    provider: xai_oauth
    model: grok-4.3
    invocation_contract: grok_research

  artifact_executor:
    type: capability_routed_cli_agent
    non_media_worker: qwen
    non_media_invocation_contract: qwen_artifact
    media_worker: grok
    media_executable: hermes
    media_provider: xai_oauth
    media_model: grok-4.3
    media_invocation_contract: grok_media
    unsupported: [audio, cross_provider_mixed]
    output_state: candidate_only
    independent_visual_acceptance_required: true
    required_review_roles: [Observer, Reviewer, Verifier]

  code_executor:
    type: cli_coding_agent
    provider: claude_code
    responsibilities:
      - repo_inspection
      - code_patch
      - test_execution
      - bug_fixing
      - implementation_report
    governance:
      bypass_agentlab_state: false
      requires_scoped_task_packet: true
      requires_diff_summary: true
      requires_test_evidence: true

capacity_truth:
  limit: unknown
  remaining: unknown
  reset_at: unknown
  reachability_does_not_imply_capacity: true
```

### Why agent executors may outperform direct API execution

Direct model API execution is simple and cheap to integrate, but it lacks a full tool-use loop unless AgentLab implements that loop itself. Specialized agents often include repo navigation, tool calling, shell interaction, patch generation, context handling, and iterative repair behavior.

Therefore, for complex coding and long-running project work, AgentLab should prefer agent executors when:

* the task requires repository-scale inspection,
* code changes span multiple files,
* tests need to be run repeatedly,
* the executor must inspect logs or diffs,
* the task benefits from IDE/CLI-native context,
* the user has already configured a strong local agent harness.

Direct API providers remain useful for:

* cheap classification,
* summarization,
* mission contract drafting,
* artifact normalization,
* lightweight review,
* fallback execution,
* deterministic offline tests.

### Required safety boundary

No agent executor may directly mutate project state without AgentLab recording:

```text
task_packet
→ executor_assignment
→ result_report
→ changed_files
→ diff_summary
→ evidence_artifacts
→ test_results
→ phase_acceptance
→ project_brain_update
```

AgentLab must treat every external or local agent as an executor, not as the source of truth.

If Hermes or Claude Code makes a plan, AgentLab records it as a proposal.

If Claude Code changes code, AgentLab records it as a patch result.

If an agent claims success, AgentLab verifies evidence before accepting.

If evidence is missing, AgentLab must return retry / blocked / human_review rather than silently closing the phase.

### Recommended default policy

Use this priority order for high-value local project work:

```text
1. AgentLab compiles mission and workflow.
2. Hermes + GPT-5.6 Sol Supervisor proposes route and decomposition.
3. AgentLab converts the proposal into governed role packets.
4. The bound role executes: Agy Observer, Claude+DeepSeek Writer,
   Grok Researcher, artifact-type-dispatched Qwen/Grok ArtifactProducer,
   or the scoped code worker.
5. AgentLab ingests reports, diffs, tests, candidates, and capacity evidence.
6. Independent validation runs; visual producers cannot self-accept.
7. Human or Supervisor approval promotes accepted state and updates memory.
```

The goal is not to make AgentLab a weaker replacement for strong agents. The goal is to make AgentLab the operating system that coordinates them.

## Trigger Rule

AgentLab only runs when the user explicitly asks to use AgentLab.

If the user gives a normal coding request without saying to use AgentLab, the local coding agent handles it independently in the current session.

## Logging Rule

Each AgentLab project maintains:

```text
agent_docs/07_DEVELOPMENT_LOG.md
agent_docs/08_CODEX_DIALOGUE_LOG.md
agent_docs/09_COST_LEDGER.yml
```

The development log is organized by module. The dialogue log records the user-visible task conversation and coding agent actions. Hidden model reasoning is not available and must not be fabricated.

## Billing Rule

Token usage is recorded from API telemetry when available. Local coding agent or local harness usage is not exposed to AgentLab as a local billing API, so their execution is recorded as a manual usage event with exact cost marked `unavailable`.

## Brain Governance Rule

The project governor layer governs traversal and token pressure:

- Any full-directory or full-repository traversal must call `request-traversal`.
- The governor records decisions in `runs/task_xxxx/brain_decisions.yml`.
- If the decision is ambiguous, AgentLab writes `USER_DECISION_REQUIRED.md` and the driving agent asks the user for a yes/no answer in the main conversation.
- If token usage approaches the warning threshold, continuing is allowed with a warning.
- If token usage crosses the stop threshold, the governor asks the user.
- If an agent executor appears stuck in a repeated loop or drifts from the task goal, the governor stops and replans.

Commands:

```bash
./agentlab.sh brain-status --project ExampleProject --task-id task_0001
./agentlab.sh request-traversal RepoScout --project ExampleProject --task-id task_0001 --scope full_repo --full-repo --reason "Need initial repo map" --estimated-files 300 --estimated-tokens 9000
```

## Dual-End Collaboration and Sync Protocol

AgentLab operates across a dual-end execution link layout to enable remote running / deployment while maintaining synchronized agent capabilities:

1.  **Architecture**:
    *   **Local Workstation**: Primary development environment and source of truth.
    *   **Relay Hub** (`<RELAY_HOST>:<RELAY_SSH_PORT>`): Shared repository and exchange relay station.
    *   **Cloud Runtime** (`<CLOUD_RUNTIME_HOST>`): Run/deployment server. Connected to Relay Hub and directly accessible from local workstation via SSH.
2.  **Sync Workflow**:
    *   **Local Workstation -> Relay Hub**: Local pushes workspace changes (skills, configs, memory snapshots) to Relay Hub using `./agentlab.sh relay-sync --execute` or manual rsync.
    *   **Relay Hub -> Cloud Runtime**: Remote agents on Cloud Runtime pull workspace/skills/MCP updates from Relay Hub using `rsync` over SSH.
    *   **Cloud Runtime -> Relay Hub -> Local Workstation**: Task execution logs and agent memory produced on Cloud Runtime sync back to Relay Hub, then pull to local workstation, maintaining synchronized memory and skills.
