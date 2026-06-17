# Skill Discovery v1

Deterministic skill discovery candidate flow for AgentLab. This module scans
local project sources and produces **candidate** skill dicts only. It never
installs, enables, executes, or copies source code from any external source.

## Overview

Skill Discovery v1 is a read-only, metadata-only pipeline that identifies
potential skills from patterns already present in a project. Every candidate
is emitted disabled and requires human review before it can be promoted to an
active skill.

### Design Principles

- **Candidates only** — discovery never installs or enables anything.
- **No network access** — all scanning is local filesystem only.
- **No source code copying** — external-derived candidates record evidence
  (path, hash, source category) but never duplicate source.
- **Deterministic** — identical project state produces identical candidates.
- **Human-first** — every candidate carries `requires_human_review: True`.

## Candidate Schema

Every candidate dict conforms to this schema:

```yaml
candidate_id: "script-my-tool"          # deterministic slug from title
title: "Script: My Tool"                # human-readable title
source_evidence:                         # list of evidence entries
  - path: "scripts/my_tool.py"
    source_category: "scripts"
    content_hash: "sha256:abcdef..."
proposed_capabilities:                   # what the skill could do
  - "Run my_tool workflow"
suitable_task_types:                     # task routing hints
  - "automation"
  - "scripting"
proposed_inputs:                         # expected input artifact types
  - "command_line_args"
proposed_outputs:                        # expected output artifact types
  - "text"
  - "report"
risk:
  level: "medium"                        # low | medium | high | critical
  reasons:
    - "Script discovered from local directory; not sandbox-tested."
  requires_approval: true                # always true for candidates
license:
  source: "agentlab_internal"           # license origin
  review_required: false                # whether license review is needed
lifecycle_status: "candidate"           # always "candidate" at discovery
enabled: false                          # always false at discovery
promotion:
  requires_human_review: true           # always true
  requires_tests: true                  # always true
  requires_metadata_completion: true    # always true
```

## Discovery Sources

Four local scanners are supported:

| Scanner                | Directory Scanned       | Trigger Condition                          |
|------------------------|-------------------------|--------------------------------------------|
| `scripts`              | `scripts/`, `agent_templates/` | Python file with docstring + >100 lines |
| `acceptance_reports`   | `acceptance_runs/`      | Repeated report file names across 2+ runs  |
| `recovery_feedback`    | `projects/*/runs/*/recovery/`, `recovery_runs/` | Same failure category in 3+ tasks |
| `docs`                 | `docs/`                 | Markdown with 5+ checklist items           |

Each scanner is independently toggleable via the policy config.

## Heuristics

### Scripts Scanner

A Python script qualifies when:
1. It lives under `scripts/` or `agent_templates/`.
2. It has at least 100 lines.
3. It contains a module-level docstring (first non-blank, non-comment line
   starts with `"""` or `'''`).

### Acceptance Reports Scanner

Scans `acceptance_runs/*/` for files matching `acceptance_report*`. Groups
reports by parent directory. When two or more groups share the same file
names, a candidate is emitted.

### Recovery Feedback Scanner

Scans for `closure_quality_feedback.json` files in project run directories.
Tallies `failure_categories` across all files. When a category appears in
three or more tasks, a candidate is emitted.

### Docs Scanner

Scans `docs/*.md` for Markdown files containing checklist markers
(`- [ ]`, `- [x]`, `* [ ]`, `* [x]`). Files with at least 5 checklist
items are considered workflow automation candidates.

## Safety Rules

1. **No execution** — discovery never runs, imports, or evaluates discovered code.
2. **No network** — all scanning is local filesystem only.
3. **No source copying** — evidence records path + hash + category, never content.
4. **Disabled by default** — every candidate has `enabled: False`.
5. **Human review required** — every candidate has `requires_human_review: True`.
6. **No auto-promotion** — candidates stay at `lifecycle_status: "candidate"`
   until explicitly promoted by a human operator.

## Policy Configuration

The discovery policy is loaded from an optional YAML file. Defaults:

```yaml
enabled: false
allow_network: false
auto_import: false
auto_promote: false
max_candidates_per_scan: 50
scanners:
  - scripts
  - acceptance_reports
  - recovery_feedback
  - docs
safety:
  always_require_human_review: true
  never_execute_external_code: true
  never_copy_external_source: true
```

Safety fields (`always_require_human_review`, `never_execute_external_code`,
`never_copy_external_source`) are immutable and cannot be overridden by the
policy file.

## CLI Usage

### Discover candidates

```bash
python -m agent_runtime.skills.discovery --root . --output config/discovery_candidates.yml
```

### Validate candidates

```bash
python -c "
from agent_runtime.skills.discovery_policy import load_discovery_policy, validate_candidate
from agent_runtime.skills.candidate_writer import load_candidates

policy = load_discovery_policy()
candidates = load_candidates('config/discovery_candidates.yml')
for c in candidates:
    errors = validate_candidate(c)
    if errors:
        for e in errors:
            print(f'ERROR: {e}')
    else:
        print(f'OK: {c[\"candidate_id\"]}')
"
```

### Merge new candidates with existing

```bash
python -c "
from agent_runtime.skills.candidate_writer import load_candidates, write_candidates, merge_candidates
from agent_runtime.skills.discovery import discover_candidates
from pathlib import Path

existing = load_candidates(Path('config/discovery_candidates.yml'))
new = discover_candidates(Path('.'))
merged = merge_candidates(existing, new)
write_candidates(merged, Path('config/discovery_candidates.yml'))
print(f'Merged: {len(merged)} candidates ({len(existing)} existing + {len(new)} new)')
"
```

## Module Map

| File | Purpose |
|------|---------|
| `agent_runtime/skills/discovery.py` | Main discovery logic and scanners |
| `agent_runtime/skills/discovery_policy.py` | Policy loading and candidate validation |
| `agent_runtime/skills/candidate_writer.py` | YAML serialisation, loading, and merging |
| `tests/test_r5_skill_discovery.py` | Comprehensive test suite |

## Limitations

- Discovery is heuristic-based and may produce false positives.
- No sandbox execution or runtime validation of candidates.
- No supply-chain scanning or security analysis.
- No integration with external skill registries or marketplaces.
- Quality scores are not computed at discovery time.
