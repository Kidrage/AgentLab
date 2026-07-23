# S9 Capability Fabric

## Verdict

S9 introduces a deterministic, mock-first capability fabric. It describes what AgentLab may do, how risky each capability is, and whether a backend is available. It does not execute external tools or install models.

## Goals

- Provide a single registry for capability contracts.
- Represent missing multimodal and external backends as explicit capability gaps.
- Require approval for shell, network, write, and other high-risk actions.
- Keep media/document outputs structured and evidence-backed.

## Built-in capabilities

The built-in registry includes:

- filesystem_read
- filesystem_write
- shell_command
- git_ops
- web_search
- browser_fetch
- pdf_read
- docx_read
- spreadsheet_read
- image_understanding
- ocr
- video_understanding
- audio_transcription
- audio_analysis
- database_query
- github_ops
- ide_handoff
- openclaw_notify

## Runtime modules

- agent_runtime/capabilities/capability_contract.py defines immutable capability records.
- agent_runtime/capabilities/registry.py provides deterministic built-in registry loading.
- agent_runtime/capabilities/permission_gate.py blocks disabled, missing, and approval-required capabilities.
- agent_runtime/capabilities/gap_card.py writes capability_gap_decision_card.yml.
- agent_runtime/capabilities/result_verifier.py validates confidence and evidence metadata.

## Runtime authority

- `agent_runtime/capabilities/registry.py` owns the deterministic built-in registry.
- `agent_runtime/capabilities/permission_gate.py` enforces disabled, unavailable,
  and approval-required capability decisions.
- Media contract CLI commands require an explicit `--mock` flag.
- The original unwired S9 YAML sketches are preserved under
  `docs/archive/config_specs_legacy_20260718/` and are not runtime policy.

## CLI

- ./agentlab.sh capability-list
- ./agentlab.sh capability-check --capability image_understanding --out /tmp/capability_demo
- ./agentlab.sh capability-gap --capability image_understanding --out /tmp/capability_demo
- ./agentlab.sh vision-contract --input artifact.png --out /tmp/vision_demo --mock
- ./agentlab.sh audio-contract --input artifact.wav --out /tmp/audio_demo --mock
- ./agentlab.sh document-contract --input artifact.pdf --out /tmp/document_demo --mock

## Safety invariants

- Missing backends produce gap cards, not fabricated results.
- Mock contract commands require --mock.
- Shell, network, and write capabilities are not selected by default.
- No secrets or private credentials are embedded in the registry or policies.
