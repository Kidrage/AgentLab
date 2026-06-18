# AgentLab S1-C Domain Workflow Templates

## 1. Why domain workflow templates exist

S1-B proved that AgentLab can compile a raw prompt into a deterministic
`MissionContract`. S1-C/D/E/F strengthens that compiler by adding a domain-aware
planning layer.

Different domains need different production workflows. A repository repair task
needs branch awareness, changed-file summaries, tests, rollback notes, and secret
checks. A research task needs source collection, freshness checks, citations, and
fake-citation guards. A creative longform task needs outline and continuity
planning before final drafting. A local filesystem cleanup task needs dry-run,
rollback, path scope, and human approval.

Domain workflow templates capture those differences as deterministic YAML data.
They are used only during compile-time planning. They do not execute tools, call
external APIs, browse the web, inspect local files, run vision/audio systems, or
insert the contract into the full runtime lifecycle.

## 2. Core concepts

### Task type

A task type is the coarse `MissionTaskType` selected by the deterministic keyword
classifier. Examples include `coding`, `research`, `creative_longform`,
`document_processing`, `data_analysis`, `audio_music`, `multimodal`,
`local_ops`, and `unknown`.

### Domain signal

A domain signal is a transparent note emitted by `domain_signals.py`. It records
which keywords contributed to classification. Signals are evidence for planning,
not proof that a runtime capability exists.

### Domain workflow template

A domain workflow template is a YAML record in
`config/domain_workflow_templates.yml`. It contains the domain-specific task
types, trigger signals, capabilities, phases, artifacts, acceptance gates, risks,
human approval policy, and notes.

### Required capability

A required capability names what future execution would need. The compiler may
record capabilities that are not implemented locally. Missing capabilities are
reported as decision cards and capability-gap acceptance gates instead of being
silently assumed.

### Artifact contract

An artifact contract names the evidence or deliverable expected before a future
execution result is accepted. S1-D merges base task-type artifacts, template
artifacts, and prompt-specific artifacts.

### Acceptance gate

An acceptance gate describes what a future reviewer, human, or execution layer
must verify. S1-E merges base gates, template gates, prompt-specific gates, and
capability-gap gates.

### Risk

A risk is a deterministic planning warning stored in the Mission Contract risks
field. S1-F includes domain-specific risks such as regression risk, fake citation
risk, visual hallucination risk, subjective audio evaluation risk, and destructive
change risk.

## 3. Included templates

The MVP template catalog includes:

- `coding_software_engineering`
- `debugging_triage`
- `research_investigation`
- `business_strategy`
- `creative_longform`
- `document_processing`
- `data_analysis`
- `audio_music`
- `multimodal_vision`
- `local_ops_automation`
- `education_tutoring`
- `unknown_exploratory`

Each template includes task types, trigger signals, required capabilities, phase
plans, required artifacts, acceptance gates, risk defaults, human approval rules,
and notes. The `unknown_exploratory` template is the safe fallback for unknown or
unmatched domains.

## 4. Selection behavior

`load_domain_workflow_templates()` loads the YAML catalog and returns a
`DomainWorkflowCatalog`. Malformed or missing entries produce structured catalog
warnings. The loader does not expose raw tracebacks for malformed YAML or missing
files.

`select_domain_workflow()` chooses a template by:

1. preferring templates whose `task_types` contain the classified task type;
2. using domain signal overlap as the tie-breaker;
3. falling back to `unknown_exploratory` when there is no match;
4. never crashing on unknown task types.

The selected template is preserved in the compile packet as
`selected_template_id` and in Mission Contract notes as:

```text
domain_workflow_template: <template_id>
```

## 5. Artifact merge behavior

The artifact builder now merges three layers:

```text
base artifacts from task type
+ artifacts from selected domain workflow template
+ prompt-specific artifacts
```

Prompt-specific artifacts include:

- `ci_results.md` for CI or GitHub Actions prompts;
- `documentation_update.md` for README/docs prompts;
- `evaluation_report.md` for benchmark/eval prompts;
- `table_extraction_report.md` for PDF/table prompts;
- `vision_observations.yml` for screenshot/image/video prompts;
- `audio_analysis_report.md` for audio/music/spatial/HRTF prompts;
- `dry_run_report.md` and `rollback_plan.md` for cleanup/delete/filesystem
  prompts.

Artifacts are deduplicated while preserving stable order.

## 6. Acceptance gate merge behavior

The acceptance builder now merges:

```text
base gates from task type
+ gates from selected domain workflow template
+ prompt-specific gates
+ capability-gap gates
```

Prompt-specific gates require CI evidence, test command output, source citations
and freshness, visual provenance and uncertainty labels, separation of audio
measurements from listening notes, dry-run and rollback for local operations, and
handoff/evidence ledgers for external agents or tools.

Research tasks always guard against fake citations. Creative longform tasks keep
outline and continuity planning ahead of final drafting. Capability gaps are
reported explicitly rather than hidden.

## 7. Assumptions, unknowns, and decision cards

`assumption_builder.py` generates deterministic assumptions, unknowns, and plain
Python decision-card dictionaries.

Examples:

- coding tasks without repo/path/branch add a missing-context unknown;
- research tasks without target region, timeframe, or source policy add
  unknowns;
- creative tasks without genre, tone, length, or audience add unknowns;
- document tasks without file/path/output format add unknowns;
- data tasks without source, schema, or output goal add unknowns;
- audio tasks without input asset, playback target, or evaluation method add
  unknowns;
- multimodal tasks without image/video/file path add unknowns;
- local destructive work adds a human-approval decision card;
- unimplemented capabilities add capability-gap decision cards;
- latest/current/today prompts add a freshness assumption and risk-review card.

There is no runtime decision-card system integration yet.

## 8. Risk generation

`risk_builder.py` combines task-type risks, template `risk_defaults`, prompt
signals, and capability-gap signals. The Task Compiler stores the resulting risk
names as simple `MissionRisk` entries.

Examples:

- coding/debugging: regression risk, insufficient test coverage, local path or
  secret leak risk;
- research/business: stale source risk, fake citation risk, source quality risk;
- creative longform: continuity drift, tone mismatch, premature draft without
  outline;
- document processing: extraction errors, table structure loss, OCR quality;
- data analysis: dirty data, schema mismatch, misleading charts;
- audio/music: subjective evaluation, playback environment mismatch, loudness or
  clipping artifacts;
- multimodal: visual hallucination, OCR errors, missing frame/page reference;
- local ops: destructive changes, rollback failure, path-scope risk;
- unknown: ambiguous goal and capability gap.

## 9. Non-goals

S1-C/D/E/F explicitly does not implement:

- runtime execution;
- full 14-node lifecycle integration;
- web intelligence runtime;
- vision runtime;
- audio analysis runtime;
- LLM planner;
- skill installation or promotion;
- OpenClaw adapter integration;
- coding agent connector loops;
- dashboards;
- network tests;
- database, Redis, Postgres, or heavy dependencies.

The compiler remains local-first, deterministic, testable, and non-executing.

## 10. Future S2 expansion path

Future S2 work can expand this MVP by:

- versioning template catalogs;
- adding richer domain-specific phases and artifact schemas;
- adding runtime availability checks behind explicit gates;
- connecting selected templates to lifecycle routing only after tests and safety
  policies exist;
- adding source collection, vision, audio, and data runtimes as separately
  approved execution layers;
- promoting repeated human feedback into concise template updates and validation
  checks.

Until then, templates are planning contracts, not production workflow execution.
