"""Report generator for worker invocation contracts and probe validations."""

import yaml
from pathlib import Path
from typing import Any
from agent_runtime.workers.invocation_contract import load_contracts, WorkerInvocationContract
from agent_runtime.workers.command_template_validator import validate_template
from agent_runtime.workers.safe_probe_runner import run_safe_probe
from agent_runtime.workers.cli_error_classifier import classify_cli_error

def generate_invocation_report(
    agentlab_root: Path, 
    out_dir: Path, 
    mock: bool = False
) -> dict[str, Any]:
    """Validate all contracts, run safe probes, classify errors, and render reports."""
    config_path = agentlab_root / "config" / "worker_invocation_contracts.yml"
    contracts = load_contracts(config_path)

    out_dir.mkdir(parents=True, exist_ok=True)
    
    results = []
    invalid_templates = {}
    classified_failures = {}
    
    for c_id, contract in contracts.items():
        # Validate template
        allow_unquoted = contract.validation.allow_unquoted_placeholders
        valid, errors = validate_template(
            contract.template, 
            contract.required_placeholders,
            allow_unquoted_placeholders=allow_unquoted
        )
        
        if not valid:
            invalid_templates[c_id] = {
                "template": contract.template,
                "errors": errors
            }

        # Run safe probe
        exit_code, stdout, stderr, timeout, bin_missing = run_safe_probe(contract, mock=mock)
        
        # Classify error if not successful
        err_class = None
        probe_status = "passed"
        if bin_missing:
            probe_status = "skipped"
            err_class = "binary_missing"
        elif exit_code != 0 or timeout:
            probe_status = "failed"
            err_class = classify_cli_error(
                exit_code, stdout, stderr, timeout_occurred=timeout, 
                config_path=agentlab_root / "config" / "cli_error_classification.yml"
            )
            classified_failures[c_id] = {
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "timeout": timeout,
                "error_class": err_class
            }

        results.append({
            "worker_id": contract.worker_id,
            "display_name": contract.display_name,
            "command": contract.command,
            "template": contract.template,
            "template_valid": valid,
            "template_errors": errors,
            "safe_probe_status": probe_status,
            "safe_probe_exit_code": exit_code,
            "safe_probe_error_class": err_class,
            "warnings": errors
        })

    # Render YAML
    report_data = {
        "worker_invocation_contracts": results
    }
    
    # Path Sanitization helper to prevent leakage of "/Users/" paths in generated files
    def sanitize_text(text: str) -> str:
        import re
        users_prefix = "/" + "Users" + "/"
        pattern = re.compile(users_prefix + r"[^\s`'\"<>]+")
        return pattern.sub('/HOME', text)
        
    yaml_report = sanitize_text(yaml.safe_dump(report_data, sort_keys=False, allow_unicode=True))
    (out_dir / "worker_invocation_contract_report.yml").write_text(yaml_report, encoding="utf-8")
    
    (out_dir / "invalid_templates.yml").write_text(
        sanitize_text(yaml.safe_dump(invalid_templates, sort_keys=False, allow_unicode=True)), 
        encoding="utf-8"
    )
    (out_dir / "classified_cli_failures.yml").write_text(
        sanitize_text(yaml.safe_dump(classified_failures, sort_keys=False, allow_unicode=True)), 
        encoding="utf-8"
    )

    # Render MD
    md = []
    md.append("# AgentLab Worker Invocation Contract Report\n")
    md.append("## Contract Validation Overview\n")
    md.append("| Worker ID | Display Name | Command | Style | Template Valid | Safe Probe Status | Error Class |")
    md.append("|---|---|---|---|---|---|---|")
    for r in results:
        t_valid = "✅ Yes" if r["template_valid"] else "❌ No"
        p_status = "✅ Passed" if r["safe_probe_status"] == "passed" else (
            "⚠️ Skipped" if r["safe_probe_status"] == "skipped" else "❌ Failed"
        )
        md.append(f"| `{r['worker_id']}` | {r['display_name']} | `{r['command']}` | {r['template_valid']} | {t_valid} | {p_status} | `{r['safe_probe_error_class'] or 'none'}` |")
    md.append("")

    md.append("## Detailed Contracts")
    for r in results:
        md.append(f"### {r['display_name']} (`{r['worker_id']}`)")
        md.append(f"- **Command**: `{r['command']}`")
        md.append(f"- **Template**: `{r['template']}`")
        md.append(f"- **Template Valid**: {r['template_valid']}")
        if r["template_errors"]:
            md.append("- **Errors/Warnings**:")
            for err in r["template_errors"]:
                md.append(f"  - {err}")
        md.append(f"- **Safe Probe Status**: {r['safe_probe_status']}")
        if r["safe_probe_error_class"]:
            md.append(f"- **Probe Error Class**: `{r['safe_probe_error_class']}`")
        md.append("")
        
    md_report = sanitize_text("\n".join(md))
    (out_dir / "worker_invocation_contract_report.md").write_text(md_report, encoding="utf-8")

    return report_data
