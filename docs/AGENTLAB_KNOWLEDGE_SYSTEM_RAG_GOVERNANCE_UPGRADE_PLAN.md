# AgentLab Knowledge System & RAG Governance Upgrade Plan

## Status

Operational foundation active — governed assist is the normal task default;
role-specific consumers remain staged

The local-first implementation lives entirely in AgentLab under
`agent_runtime/knowledge_system/`, `agent_runtime/cli/knowledge.py`,
`config/knowledge_system.yml`, and `.agentlab_runtime/knowledge/`. System,
domain, and project spaces are automatically discovered and built for the
configured production allowlist with `./agentlab.sh knowledge build --all-projects`;
`config/knowledge_system.yml#indexing.project_allowlist` is the sole project-set
authority. This command purges excluded records from shared domains and retires
empty derived shards without deleting project sources. Tasks and promotion
receipts outside the allowlist cannot reintroduce project memory. Every task may
read system and project-neutral domain evidence; project/domain records are
filtered to the requesting project even when several allowlisted projects share
one domain shard. Large media is indexed as metadata only. Keyword retrieval uses SQLite FTS5 with the existing BM25 engine
as an explicit degraded fallback. Semantic and graph channels remain optional
adapters and fail visibly when requested but not configured.

Rollout is receipt-backed and sequential: `off → shadow → assist → enforce`.
AgentLab has validated every stage, including fail-closed enforcement, and then
returned to `assist` as the production default so task preparation receives
governed evidence without being blocked by a sparse query. Evidence is persisted
in task context artifacts; each live role still requires an explicit bounded
consumer adapter before the evidence may enter its model prompt. `enforce` remains available
after a successful `assist` validation. Existing acceptance, promotion,
production, and Project Brain authorities remain unchanged; automatic memory
updates stay `propose_only`. Successful general artifact promotions, formal
narrative edition promotions, and accepted Project Brain phase/revision transitions
now issue derived-index sync receipts and refresh both project and domain shards
automatically. Only artifact-index-selected current Production/release objects
and governed Project Brain/config sources are retrieval-eligible. Legacy imports
cannot assign canonical or accepted authority. Superseded source hashes are
tombstoned, and a stale shard is skipped until a successful refresh; index failure
never rolls back authoritative files. AgentLab repository changes are folded back into the global scaffold with
`knowledge build --project AgentLab` at handoff.

Current ingestion boundaries are deliberate:

- Repository upgrades are indexed as the current governed source tree after a
  rebuild. Git owns immutable patch history; superseded source hashes are
  tombstoned instead of remaining parallel active truths.
- Project changes enter retrieval only after an accepted promotion updates the
  current artifact index or Project Truth. Drafts, attempts, archives, and
  unaccepted Agent outputs do not become memory merely because a file exists.
- Source collection is rooted inside AgentLab and `projects/`; arbitrary
  external directories and escaping symlinks are rejected. Supporting an
  external workspace requires a future explicit read-only root registry,
  namespace, content-hash manifest, and refresh receipt.
- The URL reader can extract a caller-supplied public HTTP(S) page under network
  policy. It does not perform Web search or recursive crawling, and fetched
  evidence requires citation review and governed promotion before RAG sync.

Operational commands:

- `./agentlab.sh knowledge build --all-projects`
- `./agentlab.sh knowledge status`
- `./agentlab.sh knowledge search --project ... --task-id ... --domain ... --query ...`
- `./agentlab.sh knowledge validate --project ... --task-id ... --domain ... --request ...`
- `./agentlab.sh knowledge activate --mode ... --actor ... --reason ...`
- `./agentlab.sh knowledge doctor`

## Objective

Upgrade AgentLab from a project governance system with static context
injection into a universal AI production knowledge operating system.

The upgraded system must support:

-   code engineering tasks
-   long-form narrative generation
-   image/video generation
-   audio/music production
-   research tasks
-   business automation
-   document workflows
-   multimodal production pipelines

The system must automatically create, maintain, retrieve, audit, and
retire knowledge spaces without requiring users to manually define
database structures.

------------------------------------------------------------------------

# 1. Core Design Principle

RAG is not the source of truth.

RAG provides evidence discovery.

Project Brain provides authoritative state.

Artifact Governance controls lifecycle.

The architecture should be:

Task → Knowledge Requirement Analysis → Retrieval → Evidence Bundle →
Agent Reasoning → State Transition Proposal → Governed Promotion →
Project Brain Update

------------------------------------------------------------------------

# 2. Knowledge Architecture

AgentLab should use a federated knowledge architecture.

Not one global mixed vector database.

Not one isolated database per task.

Architecture:

-   System Knowledge Space
-   Domain Knowledge Spaces
-   Project Knowledge Spaces
-   Task Retrieval Views

------------------------------------------------------------------------

# 3. Knowledge Namespace

## System Knowledge

Contains:

-   AgentLab source code
-   architecture documents
-   skills
-   routing policies
-   acceptance rules
-   historical failures
-   recovery solutions

Namespace:

system.agentlab

## Domain Knowledge

Examples:

-   code_engineering
-   longform_narrative
-   audio_engineering
-   video_generation
-   research
-   business_automation

## Project Knowledge

Every large project automatically receives a persistent knowledge space.

Examples:

-   project.AgentLab
-   project.Crown_of_Ash
-   project.audio_spatializer

## Task Retrieval View

Temporary retrieval scope generated automatically for execution.

------------------------------------------------------------------------

# 4. Automatic Knowledge Creation

Users should never manually design knowledge bases.

Flow:

User Request

↓

Task Classification

↓

Knowledge Requirement Analysis

↓

Create or Attach Knowledge Space

↓

Build Retrieval View

------------------------------------------------------------------------

# 5. Multimodal Knowledge Model

All knowledge objects require:

-   id
-   namespace
-   project_id
-   source
-   content
-   metadata
-   authority_level
-   lifecycle
-   version
-   relations

Knowledge types:

-   text
-   code
-   narrative
-   audio
-   image
-   video
-   research

------------------------------------------------------------------------

# 6. Domain Retrieval Profiles

Different tasks require different retrieval systems.

## Code

Use:

-   AST index
-   symbol index
-   dependency graph
-   call graph
-   git history
-   semantic search

## Narrative

Use:

-   character graph
-   relationship graph
-   timeline graph
-   foreshadowing graph
-   world rule graph

## Media

Use:

-   asset metadata
-   generation lineage
-   visual/audio similarity
-   parameter history

------------------------------------------------------------------------

# 7. Hybrid Retrieval Engine

Pipeline:

Query Understanding

↓

Metadata Filter

↓

Keyword Retrieval

↓

Semantic Retrieval

↓

Graph Retrieval

↓

Reranking

↓

Evidence Package

↓

Agent Context

------------------------------------------------------------------------

# 8. Large Task Automatic Memory Loop

Large tasks automatically enable:

-   knowledge extraction
-   incremental indexing
-   retrieval planning
-   memory update

Example:

Long novel:

chapter generation

↓

extract entities/events

↓

update knowledge graph

↓

audit retrieval

↓

continue generation

No manual maintenance.

------------------------------------------------------------------------

# 9. Evidence Governance

Every important AI conclusion requires evidence.

Findings must include:

-   claim
-   source
-   evidence location
-   confidence
-   retrieval trace

No evidence:

status cannot be PASS.

Use:

INSUFFICIENT_EVIDENCE

------------------------------------------------------------------------

# 10. Knowledge Lifecycle

Knowledge authority levels:

-   canonical
-   accepted
-   candidate
-   audit
-   external
-   deprecated

Rules:

Candidate cannot overwrite canonical.

Audit cannot become fact.

External references cannot become project truth.

------------------------------------------------------------------------

# 11. Implementation Roadmap

## Phase 1

Knowledge foundation:

-   schemas
-   namespace
-   metadata
-   lifecycle rules

## Phase 2

Automatic ingestion:

-   repository ingestion
-   document ingestion
-   media ingestion
-   narrative extraction

## Phase 3

Hybrid retrieval:

-   keyword
-   embedding
-   metadata filtering
-   evidence bundles

## Phase 4

Domain retrievers:

-   Code Retriever
-   Narrative Retriever
-   Media Retriever
-   Research Retriever

## Phase 5

Knowledge governance:

-   conflict detection
-   stale knowledge detection
-   promotion rules
-   retrieval audit

------------------------------------------------------------------------

# Final Goal

AgentLab evolves from:

AI agent orchestration system

into:

A self-organizing AI production operating system with automatic
knowledge formation, retrieval, governance, and long-term project
memory.

The user provides objectives.

AgentLab determines:

-   required knowledge
-   knowledge location
-   retrieval strategy
-   agent context
-   permanent state updates

No manual knowledge-base engineering should be required.
