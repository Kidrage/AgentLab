# AgentLab M1-2 Mission Compiler v2 Report

## Verdict
**PASS**

## Baseline
- branch: `main`
- before commit: `b2cda6a` (feat: add M1 external project registry)
- after commit: uncommitted (pending review)
- remote: origin/main
- CI: not run (local validation only)

## Summary

M1-2 implements a deterministic, rule-based Mission Compiler v2 that upgrades
AgentLab from basic task-level intent classification into project-level demand
compilation. The compiler reads a rough user prompt and produces a structured
`mission_contract.yml` with domain, project type, capabilities, artifacts,
acceptance gates, risk flags, and decision cards — all without any LLM calls.

### What Changed

- **10 new runtime modules** under `agent_runtime/brain/`:
  domain classifier, project type classifier, capability requirement builder,
  artifact contract builder, acceptance gate builder, risk classifier,
  decision card builder, mission contract compiler, renderer, and `__init__.py`.

- **4 new config files** under `config/`:
  mission_compiler_v2.yml, project_type_classifier.yml,
  project_artifact_contracts.yml, project_acceptance_gates.yml.

- **6 prompt fixture files** under `examples/prompts/`:
  one for each supported project type (codebase, longform, video, research,
  document, local automation).

- **1 CLI command** added to `run_task.py`:
  `./agentlab.sh mission-compiler compile --prompt-file <path> --out <dir>`.

- **84 new tests** in `tests/test_m1_mission_compiler_v2.py`.

## Changed Files

| File | Reason |
|------|--------|
| `agent_runtime/run_task.py` | Add `mission-compiler` Typer sub-app and `compile` command |
| `agent_runtime/brain/__init__.py` | New module — package init |
| `agent_runtime/brain/mission_contract.py` | New — top-level mission contract builder |
| `agent_runtime/brain/domain_classifier.py` | New — keyword-based task domain detection |
| `agent_runtime/brain/project_type_classifier.py` | New — project type classification + typedef loading |
| `agent_runtime/brain/capability_requirement_builder.py` | New — capability gap detection |
| `agent_runtime/brain/artifact_contract_builder.py` | New — per-phase artifact contracts |
| `agent_runtime/brain/acceptance_gate_builder.py` | New — global + per-type acceptance gates |
| `agent_runtime/brain/risk_classifier.py` | New — non-goal pattern + constraint detection |
| `agent_runtime/brain/decision_card_builder.py` | New — human decision point cards |
| `agent_runtime/brain/renderer.py` | New — YAML + Markdown output writer |
| `config/mission_compiler_v2.yml` | New — domain keywords, project type keywords, scale heuristics, non-goal patterns |
| `config/project_type_classifier.yml` | New — 8 project type definitions with phases, capabilities, risks |
| `config/project_artifact_contracts.yml` | New — per-phase artifact output definitions |
| `config/project_acceptance_gates.yml` | New — global + per-type acceptance gates |
| `examples/prompts/codebase_build_project.txt` | New — fixture prompt |
| `examples/prompts/longform_text_project.txt` | New — fixture prompt |
| `examples/prompts/video_generation_project.txt` | New — fixture prompt |
| `examples/prompts/research_archive_project.txt` | New — fixture prompt |
| `examples/prompts/document_knowledgebase_project.txt` | New — fixture prompt |
| `examples/prompts/local_automation_project.txt` | New — fixture prompt |
| `tests/test_m1_mission_compiler_v2.py` | New — 84 tests covering all classifiers, builders, CLI, and fixtures |

## New Runtime Modules

| Module | Purpose |
|--------|---------|
| `agent_runtime/brain/` | M1-2 Mission Compiler v2 package |
| `mission_contract.py` | Top-level prompt → mission_contract.yml compiler |
| `domain_classifier.py` | Keyword-based detection of coding/creative/video/research/document/audio/multimodal/local_ops domains |
| `project_type_classifier.py` | Maps domain + prompt → canonical project type (8 types) |
| `capability_requirement_builder.py` | Builds required/optional capability lists per project type |
| `artifact_contract_builder.py` | Builds expected artifacts per phase per project type |
| `acceptance_gate_builder.py` | Merges global gates with project-type-specific gates |
| `risk_classifier.py` | Detects risk flags from typedef + non-goal/constraint patterns in prompt |
| `decision_card_builder.py` | Creates human decision point cards for unknown types, safety concerns, capability gaps, approval points |
| `renderer.py` | Writes mission_contract.yml, intent_summary.md, and supporting YAML files |

## New Configs

| Config | Purpose |
|--------|---------|
| `config/mission_compiler_v2.yml` | Domain/project type keywords, scale heuristics, non-goal/constraint patterns |
| `config/project_type_classifier.yml` | 8 project type definitions with phases, capabilities, risks, approval points |
| `config/project_artifact_contracts.yml` | Per-phase output artifacts with evidence requirements |
| `config/project_acceptance_gates.yml` | 6 global gates + per-project-type gates (44 total gate definitions) |

## New CLI

```bash
# Compile a prompt file into mission contract artifacts
./agentlab.sh mission-compiler compile --prompt-file <path.txt> --out <dir> [--project <name>] [--task-id <id>]

# Help
./agentlab.sh mission-compiler --help
./agentlab.sh mission-compiler compile --help
```

## Artifacts Produced (per compilation)

- `mission_contract.yml` — full mission contract v2 schema
- `intent_summary.md` — human-readable summary
- `required_capabilities.yml` — capability list
- `artifact_contracts.yml` — artifact target summary
- `acceptance_gates.yml` — gate list
- `risk_flags.yml` — risks, non-goals, constraints, unknowns, assumptions
- `decision_cards/` — directory for future per-card files

## Tests Added

84 tests in `tests/test_m1_mission_compiler_v2.py`:

- **TestDomainClassification** (7) — all 6 domains + unknown
- **TestProjectTypeClassification** (6) — all 6 project types
- **TestLongProjectDetection** (7) — long vs not-long for all types
- **TestCapabilityRequirements** (5) — required capabilities per type
- **TestRiskFlags** (5) — risk detection and safety checks
- **TestArtifactTargets** (4) — artifact lists per type
- **TestAcceptanceGates** (3) — global and per-type gates
- **TestDecisionCards** (4) — card generation and uniqueness
- **TestScaleEstimation** (2) — heuristic scale estimation
- **TestHumanApproval** (1) — human_approval always required
- **TestSchemaCompliance** (4) — all 23 required keys present
- **TestRenderer** (3) — output file generation
- **TestExternalExecutor** (3) — executor recommendation per type
- **TestAssetRegistryRecommendation** (2) — asset registry recommendation
- **TestPromptFixtures** (18) — parametrized fixture existence, domain, and project type
- **TestNonGoalDetection** (4) — spam, pirate, impersonate, clean prompts
- **TestDeterminism** (2) — same input → same output
- **TestMissionCompilerCLI** (4) — CLI help, compile, output, error handling

## Tests Run

```
$ python -m pytest -q tests/test_m1_mission_compiler_v2.py
84 passed in 6.37s

$ python -m pytest -q
1293 passed, 2 skipped, 11 warnings in 81.30s

$ python -m compileall agent_runtime
(clean — no errors)

$ python -m compileall agent_runtime/brain/
(clean — all 10 modules compile)

$ ./agentlab.sh mission-compiler --help
(help output confirmed)

$ ./agentlab.sh mission-compiler compile --help
(help output confirmed)
```

## Safety Notes

- No LLM calls. All classification is keyword/pattern-based.
- No external execution. The compiler only reads .txt files and writes YAML/MD.
- No network access.
- No secret exposure. Config files contain no credentials or private paths.
- Non-goal patterns (spam, fake engagement, piracy, impersonation, etc.) are detected and flagged in decision cards.
- Human approval is always required (`human_approval_required: true` by default).
- All external executor recommendations are advisory only; actual executor dispatch requires separate approval.

## Known Limitations

1. Classification is purely keyword-based; nuanced prompts may misclassify. Future M stages could add lightweight LLM-based classification behind approval gates.
2. Domain and project type keywords are English-only.
3. The compiler does not yet integrate with the capability registry to auto-detect backend availability — capability gaps are left empty pending registry connection.
4. Decision cards are listed by ID in the mission contract; per-card YAML files are not yet written (the `decision_cards/` directory is created empty).
5. Scale estimation is heuristic (word count); it does not consider project complexity signals beyond prompt length.

## Next Recommended Stage

**M1-3 Project Workflow Templates v2** — convert mission contracts into project-specific workflow plans with phase definitions, as specified in `docs/AGENTLAB_M_SERIES_MAINLINE_HANDOFF.md` §5.5.
