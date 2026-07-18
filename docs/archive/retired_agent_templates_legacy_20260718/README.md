# Retired Agent Templates

These templates had no active role registration on 2026-07-18:

- `doc_manager.md`: superseded by deterministic task purge/document generation
  and the registered Archivist role.
- `skill_distiller.md`: superseded by the deterministic `skill_distiller.py`
  lifecycle and skill review/promotion policy.

They remain historical reference only. Active prompt files must be declared as
`template_path` or `template_variants` in `config/agent_registry.yml`; the test
suite rejects unregistered files in `agent_templates/`.
