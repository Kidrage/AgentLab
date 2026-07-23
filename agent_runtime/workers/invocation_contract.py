"""Data structure and loader for worker command invocation contracts."""

import yaml
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Any

@dataclass
class ExpectedParse:
    argv_prefix: list[str] = field(default_factory=list)
    must_contain: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)

@dataclass
class ContractValidation:
    shlex_parse_required: bool = True
    require_existing_binary: bool = False
    allow_shell: bool = False
    allow_unquoted_placeholders: bool = False

@dataclass
class ContractErrorClassification:
    invalid_exit_codes: list[int] = field(default_factory=list)
    invalid_invocation_patterns: list[str] = field(default_factory=list)
    auth_required_patterns: list[str] = field(default_factory=list)
    rate_limit_patterns: list[str] = field(default_factory=list)
    network_failure_patterns: list[str] = field(default_factory=list)
    permission_denied_patterns: list[str] = field(default_factory=list)

@dataclass
class ContractFallback:
    on_binary_missing: str = "stop_and_report"
    on_invalid_invocation: str = "stop_and_report"
    on_auth_required: str = "blocked_user_setup"
    on_network_required: str = "offline_or_retry_later"
    on_permission_denied: str = "approval_required"

@dataclass
class WorkerInvocationContract:
    worker_id: str
    display_name: str
    command: str
    invocation_style: str  # one_shot_prompt | chat_query | task_file | stdin | custom | deterministic_tool
    template: str
    required_placeholders: list[str] = field(default_factory=list)
    optional_placeholders: list[str] = field(default_factory=list)
    safe_probe: list[str] = field(default_factory=list)
    expected_parse: ExpectedParse = field(default_factory=ExpectedParse)
    validation: ContractValidation = field(default_factory=ContractValidation)
    error_classification: ContractErrorClassification = field(default_factory=ContractErrorClassification)
    fallback: ContractFallback = field(default_factory=ContractFallback)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerInvocationContract":
        # Handle sub-dataclasses manually
        exp_data = data.get("expected_parse") or {}
        expected_parse = ExpectedParse(
            argv_prefix=exp_data.get("argv_prefix") or [],
            must_contain=exp_data.get("must_contain") or [],
            must_not_contain=exp_data.get("must_not_contain") or []
        )
        
        val_data = data.get("validation") or {}
        validation = ContractValidation(
            shlex_parse_required=val_data.get("shlex_parse_required", True),
            require_existing_binary=val_data.get("require_existing_binary", False),
            allow_shell=val_data.get("allow_shell", False),
            allow_unquoted_placeholders=val_data.get("allow_unquoted_placeholders", False)
        )
        
        err_data = data.get("error_classification") or {}
        error_classification = ContractErrorClassification(
            invalid_exit_codes=err_data.get("invalid_exit_codes") or [],
            invalid_invocation_patterns=err_data.get("invalid_invocation_patterns") or [],
            auth_required_patterns=err_data.get("auth_required_patterns") or [],
            rate_limit_patterns=err_data.get("rate_limit_patterns") or [],
            network_failure_patterns=err_data.get("network_failure_patterns") or [],
            permission_denied_patterns=err_data.get("permission_denied_patterns") or []
        )
        
        fb_data = data.get("fallback") or {}
        fallback = ContractFallback(
            on_binary_missing=fb_data.get("on_binary_missing", "stop_and_report"),
            on_invalid_invocation=fb_data.get("on_invalid_invocation", "stop_and_report"),
            on_auth_required=fb_data.get("on_auth_required", "blocked_user_setup"),
            on_network_required=fb_data.get("on_network_required", "offline_or_retry_later"),
            on_permission_denied=fb_data.get("on_permission_denied", "approval_required")
        )
        
        return cls(
            worker_id=data["worker_id"],
            display_name=data["display_name"],
            command=data["command"],
            invocation_style=data["invocation_style"],
            template=data["template"],
            required_placeholders=data.get("required_placeholders") or [],
            optional_placeholders=data.get("optional_placeholders") or [],
            safe_probe=data.get("safe_probe") or [],
            expected_parse=expected_parse,
            validation=validation,
            error_classification=error_classification,
            fallback=fallback
        )

def load_contracts(config_path: Path) -> dict[str, WorkerInvocationContract]:
    """Load invocation contracts from a YAML configuration file."""
    if not config_path.exists():
        return {}
    try:
        content = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not data or "contracts" not in data:
            return {}
        contracts = {}
        for w_id, w_data in data["contracts"].items():
            contracts[w_id] = WorkerInvocationContract.from_dict(w_data)
        return contracts
    except Exception:
        return {}
