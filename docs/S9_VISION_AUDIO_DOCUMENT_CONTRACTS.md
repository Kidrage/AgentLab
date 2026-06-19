# S9 Vision, Audio, and Document Contracts

## Purpose

S9 adds structured artifact contracts for perception-style outputs while preserving AgentLab's local-first safety model. These contracts are mock-first and do not run real image, audio, video, OCR, or document-processing backends unless a future reviewed backend is explicitly configured.

## Vision contract

vision_result.yml contains:

- input_artifact
- modality
- observations
- summary
- evidence_artifacts
- model_or_tool
- confidence
- risk

The CLI command is:

```bash
./agentlab.sh vision-contract --input artifact.png --out /tmp/vision_demo --mock
```

Without --mock, the command fails instead of fabricating perception output.

## Audio contract

audio_result.yml contains:

- input_artifact
- duration
- observations
- transcript
- features
- summary
- evidence_artifacts
- model_or_tool
- confidence
- risk

The CLI command is:

```bash
./agentlab.sh audio-contract --input artifact.wav --out /tmp/audio_demo --mock
```

## Document contract

document_result.yml contains:

- input_artifact
- pages
- extracted_text
- tables
- figures
- citations
- evidence_artifacts
- model_or_tool
- confidence
- risk

The CLI command is:

```bash
./agentlab.sh document-contract --input artifact.pdf --out /tmp/document_demo --mock
```

## Validation rules

- confidence is required.
- evidence_artifacts is required.
- multimodal and extraction outputs emit human_review_required risk.
- missing backends emit capability_gap_decision_card.yml instead of result files.
