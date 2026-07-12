# AgentLab M-Series Mainline Handoff — RAG-Aware Revision

> Target path in repo: `docs/AGENTLAB_M_SERIES_MAINLINE_HANDOFF.md` or root `AGENTLAB_M_SERIES_MAINLINE_HANDOFF_CACHE_AWARE.md`
> Revision purpose: replace the older M1/M2/M3 planning handoff with a current-state-aware plan that adds AgentLab Self RAG, Project RAG, Knowledge Acquisition, and Reasoning Replay as a first-class mainline.
> Current remote audit date: 2026-07-02
> Current observed remote branch: `main`
> Current observed latest commit on GitHub commits page: `adb7e59` — `fix(m3): harden operator action closure`
> Current stable acceptance anchor: `19839d9` / v1 stable report, recording `2015 passed, 2 skipped, 11 warnings` and CI passed for run `28500440976` on `95d975d`.

---

## 0. Agent Entry Jump Map — Start Here, Do Not Re-Implement Closed Work

When an agent opens this file, it must **not** start from the top and re-add older M1/M2/M3 material. Start from this jump map.

### Current Patch Cursor

```text
CURRENT_UNREPAIRED_FIELD = M4 Knowledge Acquisition + Evidence RAG + Reasoning Replay
NEXT_STAGE_TO_IMPLEMENT = M4-0 / M4-1
DO_NOT_REOPEN = M0/M1/M2/M3 internal closed-loop baseline unless a regression is proven
DEFER = M5 Project-to-Revenue OS business/asset/revenue/commercial loop
```

### Jump Directly to Active Sections

1. [`M4-0 — Baseline Re-Audit Before RAG`](#m4-0--baseline-re-audit-before-rag)
   Confirm local repository state, CI, text integrity, v1 report, current commit, and existing modules before adding RAG.

2. [`M4-1 — RAG Kernel and Knowledge Lifecycle`](#m4-1--rag-kernel-and-knowledge-lifecycle)
   Build the shared RAG engine and knowledge lifecycle state machine.

3. [`M4-2 — AgentLab Self RAG`](#m4-2--agentlab-self-rag)
   Let AgentLab retrieve its own docs, config, tests, acceptance reports, modules, skills, and policies.

4. [`M4-3 — Project RAG Builder`](#m4-3--project-rag-builder)
   Let every long-running project automatically create isolated Project RAG from `project_brain`, artifacts, executor results, evidence, and decisions.

5. [`M4-4 — Knowledge Acquisition Layer`](#m4-4--knowledge-acquisition-layer)
   Add controlled external/local knowledge acquisition from web/docs/database/code/media providers into staged local knowledge.

6. [`M4-5 — Reasoning Event and Reasoning Replay`](#m4-5--reasoning-event-and-reasoning-replay)
   Record important reasoning events, detect knowledge gaps, acquire evidence, and revise prior reasoning.

7. [`M4-6 — Evidence-Grounded Context Packing`](#m4-6--evidence-grounded-context-packing)
   Feed executor/reviewer/assistant roles with bounded, cited context packs instead of raw history.

8. [`M4-7 — RAG Evaluation and Anti-Stale Guards`](#m4-7--rag-evaluation-and-anti-stale-guards)
   Prevent stale archive/candidate/cross-project contamination and no-citation factual claims.

9. [`M4 Final Acceptance`](#m4-final-acceptance)
   Prove Self RAG + Project RAG + Reasoning Replay works offline and does not bypass governance.

10. [`M5 — Project-to-Revenue OS`](#m5--project-to-revenue-os)
    Business/asset/production/revenue/CRM/SOP loops. This is **after** M4 RAG.

### Forbidden Redundant Work

Do not add duplicate versions of these already-covered capabilities unless tests prove a regression:

```text
- mission/task contract MVP
- project workflow planning MVP
- project brain / phase plan / phase acceptance MVP
- executor result ingestion / evidence ledger MVP
- operator state model
- TUI/WebUI operator action runtime
- cost facade and cost attribution baseline
- timeline and assistant grounding baseline
- content governance long-chain baseline
- text integrity / forbidden file guard baseline
```

### Required First Commit Message for This Handoff Update

```text
docs(m-series): rebase mainline on v1 baseline and add M4 evidence RAG plan
```

---

## 1. Current Remote State Audit

This section is a **state checkpoint**, not a replacement for local verification.

### 1.1 Observed Remote Facts

Observed from GitHub on 2026-07-02:

```text
Repository: https://github.com/Kidrage/AgentLab
Branch: main
Latest observed commit: adb7e59
Latest observed commit title: fix(m3): harden operator action closure
Prior v1 stable acceptance commit: 19839d9
Stable CI evidence in v1 report: CI passed on run 28500440976 for commit 95d975d
Full local pytest recorded in v1 report: 2015 passed, 2 skipped, 11 warnings
```

Recent commits show that the repo advanced beyond the older M-series handoff:

```text
adb7e59  fix(m3): harden operator action closure
19839d9  docs(v1): record stable CI acceptance
95d975d  fix(ci): align text integrity audit with v1 hygiene
a3523bc  feat(v1): harden internal closed loop baseline
29a28cd  feat(m3): complete M3 Stage C+D — Observability Timeline, Content Surface, Assistant Modes
45dd06a  feat(m3): complete M3 Stage A+B — Operator State Model, WebUI contracts, TUI wiring, Config Center, Cost System v2
```

### 1.2 Practical Interpretation

The old document treated M1/M2/M3 as mostly future work. That is no longer accurate.

Current interpretation:

```text
M0/M1/M2 internal governance and operator foundation: treated as accepted baseline unless regression appears.
M3 internal operator closed-loop hardening: treated as accepted/stabilized baseline through v1 stable evidence.
Original M3 Project-to-Revenue material: moved to M5, because v1 stable explicitly keeps commercial/productization outside the accepted internal closed loop.
New required mainline before commercial expansion: M4 Knowledge Acquisition + Evidence RAG + Reasoning Replay.
```

### 1.3 Required Local Confirmation Before Any New Patch

Every executor must run these before modifying code:

```bash
git status --short
git branch --show-current
git log --oneline -10
python -m compileall agent_runtime agentlab_app.py
python -m pytest -q
./agentlab.sh --help
./agentlab.sh run-pipeline --help
python scripts/audit_text_integrity.py
```

If available:

```bash
python scripts/check_remote_raw_integrity.py --ref HEAD
```

If local results differ from the remote audit summary, update:

```text
acceptance_runs/m4_rag_baseline/M4_RAG_BASELINE_REAUDIT_REPORT.md
```

---

## 2. Revised M-Series Dependency Graph

The previous graph was:

```text
M0 → M1 Project Governance Kernel → M2 Operator OS → M3 Project-to-Revenue OS
```

The revised graph is:

```text
M0 Baseline / Text Integrity / Scope Freeze
  Status: accepted unless regression
↓
M1 Project Governance Kernel
  Status: accepted internal baseline unless regression
↓
M2 Operator OS / Local Agent Company Control Plane
  Status: accepted internal baseline unless regression
↓
M3 Internal Closed Loop / Operator Action Closure
  Status: accepted/stabilized through v1 stable evidence, but local re-audit required
↓
M4 Knowledge Acquisition + Evidence RAG + Reasoning Replay
  Status: ACTIVE NEXT MAINLINE
↓
M5 Project-to-Revenue OS
  Status: future reserved after M4 RAG foundation
```

### Why Insert M4 Before P2R?

Project-to-Revenue needs reliable project memory, source grounding, market/source ingestion, reasoning revision, and asset/evidence retrieval. Without M4, M5 will recreate the old problem:

```text
agent makes a weak inference
→ lacks sources
→ asks another model
→ produces more prose
→ no durable knowledge
→ no local evidence
→ no stable memory
→ repeats the same mistakes
```

M4 changes the loop to:

```text
reasoning event
→ knowledge gap detection
→ retrieval/acquisition plan
→ safe local/external source ingestion
→ staged knowledge
→ evidence RAG
→ context pack
→ reasoning replay
→ verifier check
→ promoted memory / project knowledge / skill candidate
```

---

## 3. Global Design Rule for RAG in AgentLab

### 3.1 RAG Is Not a Side Branch

For AgentLab, RAG must not be a plugin that sits beside the system.

Bad design:

```text
Agent gets confused
→ calls random vector search
→ dumps chunks into prompt
→ continues hallucinating
```

Correct design:

```text
RAG engine = independent runtime package
Knowledge policy = globally governed lifecycle
Retrieval calls = embedded into brain/recovery/verifier/executor/assistant/project brain
Evidence ledger = canonical trace layer
Project Brain = memory promotion target
Skill/SOP factory = reusable knowledge promotion target
```

In short:

```text
Code structure: separate package.
System behavior: internal circulation system.
Governance: never bypass cost/risk/approval/evidence gates.
```

### 3.2 Required RAG Principles

```text
1. Search is not memory.
2. Retrieved is not trusted.
3. Staged is not canonical.
4. Similar is not necessarily relevant.
5. Recent is not necessarily official.
6. No citation means no factual claim.
7. Project isolation by default.
8. Knowledge must have lifecycle.
9. Archive/candidate/draft content cannot be used as current fact unless explicitly allowed.
10. RAG never discounts permission, privacy, source, or platform risk.
```

---

## 4. M0-M3 Status Map

This is a compact map so future agents do not duplicate finished work.

| Stage | Current Status | Do Next |
|---|---|---|
| M0 Baseline / hygiene | Treated as closed baseline, guarded by text integrity and v1 report | Only re-audit before M4 |
| M1 Project Governance Kernel | Internal project governance exists: mission/workflow/project brain/executor/phase acceptance/recovery/context compression patterns | Do not rewrite; integrate RAG into project brain and task packets |
| M2 Operator OS | Worker/operator/cost/config/TUI/WebUI/assistant/control-plane foundation exists | Do not rewrite; expose RAG status and actions through existing operator surfaces |
| M3 Internal Closed Loop | Operator state, action runtime, timeline, assistant grounding, content surface, cost facade, acceptance history hardened | Do not redefine as P2R; extend with RAG evidence and reasoning replay events |
| M4 Knowledge/RAG | Missing | Implement next |
| M5 P2R | Future reserved | Implement after M4 |

---

# M4 — Knowledge Acquisition + Evidence RAG + Reasoning Replay

## M4 Objective

M4 gives AgentLab a governed knowledge loop:

```text
AgentLab knows when it lacks knowledge.
AgentLab can search internal project memory, its own framework memory, local documents, code, databases, web snapshots, and approved external sources.
AgentLab stages new knowledge before trusting it.
AgentLab can rerun or revise a prior reasoning event using newly acquired evidence.
AgentLab promotes validated knowledge into Project RAG, Self RAG, Project Brain, or Skill/SOP candidates.
```

M4 is the knowledge foundation required before serious Project-to-Revenue work.

## M4 Non-Goals

M4 must not implement:

```text
- commercial revenue loop
- CRM
- platform posting
- unsafe crawling
- login-wall/paywall bypass
- automatic external skill installation
- uncontrolled browser automation
- automatic publication/uploading
- opaque third-party database dumps
- cross-project memory sharing by default
```

---

## M4-0 — Baseline Re-Audit Before RAG

### Goal

Confirm current repo state before adding a cross-cutting knowledge subsystem.

### Required Output

```text
acceptance_runs/m4_rag_baseline/M4_RAG_BASELINE_REAUDIT_REPORT.md
```

### Required Checks

```bash
git status --short
git branch --show-current
git log --oneline -10
python -m compileall agent_runtime agentlab_app.py
python -m pytest -q
./agentlab.sh --help
./agentlab.sh run-pipeline --help
python scripts/audit_text_integrity.py
```

If remote raw audit exists:

```bash
python scripts/check_remote_raw_integrity.py --ref HEAD
```

### Report Must Include

```text
- current branch
- current commit
- latest remote commit
- full pytest result
- focused v1 guard result
- text integrity result
- existing RAG/local_search/intelligence modules if any
- existing web/search/intelligence capabilities if any
- existing project_brain layout
- existing operator timeline/event types
- existing assistant grounding sources
- dirty files or local-only project assets
```

### Acceptance

M4-0 passes if:

```text
- current repo is clean or dirty files are explicitly unrelated
- baseline tests pass or failures are documented before touching RAG
- text integrity passes
- no private project asset is committed
- report identifies exactly what RAG modules already exist and what is missing
```

---

## M4-1 — RAG Kernel and Knowledge Lifecycle

### Goal

Create the shared RAG engine and knowledge lifecycle used by both AgentLab Self RAG and per-project Project RAG.

### Add Runtime Modules

```text
agent_runtime/knowledge/
  __init__.py
  knowledge_gap.py
  knowledge_candidate.py
  knowledge_lifecycle.py
  knowledge_policy.py
  knowledge_promotion.py
  knowledge_store.py
  renderer.py

agent_runtime/rag/
  __init__.py
  models.py
  source_manifest.py
  source_scanner.py
  document_record.py
  chunk.py
  metadata_store.py
  citation.py
  provenance.py
  renderer.py
```

### Add Configs

```text
config/rag.yml
config/rag_source_policy.yml
config/rag_trust_policy.yml
config/knowledge_lifecycle.yml
```

### Knowledge Lifecycle

```text
discovered
→ staged
→ extracted
→ indexed
→ verified
→ promoted_project_knowledge
→ promoted_self_knowledge
→ promoted_skill_candidate
→ retired
```

### Knowledge Candidate Schema

```yaml
knowledge_candidate:
  candidate_id:
  project_id:
  source_type: self_repo | project_file | artifact | executor_result | web | database | document | code | media | user_correction
  source_uri:
  source_path:
  fetched_or_scanned_at:
  content_hash:
  extracted_text_path:
  structured_record_path:
  trust_level: untrusted | staged | verified | canonical | retired
  lifecycle_state: discovered | staged | extracted | indexed | verified | promoted | retired
  usable_for:
    - reasoning_revision
    - context_pack
    - research_brief
  not_usable_for:
    - canonical_fact_without_verification
  provenance:
    acquired_by:
    acquisition_plan:
    evidence_refs: []
  risk:
    privacy:
    license:
    source_quality:
    requires_human_review:
```

### CLI

```bash
./agentlab.sh knowledge-candidates --project <project>
./agentlab.sh knowledge-inspect --candidate <id>
./agentlab.sh knowledge-promote --candidate <id> --target project|self|skill-candidate
./agentlab.sh knowledge-retire --candidate <id>
```

### Tests

```text
tests/test_m4_knowledge_candidate.py
tests/test_m4_knowledge_lifecycle.py
tests/test_m4_rag_source_manifest.py
tests/test_m4_rag_metadata_store.py
```

### Acceptance

M4-1 passes if:

```text
- knowledge candidates can be created, staged, indexed, verified, promoted, and retired
- staged knowledge cannot be treated as canonical fact
- every candidate has source, hash, trust, lifecycle, provenance, and risk fields
- project and self knowledge targets are separated
- CLI can inspect lifecycle state
```

---

## M4-2 — AgentLab Self RAG

### Goal

AgentLab must understand and retrieve its own framework knowledge.

Self RAG indexes:

```text
README.md
docs/
AGENTS.md
CLAUDE.md
PROJECT_HANDOFF.md
OPERATING_MODEL.md
config/
agent_runtime/
agentlab_tui/
web_ui/
tests/
acceptance_runs/
skills/
shared_protocols/
```

### Data Layout

```text
.agentlab/rag/self/
  rag_source_manifest.yml
  corpus/
  chunks.jsonl
  indexes/
    fts.sqlite
    vectors/          # optional in M4-2
    graph.jsonl       # optional in M4-2
  metadata.sqlite
  citation_ledger.yml
  retrieval_logs/
  context_packs/
  eval/
```

### Add Modules

```text
agent_runtime/rag/self_builder.py
agent_runtime/rag/self_query.py
agent_runtime/rag/self_context.py
```

### CLI

```bash
./agentlab.sh self-rag-init
./agentlab.sh self-rag-index
./agentlab.sh self-rag-query --query "phase acceptance evidence rules"
./agentlab.sh self-rag-pack --purpose route_explanation --out /tmp/self_context_pack.md
./agentlab.sh self-rag-status
```

### Required Retrieval Filters

```text
source_type
file_path
module
test_name
acceptance_stage
commit_or_report_id
trust_level
current_vs_historical
```

### Acceptance

M4-2 passes if:

```text
- Self RAG can index docs/config/tests/acceptance_runs/agent_runtime without network
- self-rag-query can find known facts from docs and tests
- context pack includes citations to local file paths and line/section metadata where available
- generated self context does not include private runtime secrets
- Self RAG is usable by assistant explanation and route/recovery planning
```

---

## M4-3 — Project RAG Builder

### Goal

Every long-running project can create its own isolated RAG corpus.

Project RAG indexes:

```text
project_brain/
roadmap.yml
milestone_graph.yml
phase_plan.yml
acceptance_history.yml
decision_log.yml
known_risks.yml
next_actions.yml
context_snapshots/
phase_summaries/
artifacts/
evidence/
task_packets/
executor_results/
asset_registry.yml
artifact_lineage.yml
project_fact_snapshot.yml
project_fact_events.jsonl
state_transition_proposals/
user_corrections/
```

### Data Layout

```text
projects/<project_id>/rag/
  rag_source_manifest.yml
  corpus/
  chunks.jsonl
  indexes/
    fts.sqlite
    vectors/        # optional until M4-7
    graph.jsonl
  citation_ledger.yml
  retrieval_logs/
  context_packs/
  evidence_traces/
  knowledge_staging/
  verified_knowledge/
  eval/
```

### Add Modules

```text
agent_runtime/rag/project_builder.py
agent_runtime/rag/project_query.py
agent_runtime/rag/project_context.py
agent_runtime/rag/project_refresh.py
agent_runtime/rag/project_isolation.py
```

### RAG Source Manifest Schema

```yaml
rag_source_manifest:
  project_id:
  created_at:
  sources:
    - path: projects/<project>/project_brain/
      source_type: project_brain
      trust_level: canonical
      lifecycle_state: current
      include: true
      retrieval_policy: default

    - path: projects/<project>/artifacts/candidates/
      source_type: candidate_artifact
      trust_level: staged
      lifecycle_state: candidate
      include: true
      retrieval_policy: never_as_canonical_fact

    - path: projects/<project>/archive/
      source_type: archive
      trust_level: historical
      lifecycle_state: archived
      include: true
      retrieval_policy: history_only
```

### CLI

```bash
./agentlab.sh project-rag-init --project <project>
./agentlab.sh project-rag-index --project <project>
./agentlab.sh project-rag-query --project <project> --query "current phase blockers"
./agentlab.sh project-rag-pack --project <project> --task <task_id> --out /tmp/context_pack.md
./agentlab.sh project-rag-refresh --project <project>
./agentlab.sh project-rag-status --project <project>
```

### Acceptance

M4-3 passes if:

```text
- Project RAG initializes for a project without touching other projects
- project_brain and evidence artifacts are indexed
- candidate/archive content is marked non-canonical by default
- cross-project retrieval is blocked unless explicit global search mode is approved
- accepted phase updates trigger incremental refresh
- Project RAG status is visible to operator state/timeline
```

---

## M4-4 — Knowledge Acquisition Layer

### Goal

When reasoning is weak or knowledge is missing, AgentLab can safely acquire external/local knowledge and convert it into staged local knowledge.

### Supported Source Types

```text
self_rag
project_rag
local_docs
local_repo
approved_database
web_snapshot
native_web_fetcher
AnySearch_provider_optional
document_ingestion_result
vision_result
audio_result
executor_report
user_correction
```

### Add Runtime Modules

```text
agent_runtime/intelligence/
  __init__.py
  acquisition_plan.py
  source_policy.py
  source_extractor.py
  source_quality.py
  freshness.py
  citation_ledger.py
  native_web_fetcher.py       # mock-first or gated real mode
  database_provider.py        # mock-first
  renderer.py
```

### Acquisition Plan Schema

```yaml
knowledge_acquisition_plan:
  plan_id:
  purpose: revise_reasoning_event | prepare_task_packet | verify_claim | research_brief | recover_failure
  target_event_id:
  project_id:
  queries: []
  source_scopes:
    self_rag:
      enabled: true
    project_rag:
      enabled: true
      project_id:
    local_docs:
      enabled: true
      paths: []
    external_web:
      enabled: false
      approval_required: true
      max_sources:
      policy:
        block_private_ip: true
        block_file_url: true
        no_paywall_bypass: true
        require_citation: true
    database:
      enabled: false
      approval_required: true
  budget:
    max_sources:
    max_bytes:
    max_tokens:
    max_cost_usd:
  expected_outputs:
    - knowledge_candidates.yml
    - citation_ledger.yml
    - extraction_report.md
```

### Safety Rules

```text
- no private IP / localhost / file URL fetch by default
- no paywall/login-wall bypass
- no script execution
- no large binary download without approval
- all external sources require URL/timestamp/hash
- all external source claims require citation ledger entry
- all acquired knowledge enters staging first
```

### CLI

```bash
./agentlab.sh knowledge-gap-plan --reasoning-event <path> --out <dir>
./agentlab.sh acquire-knowledge --plan <plan.yml> --dry-run
./agentlab.sh acquire-knowledge --plan <plan.yml> --approve-network
./agentlab.sh citation-ledger --project <project>
```

### Acceptance

M4-4 passes if:

```text
- local/self/project retrieval works offline
- external web acquisition is disabled/gated by default
- dry-run plan shows what would be fetched
- acquired sources become staged knowledge candidates, not canonical facts
- citation ledger records source URI/path/timestamp/hash
- unsafe URLs are blocked
```

---

## M4-5 — Reasoning Event and Reasoning Replay

### Goal

Record important model/system reasoning events in an auditable summary form, detect when they need more knowledge, and revise them using Evidence RAG.

Do not store private chain-of-thought. Store only:

```text
question
reasoning_summary
claims
confidence
uncertainty_flags
evidence_refs
decision
revision history
```

### Add Runtime Modules

```text
agent_runtime/reasoning/
  __init__.py
  reasoning_event.py
  critique.py
  knowledge_gap_detector.py
  replay.py
  revision.py
  renderer.py
```

### Reasoning Event Schema

```yaml
reasoning_event:
  event_id:
  project_id:
  task_id:
  phase_id:
  role:
  question:
  reasoning_summary:
  claims:
    - claim:
      evidence_refs: []
      confidence: low | medium | high
  confidence: 0.0
  uncertainty_flags:
    - insufficient_evidence
    - missing_project_context
    - missing_external_context
    - possible_outdated_knowledge
    - verifier_disagreed
  decision:
    status: accepted | needs_knowledge_acquisition | needs_replay | rejected
    rationale:
  created_at:
```

### Reasoning Revision Schema

```yaml
reasoning_revision:
  original_event_id:
  revision_id:
  acquisition_plan:
  revision_context_pack:
  revised_conclusion:
  confidence_before:
  confidence_after:
  changed_claims:
    - old:
      new:
      evidence_refs: []
  remaining_uncertainties: []
  recommended_actions: []
  verifier_status: pending | accepted | rejected
```

### CLI

```bash
./agentlab.sh reasoning-event-create --project <project> --task <task_id> --from-report <path>
./agentlab.sh reasoning-critique --event <event.yml>
./agentlab.sh reasoning-replay --event <event.yml> --context-pack <context_pack.md> --out <dir>
./agentlab.sh reasoning-revisions --project <project>
```

### Acceptance

M4-5 passes if:

```text
- important reasoning events can be recorded without private chain-of-thought
- low-confidence/no-evidence reasoning triggers knowledge_gap
- knowledge_gap produces acquisition_plan
- reasoning replay produces revision with changed claims and evidence refs
- verifier can reject no-citation revisions
- accepted revisions update project decision_log or recovery plan
```

---

## M4-6 — Evidence-Grounded Context Packing

### Goal

Replace raw prompt history with task-specific, source-grounded context packs for executors, reviewers, assistants, recovery, and project planning.

### Add Runtime Modules

```text
agent_runtime/rag/retrieval_plan.py
agent_runtime/rag/retriever.py
agent_runtime/rag/reranker.py
agent_runtime/rag/filters.py
agent_runtime/rag/context_packer.py
agent_runtime/rag/context_budget.py
agent_runtime/rag/context_renderers.py
```

### Retrieval Plan Schema

```yaml
retrieval_plan:
  plan_id:
  project_id:
  task_id:
  purpose: executor_handoff | verifier_review | assistant_answer | recovery_replan | reasoning_replay
  needs:
    - current_project_goal
    - current_phase
    - relevant_files
    - accepted_facts
    - previous_failures
    - known_risks
    - acceptance_criteria
  filters:
    project_id:
    lifecycle_state:
      - current
      - accepted
    trust_level:
      - canonical
      - verified
    exclude:
      - rejected_candidate_as_fact
      - archive_as_current_fact
  retrieval_modes:
    - fts
    - semantic_optional
    - graph_optional
  max_context_tokens:
  evidence_required: true
```

### Context Pack Layout

```markdown
# Context Pack

## Task

## Canonical Project Facts

## Relevant Decisions

## Relevant Files / Artifacts

## Acceptance Criteria

## Known Risks

## Previous Failures

## Forbidden / Do Not Use

## Evidence References
```

### Integration Points

```text
- executor task_packet must link to context_pack.md
- phase_acceptance must read evidence_refs from context_pack and executor_result
- assistant answers must cite context sources
- recovery plans must cite failure and evidence sources
- project-next must use compact RAG pack, not raw full history
```

### CLI

```bash
./agentlab.sh rag-plan --project <project> --task <task_id> --purpose executor_handoff
./agentlab.sh rag-pack --plan <retrieval_plan.yml> --out <dir>
./agentlab.sh rag-query --project <project> --query "current blockers" --mode current
```

### Acceptance

M4-6 passes if:

```text
- context packs can be generated for executor_handoff, verifier_review, assistant_answer, recovery_replan, and reasoning_replay
- packs have bounded token budgets
- every factual pack item has a source reference
- archive/candidate content is clearly marked and not used as current fact
- task_packet includes context_pack path
- verifier fails factual output with missing evidence when evidence_required=true
```

---

## M4-7 — RAG Evaluation and Anti-Stale Guards

### Goal

Prove RAG retrieval is safe, relevant, isolated, and not poisoning project memory.

### Add Runtime Modules

```text
agent_runtime/rag/eval/
  __init__.py
  test_cases.py
  evaluator.py
  metrics.py
  fixtures.py
  report.py
```

### Required Eval Cases

```text
known_answer_retrieval
anti_stale_archive_retrieval
candidate_isolation
cross_project_isolation
phase_context_retrieval
evidence_grounding
context_budget_limit
reasoning_replay_improves_confidence
unsafe_source_blocking
no_citation_claim_rejection
```

### CLI

```bash
./agentlab.sh rag-eval --suite offline --out acceptance_runs/m4_rag_eval
./agentlab.sh rag-eval --project <project> --suite project
```

### Metrics

```yaml
rag_eval_metrics:
  known_answer_recall:
  stale_fact_rejection_rate:
  candidate_as_fact_rejection_rate:
  cross_project_leak_rate:
  evidence_grounding_rate:
  context_budget_pass_rate:
  unsafe_source_block_rate:
  reasoning_revision_acceptance_rate:
```

### Acceptance

M4-7 passes if:

```text
- offline RAG eval suite runs without network
- known current facts are retrieved from canonical sources
- stale/archive facts are not treated as current facts
- candidate/draft facts are not promoted without acceptance
- cross-project contamination is blocked
- context packs stay within budget
- no-citation factual claims fail verification
- reasoning replay can improve or explicitly lower confidence with evidence
```

---

## M4 Final Acceptance

M4 is accepted only if all of the following are true:

```text
- M4-0 baseline re-audit report exists
- shared knowledge lifecycle exists
- Self RAG can index and query AgentLab docs/config/tests/acceptance/runtime modules
- Project RAG can initialize, index, query, and refresh per project
- project isolation and trust/lifecycle filtering are enforced
- external knowledge acquisition is staged and gated
- reasoning events and revisions are recorded without private chain-of-thought
- reasoning replay uses context packs and evidence refs
- executor/reviewer/assistant/recovery workflows can consume RAG context packs
- RAG eval suite catches stale/archive/candidate/cross-project/no-citation failures
- no network or external execution is required for tests
- all new files pass text integrity
- full pytest passes
```

### M4 Acceptance Report

Create:

```text
acceptance_runs/m4_knowledge_rag/M4_KNOWLEDGE_RAG_REPORT.md
```

Report must include:

```text
- baseline commit and test state
- modules added
- configs added
- CLI commands added
- Self RAG demo
- Project RAG demo
- Knowledge Acquisition dry-run demo
- Reasoning Replay demo
- Context Pack demo
- RAG Eval results
- safety notes
- known limitations
- next stage: M5 Project-to-Revenue OS
```

---

# M5 — Project-to-Revenue OS

## M5 Objective

M5 is the old M3 Project-to-Revenue OS, moved here because v1 stable accepted only the internal closed loop and explicitly kept commercial/productization outside that acceptance scope.

M5 answers:

```text
Why is this project being produced?
Who is it for?
What assets are created?
How are assets used?
What value or revenue path exists?
What production loop exists?
What data should be tracked?
What compliance risks exist?
What SOP/skill should be learned?
```

## M5 Dependency on M4

M5 must use M4 RAG for:

```text
- business contract evidence
- market/channel source grounding
- asset lineage retrieval
- production pipeline context packs
- analytics/revenue reasoning revision
- compliance source tracking
- CRM/delivery memory
- SOP/skill candidate mining
```

No M5 factual business claim may bypass M4 citation/evidence rules.

## M5 Stages

```text
M5-1 Business Contract
M5-2 Asset Registry + Lineage
M5-3 Production Pipeline Templates
M5-4 Market / Channel Intelligence
M5-5 Analytics + Revenue Ledger
M5-6 Compliance / Risk Brain
M5-7 CRM / Client Delivery Loop
M5-8 SOP / Skill Factory 2.0
M5-9 End-to-End P2R Demo Projects
```

### M5-1 — Business Contract

Add:

```text
agent_runtime/business/
  business_contract.py
  revenue_model.py
  customer_profile.py
  unit_economics.py
  monetization_plan.py
  commercial_risk.py
  success_metrics.py
  renderer.py
```

Project layout:

```text
projects/<project_id>/business_brain/
  business_goal.yml
  revenue_model.yml
  customer_profile.yml
  monetization_plan.yml
  cost_model.yml
  pricing_assumptions.yml
  risk_register.yml
  success_metrics.yml
```

Must use M4 context packs for market/source evidence where factual claims are made.

### M5-2 — Asset Registry + Lineage

Add:

```text
agent_runtime/assets/
  asset_registry.py
  asset_lineage.py
  asset_versioning.py
  rights_metadata.py
  usage_tracker.py
  quality_report.py
  renderer.py
```

Project layout:

```text
projects/<project_id>/assets/
  asset_registry.yml
  asset_lineage.yml
  version_history.yml
  rights_and_license.yml
  usage_records.yml
  asset_quality_reports/
```

Asset lineage must become graph-indexable by M4 Project RAG.

### M5-3 — Production Pipeline Templates

Add:

```text
agent_runtime/production/
  pipeline_template.py
  pipeline_instance.py
  production_calendar.py
  batch_scheduler.py
  stage_gate.py
  throughput_tracker.py
  backlog_manager.py
  renderer.py
```

Required templates:

```text
content_ip_pipeline
service_delivery_pipeline
saas_product_pipeline
research_consulting_pipeline
local_automation_pipeline
audio_music_pipeline
```

### M5-4 — Market / Channel Intelligence

Must use M4 Knowledge Acquisition and citation ledger. Agent-Reach-like providers remain disabled by default and approval-gated.

### M5-5 — Analytics + Revenue Ledger

Manual/offline first. No external analytics API required in first pass.

### M5-6 — Compliance / Risk Brain

Must block:

```text
fake engagement
spam automation
bulk account creation
platform policy evasion
paywall/login-wall bypass
impersonation
copyright theft
client data leakage
unapproved posting
```

### M5-7 — CRM / Client Delivery Loop

Skeleton only; no payment/legal automation without explicit scope and human review.

### M5-8 — SOP / Skill Factory 2.0

Successful workflows and repeated failures become SOP/playbook/skill candidates through existing Skill OS and M4 evidence traces.

### M5-9 — End-to-End P2R Demos

Required offline demos:

```text
1. AI Novel / Video IP Project
2. Local Automation Service Project
3. Small SaaS / Tool Product Project
```

M5 passes only if all demos use M4 evidence/RAG for factual/project memory claims.

---

## 6. Updated External Project Placement

| External Project | Current Meaning | M4 Placement | M5 Placement |
|---|---|---|---|
| MinerU | Document ingestion provider | staged document knowledge source | commercial document/contract/report assetization |
| MarkItDown | Lightweight document extraction | local document ingestion into Project RAG | content/document asset pipeline |
| Codebase-Memory-MCP | Code structural memory | code knowledge provider, brokered/gated | code asset lineage and repo knowledge reuse |
| Graphify | Knowledge graph provider | optional graph index provider | asset lineage graph/project graph |
| Supervision | Vision evidence normalization | vision result ingestion into evidence RAG | video/content QA asset evidence |
| mattpocock/skills | Skill package reference | skill/SOP candidate source | SOP/skill factory reference |
| Ponytail | Minimal reviewer | verifier/reasoning critique reference | cost-reduction / anti-overengineering gate |
| Agent-Reach | Web/social intelligence provider | high-risk acquisition provider, disabled by default | market/channel intelligence, gated |
| BabyAGI | Self-evolving skill reference | reasoning replay / skill mining inspiration only | SOP/skill factory inspiration, no auto-exec |
| AiToEarn | P2R reference | not M4 core | content production/channel-operation reference |

---

## 7. Repository-Level Corrections Still Required

### 7.1 Update README / Handoff Status

README currently may lag behind latest commits. After M4-0, update baseline references so public docs do not say “M0/M1 consolidation before M2/M3” if the repo has already passed v1 internal closed-loop acceptance.

### 7.2 Fix Single-Line Markdown Reports If Text Integrity Policy Requires It

Some raw acceptance reports may appear as single-line Markdown. If the repo policy now rejects compressed files, ensure generated reports are real multiline Markdown.

### 7.3 Add RAG to Operator State, But Do Not Bypass It

Operator surfaces should show:

```text
self_rag_status
project_rag_status
knowledge_candidates
retrieval_logs
context_packs
reasoning_events
reasoning_revisions
stale_fact_warnings
citation_coverage
```

But operator surfaces must not directly mutate canonical memory without `Operator Action Runtime` / approval gates.

### 7.4 Extend Timeline Event Types

Add M4 timeline events:

```text
rag_source_discovered
rag_index_started
rag_index_completed
knowledge_gap_detected
knowledge_acquisition_planned
knowledge_candidate_staged
knowledge_candidate_verified
knowledge_promoted
reasoning_event_recorded
reasoning_replay_started
reasoning_revision_created
reasoning_revision_accepted
context_pack_created
rag_eval_completed
stale_fact_blocked
cross_project_rag_blocked
```

### 7.5 Extend Cost/Risk Policy

RAG has costs and risks:

```text
indexing cost
embedding cost if enabled
web acquisition cost
database query cost
private data exposure risk
source licensing risk
memory poisoning risk
cross-project leakage risk
stale fact risk
```

Cost/risk policy must gate these before M4 is accepted.

---

## 8. Suggested Implementation Prompt for M4

```markdown
You are working on Kidrage/AgentLab.

Current task: M4 Knowledge Acquisition + Evidence RAG + Reasoning Replay.

Important current-state rule:
- Treat M0/M1/M2/M3 internal closed-loop as accepted baseline unless tests prove regression.
- Do not reimplement mission compiler, project brain, executor connector, phase acceptance, cost system, TUI/WebUI, or assistant grounding.
- Integrate RAG into those systems instead.
- Do not implement M5 Project-to-Revenue yet.

Implement in order:
1. M4-0 Baseline Re-Audit Before RAG.
2. M4-1 RAG Kernel and Knowledge Lifecycle.
3. M4-2 AgentLab Self RAG.
4. M4-3 Project RAG Builder.
5. M4-4 Knowledge Acquisition Layer.
6. M4-5 Reasoning Event and Reasoning Replay.
7. M4-6 Evidence-Grounded Context Packing.
8. M4-7 RAG Evaluation and Anti-Stale Guards.

Hard safety rules:
- No network by default.
- No external search/fetch without explicit acquisition plan and approval.
- No private IP, localhost, file URL, login-wall, or paywall bypass.
- All external knowledge enters staged state first.
- Staged knowledge is never canonical.
- Candidate/archive/draft content is never current fact by default.
- Cross-project retrieval is blocked by default.
- No private chain-of-thought storage; only reasoning summaries, claims, uncertainty flags, evidence refs, and revision records.
- No factual claim without citation/evidence ref when evidence_required=true.

Run:
python -m compileall agent_runtime agentlab_app.py
python -m pytest -q
./agentlab.sh --help
./agentlab.sh run-pipeline --help
python scripts/audit_text_integrity.py

Create:
acceptance_runs/m4_knowledge_rag/M4_KNOWLEDGE_RAG_REPORT.md
```

---

## 9. One-Line Summary

```text
M1-M3 made AgentLab govern and operate internal long-running projects.
M4 makes AgentLab learn, retrieve, cite, revise reasoning, and preserve project/self knowledge safely.
M5 then uses that knowledge substrate to build Project-to-Revenue business, asset, production, analytics, compliance, CRM, and SOP loops.
```
