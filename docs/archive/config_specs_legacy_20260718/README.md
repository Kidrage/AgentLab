# Legacy Unwired Config Specs

These YAML files were moved out of `config/` during the 2026-07-18 pruning pass.
At that point, no AgentLab loader or runtime source referenced their filenames.
Some adjacent capabilities still exist, but their behavior is implemented in
code or another policy file rather than governed by these documents.

They are historical design inputs, not runtime authority. Do not restore a file
to `config/` until a runtime owner loads it and a test proves that changing the
policy changes behavior.

Archived groups include early ingestion, local/web intelligence, program
manager, phase acceptance, reviewer/router feedback, skill discovery, MCP
permission, language, task compaction, and the unwired S9 capability/media
policy sketches.
