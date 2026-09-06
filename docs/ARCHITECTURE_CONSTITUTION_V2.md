# AgentLab Architecture Constitution v2

## Product position

AgentLab is a local-first **agentic production operating system**. Its near-term job is to produce reliable, repeatable, continuously maintainable digital products with observable cost, state, evidence, review, recovery, and release history.

It is not a chatbot, an LLM wrapper, a single Agent, or an Agent swarm. Models and CLI tools are replaceable execution resources. Agents are governed workers inside a durable production system.

## The two authorities

AgentLab may have only two durable semantic authorities:

1. **Task Runtime — Execution Truth**
   - answers what work is being done, by whom, in what state, with which attempts, artifacts, evidence, and failures;
   - canonical authority is the Runtime v2 event ledger for each Task.

2. **Project Truth — Product Truth**
   - answers what the project currently accepts as true and releasable;
   - canonical authority is the current immutable project snapshot selected by `project_truth.yml` in enforced mode.

No third subsystem may become another current-state authority.

## Derived layers

The following are views, caches, adapters, evidence, or execution resources — never independent truth:

- Web UI, TUI, desktop app, MCP/API surfaces;
- `production/` filesystem projections and artifact indexes;
- Knowledge/RAG indexes;
- handoff documents;
- acceptance reports;
- daemon/watchdog state;
- Agent prompts and worker sessions;
- model/provider availability observations;
- legacy `runs/` after Runtime v2 migration.

A derived layer may be rebuilt or replaced without changing accepted Task or Project truth.

## Control-surface rule

Every mutation from Web UI, TUI, CLI, MCP, desktop, or external Agent must enter the same governed command boundary.

A control surface must not directly edit task state YAML, projection files, Project Truth projections, or generated indexes.

Reads must prefer the canonical authority and may expose legacy state only as explicitly labelled compatibility data.

## Runtime v2 precedence

If a Task Runtime v2 identity exists, it is authoritative even if its ledger is damaged. A damaged v2 Task fails closed; the system must never fall back to writing a same-named legacy run.

Legacy `projects/<Project>/runs/` is a migration/compatibility source. New product capability must not be added to the legacy path.

## Promotion bridge

The only semantic bridge from execution to accepted product state is an explicit, idempotent promotion transaction:

```text
Task Runtime candidate + evidence
        -> PromotionRequest
        -> ProjectTruth.commit(ChangeSet)
        -> canonical snapshot id
        -> promotion receipt recorded back in Task Runtime
```

Worker success alone never means product promotion.

## Agent model

Keep these concepts separate:

```text
Model   = intelligence resource
Worker  = executable shell/tool surface
Role    = stable responsibility contract
Agent   = role + context + permissions + tools + model profile + acceptance rules
Skill   = reusable professional procedure/capability
Team    = governed collaboration graph of Agents
```

AgentLab owns orchestration, state, evidence, permissions, and promotion. Workers do not become workflow hosts merely because they can spawn subagents.

## Configuration rule

Authoring configuration may remain split by concern, but a prepared Task should execute against one immutable compiled runtime manifest/hash. Generated manifests are rebuildable products of canonical configuration, never additional hand-maintained authorities.

## Repository/runtime boundary

AgentLab source code and live customer/project runtime data must move toward physically separate roots. Repository `projects/` should ultimately contain only examples, fixtures, schemas, and ignored local development state.

## Refactoring rule

Prefer deleting or demoting a control plane over introducing another one. Preserve stable public facades while splitting oversized implementations internally.

Before adding a new persistent state file, registry, ledger, or lifecycle, answer:

> Is this execution truth, or product truth?

If neither, it must not become a new authority.

## Current consolidation order

1. Make Runtime v2 authoritative at every task control surface.
2. Stop creating new legacy tasks/runs.
3. Move legacy reads behind explicit compatibility adapters.
4. Unify Command/Query application boundaries for UI, CLI, TUI, MCP, and desktop.
5. Split oversized Runtime/Runner implementations without changing public behavior.
6. Compile per-Task immutable runtime manifests from canonical configuration.
7. Physically separate live project/runtime data from the AgentLab source checkout.
8. Only after kernel stability, resume new Agent/self-evolution/product-pack expansion.
