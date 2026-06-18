# AgentLab S1-B Task Compiler MVP

## 1. What S1-B adds

S1-B adds the first deterministic Task Compiler layer for AgentLab.

It accepts a raw user prompt and produces a structured `MissionContract` that a
future runtime can inspect before execution. The MVP proves the local path:

```text
raw user prompt
→ intent summary
→ lightweight task type classification
→ assumptions / unknowns
→ required capabilities
→ required artifacts
→ acceptance gates
→ human approval policy
→ MissionContract object
→ mission_contract.yml
```

The implementation lives in `agent_runtime/brain/task_compiler.py` and helper
builders under `agent_runtime/brain/`.

## 2. Task Compiler vs Mission Contract schema

The S1-A Mission Contract schema is the stable data contract.

The S1-B Task Compiler is a deterministic producer of that schema. It does not
change the meaning of the schema and does not replace validation. Instead, it
fills the existing fields using transparent heuristics:

- `task_type`
- `intent_summary`
- `unknowns`
- `assumptions`
- `required_capabilities`
- `required_artifacts`
- `acceptance_gates`
- `human_approval`
- `recommended_route`
- `notes`

If the compiler creates invalid schema data, it raises a structured
`TaskCompilationError` instead of exposing a raw traceback.

## 3. Deterministic local-first scope

The MVP is intentionally local-first and deterministic.

It must not:

- execute tools;
- browse the web;
- call external providers;
- mutate AgentLab runtime task lifecycle state;
- install skills;
- connect to databases;
- run AnySearch, CodeGraph, ECC, OpenClaw, or coding-agent loops.

Identical prompt text and options produce the same classification logic and the
same builder outputs, aside from the `created_at` timestamp in the contract.

## 4. Public API

Primary API:

```python
compile_task_to_contract(
    user_prompt: str,
    *,
    task_id: str | None = None,
    project: str | None = None,
    output_dir: Path | str | None = None,
    strict: bool = False,
) -> MissionContract
```

Packet API:

```python
compile_task_packet(
    user_prompt: str,
    *,
    task_id: str | None = None,
    project: str | None = None,
) -> TaskCompilationResult
```

`TaskCompilationResult` contains:

- `contract`
- `intent_summary`
- `domain_signals`
- `warnings`
- `decision_cards`

## 5. Supported task types

The classifier aligns with `MissionTaskType` and supports:

- `coding`
- `debugging`
- `research`
- `business`
- `creative_longform`
- `document_processing`
- `data_analysis`
- `audio_music`
- `multimodal`
- `local_ops`
- `education`
- `unknown`

Classification is rule-based. Keyword matches are scored by domain, ties are
resolved by a fixed priority order, and secondary matches are preserved in
`domain_signals`.

## 6. Domain signals

`agent_runtime/brain/domain_signals.py` contains transparent keyword rules.

Examples:

- coding/debugging: `repo`, `repository`, `GitHub`, `bug`, `pytest`, `CI`,
  `traceback`, `patch`, `commit`, `branch`, `CLI`, `API`, `function`, `class`
- research/business: `research`, `investigate`, `compare`, `market`, `company`,
  `competitor`, `industry`, `source`, `citation`, `latest`, `report`
- creative longform: `novel`, `story`, `script`, `chapter`, `character`,
  `worldbuilding`, `outline`, `rewrite`, `scene`
- document processing: `PDF`, `docx`, `document`, `summarize`, `extract`,
  `table`, `OCR`, `parse`, `format`
- data analysis: `csv`, `xlsx`, `spreadsheet`, `dataframe`, `chart`,
  `statistics`, `analyze data`, `clean data`
- audio/music: `audio`, `music`, `mix`, `master`, `spatial audio`, `HRTF`,
  `MIR`, `stem`, `loudness`, `spectrogram`, `speaker`, `binaural`
- multimodal: `image`, `screenshot`, `video`, `figure`, `diagram`, `photo`,
  `UI screenshot`, `visual`
- local ops: `local file`, `folder`, `backup`, `organize`, `shell`,
  `filesystem`, `NAS`, `server`, `deploy`
- education: `teach`, `explain`, `lesson`, `homework`, `quiz`, `study`, `tutor`

## 7. Required capabilities builder

The capability builder records what future execution would need.

It may include capabilities that AgentLab does not yet implement. That is not a
compiler failure. It is a capability gap represented in the contract and packet
decision cards.

Common capability names include:

- `file_read`
- `file_write`
- `code_edit`
- `repo_inspection`
- `test_execution`
- `web_search`
- `source_citation`
- `long_document_reading`
- `image_understanding`
- `video_understanding`
- `audio_analysis`
- `spreadsheet_processing`
- `data_analysis`
- `local_shell`
- `skill_discovery`
- `human_approval`

Rules include:

- research/business requires `web_search` and `source_citation`;
- coding/debugging requires `repo_inspection`, `code_edit`, and
  `test_execution`;
- screenshot/image prompts require `image_understanding`;
- video prompts require `video_understanding`;
- audio/music prompts require `audio_analysis`;
- spreadsheet/data prompts require `spreadsheet_processing` or `data_analysis`;
- unknown prompts require `human_approval`.

## 8. Artifact builder

`agent_runtime/brain/artifact_builder.py` maps task types to default required
artifacts.

Examples:

- coding/debugging: `intent_summary.md`, `repo_findings.md`, `patch_plan.md`,
  `changed_files_summary.md`, `test_results.md`, `acceptance_report.md`
- research/business: `research_plan.md`, `source_table.yml`,
  `evidence_notes.md`, `analysis_report.md`, `citation_ledger.yml`,
  `uncertainty_notes.md`
- creative longform: `creative_brief.md`, `world_or_context_bible.md`,
  `character_or_structure_notes.md`, `outline.md`, `draft.md`,
  `continuity_ledger.md`, `revision_notes.md`
- document processing: `extraction_plan.md`, `parsed_content.md`,
  `table_outputs/`, `quality_check.md`, `summary.md`
- data analysis: `data_profile.md`, `cleaning_log.md`,
  `analysis_notebook_or_script.py`, `charts/`, `findings_report.md`
- audio/music: `audio_task_brief.md`, `input_asset_manifest.yml`,
  `analysis_report.md`, `processing_plan.md`, `listening_or_validation_notes.md`
- multimodal: `input_artifact_manifest.yml`, `vision_observations.yml`,
  `extracted_text.md`, `annotated_artifacts/`, `visual_summary.md`
- local ops: `operation_plan.md`, `dry_run_report.md`,
  `changed_files_manifest.yml`, `rollback_plan.md`, `completion_report.md`
- education: `learning_goal.md`, `lesson_plan.md`, `explanation.md`,
  `practice_questions.md`, `answer_key.md`
- unknown: `intent_summary.md`, `clarifying_questions.md`, `assumptions.yml`,
  `proposed_plan.md`

## 9. Acceptance gate builder

`agent_runtime/brain/acceptance_builder.py` maps task types to gates that future
execution or review must satisfy.

Examples:

- coding/debugging gates require compile/static checks, relevant tests, changed
  file summaries, no leaked secrets or local absolute paths, and rollback notes.
- research/business gates require sourced factual claims, timestamps or access
  dates, explicit uncertainty, no fake citations, and source quality notes.
- creative longform gates require genre/tone alignment, coherent structure,
  continuity tracking, revision notes, and outline-first behavior.
- multimodal gates require artifact references, uncertain visual claims marked,
  extracted text separated from interpretation, and capability-gap declaration
  when no vision tool exists.
- audio/music gates require asset manifests, analysis method, separation of
  subjective and measurable observations, and validation/listening notes.
- local ops gates require dry-runs, rollback plans, path-scope confirmation, and
  human approval for destructive changes.
- unknown gates require clarifying questions or assumptions and human approval.

## 10. Assumptions, unknowns, and approval

The compiler never crashes solely because a prompt is underspecified, except for
an empty prompt. Instead it writes conservative unknowns and assumptions.

Unknowns are added when:

- the prompt lacks a target repo, file, data source, artifact, or scope;
- the prompt is very short;
- research/business sources are not collected yet;
- local operations lack path scope;
- classification falls back to `unknown`.

Human approval is required when:

- task type is `unknown`;
- the prompt is local-ops or potentially destructive;
- required capabilities are not implemented in the local S1-B runtime.

## 11. Capability gap behavior

S1-B treats unimplemented required capabilities as planning information, not as
compile failures.

For example, a screenshot prompt can compile successfully while requiring
`image_understanding`. If no local vision runtime exists, the compile packet adds
a `capability_gap` decision card and the contract requires human approval.

This lets AgentLab preserve the user need without pretending the capability is
already available.

## 12. CLI usage

The optional CLI is available at `scripts/compile_mission_contract.py`.

Example:

```bash
python scripts/compile_mission_contract.py \
  --task-id demo_s1_b \
  --project AgentLab \
  --prompt "Fix the pytest failure in this repository and produce an acceptance report." \
  --output /tmp/mission_contract.yml
```

The CLI writes YAML and prints JSON with:

- task id;
- task type;
- required capability count;
- required artifact count;
- acceptance gate count;
- human approval flag;
- output path.

It accepts prompt text through `--prompt` or a UTF-8 prompt file through
`--prompt-file`.

## 13. Example inputs

Short deterministic fixtures live under `examples/task_compiler_inputs/`:

- `coding_bug.txt`
- `research_company.txt`
- `creative_novel.txt`
- `multimodal_screenshot.txt`
- `audio_music_analysis.txt`
- `document_pdf.txt`
- `data_spreadsheet.txt`
- `local_ops_cleanup.txt`
- `unknown_ambiguous.txt`

Tests compile every example and validate the resulting `MissionContract`.

## 14. Non-goals confirmed

S1-B does not implement:

- full domain workflow templates;
- LLM planning;
- runtime lifecycle integration;
- external execution;
- web intelligence runtime;
- vision runtime;
- external skill install or execution;
- OpenClaw adapter integration;
- coding agent connector loop;
- Long Project Orchestrator;
- Dashboard;
- database, Redis, Postgres, or heavy dependency integration.

## 15. Future S1-C/D/E/F extension points

Future work can extend the MVP without changing S1-B guarantees:

- S1-C can add richer domain workflow templates behind explicit versioned
  builders.
- S1-D can add optional LLM planning while preserving deterministic fallback
  compilation.
- S1-E can add capability discovery and runtime availability checks without
  turning gaps into silent failures.
- S1-F can integrate Task Compiler into the runtime lifecycle behind tested,
  disabled-by-default flags or explicit approval gates.

## 16. Operational safety

Agents should treat Task Compiler output as planning data.

Execution remains a separate concern. A valid compiled MissionContract does not
grant permission to modify files, call APIs, browse the web, or run shell
commands. Those actions require the normal AgentLab execution route, approval
policy, and verification gates.
