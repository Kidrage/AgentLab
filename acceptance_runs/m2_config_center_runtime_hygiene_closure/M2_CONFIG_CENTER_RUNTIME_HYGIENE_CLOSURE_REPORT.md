# AgentLab M2 Config Center + Runtime Hygiene Closure Report

## Verdict
PASS

## Baseline
- **branch:** main
- **before commit:** fead384ac62e2975be543dbeea8558d9a779a2c9
- **final commit:** d5d40a54ec80955085d37f71ed10ba87bf82c33d
- **origin/main:** d5d40a54ec80955085d37f71ed10ba87bf82c33d
- **CI run URL:** https://github.com/Kidrage/AgentLab/actions
- **CI conclusion:** pending / not yet confirmed (push succeeded, local validation fully green)
- **remote:** origin → `git@github.com:Kidrage/AgentLab.git`, relay → `ssh://admin@10.147.17.250:/home/admin/AgentLab`

## Summary
This round closes the remaining evidence/config drift gaps found after `fead384`. Specifically, it repairs stale config profile keys, adds robust profile validation and overlay tests, and ensures all runtime hygiene verification scripts pass cleanly.

## Fixed Since fead384
- **acceptance report final commit updated**: Updated this report to record the final HEAD SHA and remote main commit.
- **config_profiles stale keys repaired**: Replaced `routing_policy.default_mode` with `routing_policy.default_budget` and `model_profiles.default_budget_mode` with `agent_model_profiles.default_budget_mode` in all active profile overlays. Removed `execution_policy.require_explicit_execute`.
- **profile activation / overlay validation tests added**: Created `tests/test_m2_config_center_profiles.py` covering dev, prod, frugal, max_quality, spelling typos, and unknown keys.
- **runtime hygiene remained closed**: Confirmed scripts first lines, forbidden tracked files, and text integrity pass completely.
- **text integrity remained clean**: No absolute path leaks or issues.

## Config Profile Closure
Validated the following profiles against the schema:
- **dev**: PASS (resolved default budget: balanced)
- **prod**: PASS (resolved default budget: balanced)
- **frugal**: PASS (resolved default budget: frugal, confirmed spelling)
- **max_quality**: PASS (resolved default budget: max_quality)

## Tests Added / Updated
- `tests/test_m2_config_center_profiles.py` (New):
  - `test_config_profiles_use_current_schema_keys`
  - `test_config_profile_dev_validates`
  - `test_config_profile_prod_validates`
  - `test_config_profile_frugal_validates`
  - `test_config_profile_max_quality_validates`
  - `test_legacy_default_mode_is_not_used_in_committed_profiles`
  - `test_legacy_furgal_not_used_in_committed_profiles`
  - `test_profile_overlay_unknown_key_fails_or_warns`
- `tests/test_m2_config_resolution.py` (Updated):
  - `test_dev_profile_makes_permissive` (asserts `default_budget` is `balanced`)

## Tests Run

### compileall
```bash
$ python -m compileall agent_runtime agentlab_app.py
```
**PASS** — All Python files compile without errors.

### pytest (full suite)
```bash
$ python -m pytest -q
```
**RESULT:** 1605 passed, 2 skipped, 11 warnings in 157.45s.

### Text integrity
```bash
$ python scripts/audit_text_integrity.py
```
**PASS** — Scanned 963 files, 0 suspicious files.

### Forbidden files tracked
```bash
$ python scripts/check_forbidden_tracked_files.py
```
**PASS** — No forbidden files tracked.

### Config CLI checks
```bash
$ ./agentlab.sh --help                                                   # PASS
$ ./agentlab.sh run-pipeline --help                                      # PASS
$ ./agentlab.sh config --help                                            # PASS
$ ./agentlab.sh config config-validate                                   # PASS (exit 0)
$ ./agentlab.sh config config-list --limit 20                            # PASS
$ ./agentlab.sh config config-get --key routing_policy.default_budget    # PASS (balanced)
$ ./agentlab.sh config config-get --key agent_model_profiles.default_budget_mode # PASS (balanced)
```

## Safety Notes
Confirmed:
- ✅ No new feature stage introduced
- ✅ No WebUI/TUI added
- ✅ No external executor dispatch added
- ✅ No network crawling or execution
- ✅ No real secrets printed or tracked
- ✅ No `.env` files tracked
- ✅ No private user paths introduced
- ✅ No acceptance_runs global path exemption

## Final Acceptance Notes
This closes M2-5 Config Center + Runtime Hygiene only.
Do not start M2-6/M3 in this patch.
