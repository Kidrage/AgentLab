# Legacy Active-Skill Usage Ledgers

These files preserve the final snapshots of the mutable ledgers that AgentLab
previously kept inside `skills/active/<skill_id>/`.

They are historical evidence only. AgentLab does not read or append them.
Starting with `config/skill_injection_policy.yml` schema 2, skill packages are
immutable after promotion and each task writes usage evidence to its own
`run_dir/skill_usage.yml`, governed by `config/run_retention_policy.yml`.
