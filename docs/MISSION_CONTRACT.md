# Mission Contract Schema Foundation

AgentLab S1 introduces the Mission Contract as the planned entry contract for
the new mainline. The contract captures a user's mission intent before later
compiler stages decide how to route, decompose, validate, or execute work.

## Scope of S1-A

This S1-A foundation defines only:

- the `MissionContract` dataclass schema;
- stable task type enums;
- structured assumptions, risks, capability requirements, artifact contracts,
  acceptance gates, and human approval metadata;
- YAML load/write helpers;
- deterministic dictionary conversion;
- structured validation errors;
- example YAML fixtures and tests.

This is not the full Mission Compiler.

## Non-Goals in This Stage

S1-A deliberately does not implement:

- a Task Compiler;
- a domain classifier;
- an artifact or acceptance builder;
- runtime lifecycle wiring;
- Skill OS;
- Capability Fabric;
- native web intelligence;
- vision, multimodal execution, or audio generation;
- OpenClaw adapters or dashboard features.

## Schema Location

The implementation lives in:

```text
agent_runtime/brain/mission_contract.py
```

The main public helpers are:

```python
load_mission_contract(path)
write_mission_contract(contract, path)
validate_mission_contract(contract)
mission_contract_to_dict(contract)
mission_contract_from_dict(data)
```

## Task Types

Supported `task_type` values are:

```text
coding
debugging
research
business
creative_longform
document_processing
data_analysis
audio_music
multimodal
local_ops
education
unknown
```

Unknown enum values fail validation with a structured `unknown_enum` error.

## Validation Rules

Validation returns a list of structured errors. An empty list means PASS.

Required checks include:

- `schema_version` is present;
- `mission_id` is present;
- `task_type` is one of the supported values or `unknown`;
- `user_goal` is not empty;
- capability entries include `capability` and `reason`;
- artifact entries include `artifact_type`, `name`, and `description`;
- acceptance gates include `gate_id`, `description`, and
  `verification_method`;
- enum-like fields reject unknown values clearly.

Empty optional lists are allowed.

## Examples

Example contracts live in:

```text
examples/mission_contracts/
```

They cover coding, research, creative longform, multimodal image review, and
audio/music planning. These examples are schema fixtures only; they do not imply
that multimodal or audio execution is wired into the runtime.

## Runtime Status

At this stage, Mission Contract is not enforced by `run-pipeline` and is not
connected to the 14-node lifecycle. Future work should require a valid mission
contract before a task enters execution, but S1-A intentionally keeps runtime
behavior unchanged.

## Next Stages

Recommended follow-up work:

- S1-B: Task Compiler MVP;
- S1-C: Domain Classifier;
- S1-D/E: Artifact and acceptance builders;
- later S stages: Skill OS, Capability Fabric, Recovery Brain, and evaluation
  gates.