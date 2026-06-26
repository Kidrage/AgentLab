# Routing Intent and Gate Consistency

> How AgentLab classifies task intent and ensures route selection is consistent
> with validation gate requirements.

## Intent Classification

AgentLab classifies every task as either **implementation-required** or
**analysis-only** based on keyword signals in the user prompt.

### Implementation Signals

A task is classified as implementation-required if the prompt contains keywords
like:

| English | Chinese |
|---------|---------|
| implement | 实现 |
| patch | 写补丁 / 应用补丁 |
| modify / edit | 修改 |
| create file | 创建文件 |
| add test(s) | 加测试 / 增加测试 |
| fix | 修复 |
| wire / integrate | 接入 |
| generate code | 生成代码 |
| write module | 写模块 |
| run pytest / make CI pass | 过 CI |
| produce implementation report | 生成实现报告 |

### Explicit Analysis-Only Override

A task remains analysis-only even when implementation keywords are present IF
the prompt contains explicit non-implementation signals:

| English | Chinese |
|---------|---------|
| analysis only | 只分析 |
| planning only | 只规划 |
| do not modify files | 不要改代码 |
| no implementation | 不要落地 / 不实现 |
| design only | 仅分析 / 仅评估 |

### Priority

```
implementation signals > evaluation signals
explicit analysis-only > implementation signals
```

When both implementation and evaluation signals are present, **implementation
wins** unless the user explicitly says "analysis only".

## Route Selection

### Implementation-Required Routes

Always include at least one **implementation executor**:

- `Coder` — primary code-change agent
- `external_ide_ai` — external IDE AI (e.g. Claude Code, Codex)
- `manual_patch_submitter` — human-submitted patches
- `claude_code` — Claude Code CLI

If no implementation executor is available, the task status becomes **blocked**
with reason `implementation_required_but_no_executor`.

### Analysis-Only Routes

Must NOT include Coder or other implementation executors. Expected artifacts:

- `supervisor_plan.md`
- `analysis_report.md`
- `design_report.md`
- `routing_report.md`

## Route/Gate Consistency Invariant

> For every required validation artifact, at least one selected route executor
> must be able to produce it.

The `validate_route_gate_consistency()` function enforces:

1. **`implementation_report` gate requires an implementation executor** in the
   route. If the gate says `owner: Coder` but Coder is skipped, the task is
   invalid.

2. **Artifact ownership**: Each artifact has canonical producers. If none of
   those producers are in the route, the gate cannot be satisfied.

3. **Analysis-only tasks must not require implementation artifacts** like
   `implementation_report.md`, patches, or code diffs.

4. **Implementation-required tasks must have at least one implementation
   executor** in the route.

### Why Coder Cannot Be Skipped If Implementation Report Is Required

The `implementation_report` gate (`config/validation_gates.yml`) has:

```yaml
- id: implementation_report
  owner: Coder
  required: true
```

If the route skips Coder (or has no other implementation executor), there is
**no agent** that can produce this artifact. The task would fail at the
validation gate with no way to proceed.

### How External Implementation Executors Satisfy Gates

Routes can use `external_ide_ai`, `manual_patch_submitter`, or `claude_code`
instead of `Coder`. These are all valid implementation executors. The
consistency check validates that at least one is present.

## Validation

Run the acceptance script:

```bash
python scripts/check_routing_gate_consistency.py
```

This runs deterministic fixtures for:
- analysis-only prompts
- implementation prompts (English + Chinese)
- mixed analysis + implementation prompts
- multimodal implementation prompts
- contradictory route/gate configurations
- no-executor-available scenarios

CI does not require real agent execution — all checks are shape/contract validations.
