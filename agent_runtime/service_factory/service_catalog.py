"""Deterministic S12 service catalog, quote, timeline, and delivery package API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re

import yaml

_PRIVATE_PATH_RE = re.compile(r"/" + r"Users/[^/\s]+")


@dataclass(frozen=True)
class ServiceCatalogItem:
    service_id: str
    description: str
    required_capabilities: list[str]
    default_workflow_template: str
    estimated_phases: int
    quality_rubric: list[str]
    deliverables: list[str]
    human_approval_points: list[str]
    risk_notes: list[str]
    trigger_terms: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServiceCatalogItem":
        required = [
            "service_id",
            "description",
            "required_capabilities",
            "default_workflow_template",
            "estimated_phases",
            "quality_rubric",
            "deliverables",
            "human_approval_points",
            "risk_notes",
        ]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"service catalog item missing fields: {missing}")
        return cls(
            service_id=str(data["service_id"]),
            description=str(data["description"]),
            required_capabilities=list(data["required_capabilities"] or []),
            default_workflow_template=str(data["default_workflow_template"]),
            estimated_phases=int(data["estimated_phases"]),
            quality_rubric=list(data["quality_rubric"] or []),
            deliverables=list(data["deliverables"] or []),
            human_approval_points=list(data["human_approval_points"] or []),
            risk_notes=list(data["risk_notes"] or []),
            trigger_terms=list(data.get("trigger_terms", []) or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "description": self.description,
            "required_capabilities": self.required_capabilities,
            "default_workflow_template": self.default_workflow_template,
            "estimated_phases": self.estimated_phases,
            "quality_rubric": self.quality_rubric,
            "deliverables": self.deliverables,
            "human_approval_points": self.human_approval_points,
            "risk_notes": self.risk_notes,
        }


def _safe_write_yaml(path: Path, data: dict[str, Any]) -> None:
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    text = _PRIVATE_PATH_RE.sub("<redacted-user-path>", text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_service_catalog(path: Path) -> list[ServiceCatalogItem]:
    if not path.exists():
        raise FileNotFoundError(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services = data.get("services", [])
    items = [ServiceCatalogItem.from_dict(item) for item in services]
    ids = [item.service_id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate service_id in service catalog")
    return sorted(items, key=lambda item: item.service_id)


def match_service(prompt: str, catalog: list[ServiceCatalogItem]) -> ServiceCatalogItem:
    normalized = prompt.lower()
    best: tuple[int, ServiceCatalogItem] | None = None
    for item in catalog:
        score = 0
        for term in [item.service_id, *item.trigger_terms, *item.deliverables, item.description]:
            term_text = str(term).lower().replace("_", " ")
            if term_text and term_text in normalized:
                score += 3
            for token in re.findall(r"[a-z0-9\u4e00-\u9fff]+", term_text):
                if len(token) >= 2 and token in normalized:
                    score += 1
        if item.service_id == "local_file_organization" and any(term in prompt for term in ["文件整理", "本地文件", "整理助手"]):
            score += 20
        if item.service_id == "company_research_report" and any(term in prompt for term in ["公司", "调研", "加入"]):
            score += 12
        if item.service_id == "longform_novel_blueprint" and any(term in prompt for term in ["小说", "长篇", "章节"]):
            score += 12
        if best is None or score > best[0]:
            best = (score, item)
    if best is None or best[0] <= 0:
        return next(item for item in catalog if item.service_id == "personal_automation_workflow")
    return best[1]


def estimate_quote(service: ServiceCatalogItem, complexity: str = "medium") -> dict[str, Any]:
    multipliers = {"small": 1, "medium": 2, "large": 3, "enterprise": 5}
    factor = multipliers.get(complexity, 2)
    risk_factor = 1 + min(len(service.risk_notes), 5) * 0.1
    approval_factor = 1 + len(service.human_approval_points) * 0.05
    effort_points = round((service.estimated_phases * factor) * risk_factor * approval_factor, 2)
    if effort_points <= 5:
        quote_band = "small"
    elif effort_points <= 10:
        quote_band = "medium"
    elif effort_points <= 18:
        quote_band = "large"
    else:
        quote_band = "enterprise"
    return {
        "service_id": service.service_id,
        "complexity": complexity,
        "quote_band": quote_band,
        "effort_points": effort_points,
        "required_capabilities": service.required_capabilities,
        "external_execution_needed": any(capability in {"web_search", "browser_fetch", "github_ops"} for capability in service.required_capabilities),
        "human_approval_count": len(service.human_approval_points),
        "timeline": {
            "estimated_phases": service.estimated_phases,
            "phase_unit": "deterministic local-first phase",
            "approval_gates": service.human_approval_points,
        },
        "quality_rubric": service.quality_rubric,
        "deliverables": service.deliverables,
        "risk_notes": service.risk_notes,
    }


def build_delivery_package(out_dir: Path, service: ServiceCatalogItem, quote: dict[str, Any]) -> Path:
    package = out_dir / "delivery_package"
    (package / "artifacts").mkdir(parents=True, exist_ok=True)
    (package / "evidence").mkdir(parents=True, exist_ok=True)
    files = {
        "final_summary.md": [
            "# Final Delivery Summary",
            "",
            f"Service: {service.service_id}",
            f"Quote band: {quote['quote_band']}",
            "",
            "## Deliverables",
            *[f"- {item}" for item in service.deliverables],
        ],
        "acceptance_history.md": [
            "# Acceptance History",
            "",
            "- Pending project execution; package schema prepared by S12 service factory.",
        ],
        "risks_and_limitations.md": [
            "# Risks and Limitations",
            "",
            *[f"- {item}" for item in service.risk_notes],
        ],
        "reproduction_commands.md": [
            "# Reproduction Commands",
            "",
            "```bash",
            "./agentlab.sh service-factory-plan --prompt '<request>' --out /tmp/agentlab_service_factory",
            "```",
        ],
        "next_steps.md": [
            "# Next Steps",
            "",
            "- Review quote and timeline estimate.",
            "- Approve any capability or executor handoff before real execution.",
            "- Run the relevant mission/workflow/project pipeline for the selected service.",
        ],
    }
    for name, lines in files.items():
        (package / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return package


def write_service_factory_artifacts(root: Path, prompt: str, out_dir: Path, complexity: str = "medium") -> dict[str, Any]:
    catalog = load_service_catalog(root / "config" / "service_catalog.yml")
    service = match_service(prompt, catalog)
    quote = estimate_quote(service, complexity)
    out_dir.mkdir(parents=True, exist_ok=True)
    service_match = {"service_id": service.service_id, "description": service.description, "workflow_template": service.default_workflow_template}
    timeline = quote["timeline"]
    _safe_write_yaml(out_dir / "service_match.yml", service_match)
    _safe_write_yaml(out_dir / "quote_estimate.yml", quote)
    _safe_write_yaml(out_dir / "timeline_estimate.yml", timeline)
    package = build_delivery_package(out_dir, service, quote)
    return {
        "service_match": service_match,
        "quote_estimate": quote,
        "timeline_estimate": timeline,
        "delivery_package": str(package),
    }
