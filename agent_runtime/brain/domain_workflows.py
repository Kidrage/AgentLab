"""Domain workflow template catalog for AgentLab S1-C.

The catalog is deterministic planning data. Loading and selection are deliberately
local-only: no provider calls, no repository inspection, no shell execution, and
no lifecycle mutation. Malformed templates are represented as catalog warnings so
callers can surface structured errors without raw tracebacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE_PATH = ROOT / "config" / "domain_workflow_templates.yml"
UNKNOWN_TEMPLATE_ID = "unknown_exploratory"
REQUIRED_FIELDS = (
    "template_id",
    "task_types",
    "trigger_signals",
    "required_capabilities",
    "phase_plan",
    "required_artifacts",
    "acceptance_gates",
    "risk_defaults",
    "human_approval",
    "notes",
)
LIST_FIELDS = (
    "task_types",
    "trigger_signals",
    "required_capabilities",
    "phase_plan",
    "required_artifacts",
    "acceptance_gates",
    "risk_defaults",
    "notes",
)


@dataclass(frozen=True)
class DomainWorkflowTemplate:
    """One deterministic domain workflow planning template."""

    template_id: str
    task_types: list[str] = field(default_factory=list)
    trigger_signals: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    phase_plan: list[str] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)
    acceptance_gates: list[str] = field(default_factory=list)
    risk_defaults: list[str] = field(default_factory=list)
    human_approval: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class DomainWorkflowCatalog:
    """Loaded templates plus non-fatal validation warnings."""

    templates: dict[str, DomainWorkflowTemplate] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def get(self, template_id: str) -> DomainWorkflowTemplate | None:
        """Return a template by id, or None when it is unavailable."""

        return self.templates.get(template_id)

    @property
    def unknown_template(self) -> DomainWorkflowTemplate:
        """Return the unknown fallback, creating an in-memory safe template if needed."""

        return self.templates.get(UNKNOWN_TEMPLATE_ID) or _fallback_unknown_template()


class DomainWorkflowLoadError(ValueError):
    """Structured domain workflow load problem for callers that want errors."""

    def __init__(self, warnings: list[str]):
        self.warnings = warnings
        super().__init__("; ".join(warnings))


def _fallback_unknown_template() -> DomainWorkflowTemplate:
    """Build a safe fallback template for malformed or missing catalogs."""

    return DomainWorkflowTemplate(
        template_id=UNKNOWN_TEMPLATE_ID,
        task_types=["unknown", "exploratory"],
        trigger_signals=["unclear", "ambiguous", "unknown"],
        required_capabilities=["human_approval"],
        phase_plan=[
            "restate_known_request",
            "identify_unknowns",
            "propose_clarifying_questions",
            "define_safe_minimal_plan",
            "require_human_approval",
            "summarize_limits",
        ],
        required_artifacts=[
            "intent_summary.md",
            "clarifying_questions.md",
            "assumptions.yml",
            "proposed_plan.md",
            "acceptance_report.md",
        ],
        acceptance_gates=[
            "ambiguity is explicitly documented",
            "human approval is required before execution",
            "execution scope is not expanded beyond prompt",
            "capability gaps are labeled",
        ],
        risk_defaults=["ambiguous_goal_risk", "capability_gap_risk"],
        human_approval={
            "required_by_default": True,
            "required_when": ["unknown_task_type", "destructive_change", "external_execution"],
        },
        notes=["Generated in-memory fallback because no valid unknown template was available."],
    )


def _as_list(value: Any) -> list[str]:
    """Coerce YAML scalar/list values to a stable list of stripped strings."""

    if value is None:
        return []
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = [value]
    result: list[str] = []
    for item in raw_values:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _structured_warning(template_id: str, field_name: str, message: str) -> str:
    """Return a deterministic warning string for malformed template data."""

    return f"template={template_id} field={field_name}: {message}"


def _template_from_mapping(template_id: str, raw: Any) -> tuple[DomainWorkflowTemplate | None, list[str]]:
    """Convert one raw YAML mapping into a DomainWorkflowTemplate."""

    warnings: list[str] = []
    if not isinstance(raw, dict):
        return None, [_structured_warning(template_id, "template", "entry must be a mapping")]

    raw_id = str(raw.get("template_id") or template_id).strip()
    if not raw_id:
        raw_id = template_id
    if raw_id != template_id:
        warnings.append(
            _structured_warning(template_id, "template_id", f"does not match key {raw_id!r}")
        )

    for field_name in REQUIRED_FIELDS:
        if field_name not in raw:
            warnings.append(_structured_warning(template_id, field_name, "missing required field"))
    for field_name in LIST_FIELDS:
        if field_name in raw and not isinstance(raw.get(field_name), list):
            warnings.append(_structured_warning(template_id, field_name, "expected a list"))
    human_approval = raw.get("human_approval") if isinstance(raw.get("human_approval"), dict) else {}
    if "human_approval" in raw and not isinstance(raw.get("human_approval"), dict):
        warnings.append(_structured_warning(template_id, "human_approval", "expected a mapping"))

    template = DomainWorkflowTemplate(
        template_id=raw_id,
        task_types=_as_list(raw.get("task_types")),
        trigger_signals=_as_list(raw.get("trigger_signals")),
        required_capabilities=_as_list(raw.get("required_capabilities")),
        phase_plan=_as_list(raw.get("phase_plan")),
        required_artifacts=_as_list(raw.get("required_artifacts")),
        acceptance_gates=_as_list(raw.get("acceptance_gates")),
        risk_defaults=_as_list(raw.get("risk_defaults")),
        human_approval=dict(human_approval),
        notes=_as_list(raw.get("notes")),
    )

    for field_name in LIST_FIELDS:
        if not getattr(template, field_name):
            warnings.append(_structured_warning(template_id, field_name, "must not be empty"))
    if not template.human_approval:
        warnings.append(_structured_warning(template_id, "human_approval", "must not be empty"))
    return template, warnings


def _load_yaml_mapping(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Read a YAML file and return a mapping plus structured warnings."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, [f"catalog_path={path}: failed to read template file: {exc}"]
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return {}, [f"catalog_path={path}: failed to parse YAML: {exc}"]
    if not isinstance(data, dict):
        return {}, [f"catalog_path={path}: top-level YAML must be a mapping"]
    return data, []


def load_domain_workflow_templates(path: Path | str | None = None) -> DomainWorkflowCatalog:
    """Load deterministic domain workflow templates from YAML.

    The function never raises raw YAML/file tracebacks. Missing files, malformed
    top-level data, malformed template entries, and missing fallback templates are
    all represented as catalog warnings. A safe in-memory unknown fallback is
    always available to selection callers.
    """

    template_path = Path(path) if path is not None else DEFAULT_TEMPLATE_PATH
    data, warnings = _load_yaml_mapping(template_path)
    raw_templates = data.get("templates", data)
    templates: dict[str, DomainWorkflowTemplate] = {}

    if not isinstance(raw_templates, dict):
        warnings.append("field=templates: expected a mapping of template id to template data")
        raw_templates = {}

    for template_id in sorted(raw_templates):
        template, item_warnings = _template_from_mapping(str(template_id), raw_templates[template_id])
        warnings.extend(item_warnings)
        if template is not None:
            templates[template.template_id] = template

    if UNKNOWN_TEMPLATE_ID not in templates:
        warnings.append(
            f"template={UNKNOWN_TEMPLATE_ID}: missing fallback template; using in-memory fallback"
        )
        templates[UNKNOWN_TEMPLATE_ID] = _fallback_unknown_template()

    return DomainWorkflowCatalog(templates=templates, warnings=warnings)


def _normalize_task_type(task_type: str) -> str:
    """Normalize MissionTaskType enum values or plain strings."""

    value = getattr(task_type, "value", task_type)
    return str(value or "unknown").strip().lower() or "unknown"


def _signal_tokens(domain_signals: list[str]) -> set[str]:
    """Extract lowercase tokens from domain signal notes for overlap scoring."""

    tokens: set[str] = set()
    for signal in domain_signals:
        lowered = str(signal).lower().replace("=", " ").replace(":", " ").replace(",", " ")
        for token in lowered.split():
            clean = token.strip(" .;()[]{}")
            if clean:
                tokens.add(clean)
        tokens.add(str(signal).lower())
    return tokens


def _template_signal_score(template: DomainWorkflowTemplate, domain_signals: list[str]) -> int:
    """Return deterministic overlap between template triggers and domain signals."""

    if not domain_signals:
        return 0
    signal_text = "\n".join(domain_signals).lower()
    tokens = _signal_tokens(domain_signals)
    score = 0
    for trigger in template.trigger_signals:
        lowered = trigger.lower()
        if lowered in tokens or lowered in signal_text:
            score += 1
    return score


def select_domain_workflow(
    task_type: str,
    domain_signals: list[str],
    catalog: DomainWorkflowCatalog | None = None,
) -> DomainWorkflowTemplate:
    """Select the best domain workflow template for a classified task.

    Selection prefers templates whose ``task_types`` contain the classified task
    type. Domain-signal overlap breaks ties. Unknown task types and catalogs with
    missing entries fall back to ``unknown_exploratory`` instead of crashing.
    """

    active_catalog = catalog or load_domain_workflow_templates()
    normalized = _normalize_task_type(task_type)
    candidates = list(active_catalog.templates.values())
    if not candidates:
        return _fallback_unknown_template()

    scored: list[tuple[int, int, str, DomainWorkflowTemplate]] = []
    for template in candidates:
        task_match = 1 if normalized in {item.lower() for item in template.task_types} else 0
        signal_score = _template_signal_score(template, domain_signals)
        scored.append((task_match, signal_score, template.template_id, template))

    direct_matches = [item for item in scored if item[0] > 0]
    if not direct_matches:
        return active_catalog.unknown_template

    direct_matches.sort(key=lambda item: (-item[0], -item[1], item[2]))
    selected = direct_matches[0][3]
    if selected.template_id == UNKNOWN_TEMPLATE_ID:
        return selected
    return selected


def template_note(template: DomainWorkflowTemplate) -> str:
    """Return the MissionContract note used to preserve selected template id."""

    return f"domain_workflow_template: {template.template_id}"
