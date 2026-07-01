"""Active M-series labels for the current repair mainline."""

from __future__ import annotations

ACTIVE_STAGE_LABELS = {
    "M2": "Long-Project Governance Stable Baseline",
    "M3": "Operator OS / Transparent Control Plane",
    "M4": "Project-to-Revenue OS",
}

M3_FORBIDDEN_SCOPES = [
    "business_contract",
    "asset_registry",
    "production_pipeline",
    "revenue_ledger",
    "market_channel_automation",
    "crm_client_delivery_loop",
    "compliance_business_ops",
    "automatic_platform_posting",
]


def active_stage_scope() -> dict[str, object]:
    return {
        "schema_version": 1,
        "active_labels": dict(ACTIVE_STAGE_LABELS),
        "m3_scope": ACTIVE_STAGE_LABELS["M3"],
        "m3_must_not_implement": list(M3_FORBIDDEN_SCOPES),
        "historical_label_warning": (
            "Older repository docs may call Operator OS M2 and Project-to-Revenue M3. "
            "For the current repair mainline, M3 means Operator OS and M4 means Project-to-Revenue."
        ),
    }
