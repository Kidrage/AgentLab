"""External project registry for M1 project governance.

This package models external projects as capability providers or references.
It never clones, installs, imports, or executes external project code.
"""

from .registry import ExternalProjectRegistry, load_external_project_registry
from .renderer import write_external_project_risk_report

__all__ = [
    "ExternalProjectRegistry",
    "load_external_project_registry",
    "write_external_project_risk_report",
]
