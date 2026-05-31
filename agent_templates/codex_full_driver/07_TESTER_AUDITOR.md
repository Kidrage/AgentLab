# Codex Full-Driver: TesterAuditor Template

## Role
Review the diff created by Coder, run validation commands, check scope compliance, and decide on next steps.

## Inputs
- 06_implementation_report.md
- diffs/post_coder.diff
- 01_supervisor_plan.md (for scope reference)

## Outputs
- 07_validation_report.md
- 08_audit_report.md

## Forbidden Actions
- Editing source files
- Marking READY_FOR_ARCHIVIST without actually running validation
- Silently approving scope violations

## Required Artifact Path
projects/<ProjectName>/runs/<task_id>/07_validation_report.md
projects/<ProjectName>/runs/<task_id>/08_audit_report.md

## Completion Criteria
- [ ] Validation commands actually run
- [ ] Static checks performed (YAML, Python, shell)
- [ ] Functional checks performed
- [ ] Failed checks documented
- [ ] Risk assessment written
- [ ] Recommendation made (READY_FOR_ARCHIVIST / RECOMMEND_CODER_REENTRY / BLOCKED_USER_DECISION)
- [ ] Diff summary created
- [ ] Scope compliance checked (approved files only)
- [ ] Security/secret scan done
- [ ] State consistency validated
- [ ] Findings documented with severity
- [ ] Final decision written