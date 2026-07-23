# AgentLab Domain Glossary

## AgentLab Role

A stable responsibility contract such as Supervisor, Writer, Coder, Reviewer,
or Verifier. A role owns declared inputs and outputs; it is not a model or CLI.

## Worker Shell

A registered local execution surface such as Hermes or Claude Code. A shell may
use native tools/subagents inside one assigned role, then returns an AgentLab
receipt.

## Local CLI Home

A worker's credentials, sessions, cache, and private runtime state. CLI homes are
local-only and excluded from repository ingestion, Git, handoff bundles, and
relay synchronization.

## Workflow Driver

The AgentLab-level execution mode that advances a task. It is distinct from the
worker selected for any role.

## Route

The smallest ordered set of roles needed for a request. Route authority is
`config/routing_rules.yml`.

## Production Pack

A domain contract defining lifecycle nodes, outputs, memory records, and quality
gates. It does not select models.

## Task Run

The recoverable state boundary at `projects/<Project>/runs/<task_id>/`, including
plan, state, lifecycle, events, decisions, reports, and candidate artifacts.

## Candidate Artifact

A task-local deliverable awaiting required checks and approval. It is not a
formal project fact or production deliverable.

## Production Artifact

A promoted current deliverable under `projects/<Project>/production/`, selected
by the project artifact index where applicable.

## Receipt

Machine-readable evidence that a role, command, generation, review, or promotion
actually ran with the declared boundary and result.

## Decision Card

A durable approval-policy outcome or recovery choice. It may record a scoped
automatic grant, a pending human decision, or a forbidden action. Only pending
human decisions block until resolved through a governed control surface.

## Policy Approval Grant

A time-limited authorization issued by a named approval policy for one exact
request scope. The grant records policy and scope hashes and becomes invalid if
the policy, requested action, files, capabilities, or expiry changes.

## Capacity Route

A declared same-role worker/model fallback triggered by observed capacity or
availability evidence. Silent fallback is not a capacity route.

## Structured Project Memory

Versioned facts, indexes, ledgers, and state proposals used as authority for
long-running work. Retrieval can supply evidence but does not become the fact
source by itself.

## Self-Evolution Proposal

A candidate AgentLab component change backed by a repeatable capability gap,
ownership, contracts, tests, and rollback. It requires validation and approval
before activation.

The superseded topology-oriented glossary is archived at
`docs/archive/root_agent_guides_legacy_20260718/CONTEXT.md`.
