"""M2-1 Local Worker Registry & CLI Invocation Contract Validator.

Handles discovery of local worker CLIs and validation of command invocation contracts.
"""

from .worker_card import WorkerCard, WorkerCategory
from .detector import scan_workers
from .registry import WorkerRegistry
from .command_probe import probe_command
from .version_probe import probe_version
from .auth_probe import probe_auth
from .health_probe import probe_health
from .renderer import render_worker_scan_report
from .invocation_contract import WorkerInvocationContract, load_contracts
from .command_template_validator import validate_template
from .cli_error_classifier import CliErrorClass, classify_cli_error
from .safe_probe_runner import run_safe_probe
from .invocation_report import generate_invocation_report
from .audition import run_all_auditions, run_single_audition, get_scorecard_report_data

__all__ = [
    "WorkerCard",
    "WorkerCategory",
    "scan_workers",
    "WorkerRegistry",
    "probe_command",
    "probe_version",
    "probe_auth",
    "probe_health",
    "render_worker_scan_report",
    "WorkerInvocationContract",
    "load_contracts",
    "validate_template",
    "CliErrorClass",
    "classify_cli_error",
    "run_safe_probe",
    "generate_invocation_report",
    "run_all_auditions",
    "run_single_audition",
    "get_scorecard_report_data",
]

