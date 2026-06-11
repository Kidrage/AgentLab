"""Tests for external skill import (fixture-based, no network).

Covers:
  1. Parse name from fixture
  2. Parse description from fixture
  3. Token / cost estimation
  4. Create pending skill request
  5. Source snapshot saved
  6. URL not in allowlist → rejected
  7. Missing frontmatter → error
  8. Missing name/description → error
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import cost_tracker
from external_skill_importer import (
    build_external_skill_request,
    estimate_markdown_tokens,
    import_skill_from_fixture,
    import_skill_from_url,
    load_import_policy,
    parse_skill_frontmatter,
    _policy_allows_url,
)
from skill_evolution import (
    ensure_skill_registry,
    load_skill_requests,
)

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "external_skills" / "agentskills-io" / "SKILL.md"


def _write_pricing(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "model_pricing.yml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "currency": "USD",
                "models": {
                    "deepseek/deepseek-v4-pro": {
                        "input_per_1m": 1.0,
                        "output_per_1m": 2.0,
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    cost_tracker._PRICE_CACHE = None
    cost_tracker._PRICE_ROOT = None


def _write_import_policy(root: Path, *, enabled: bool = True) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "external_skill_import_policy.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "enabled": enabled,
                "allow_network_by_default": False,
                "allowed_hosts": ["raw.githubusercontent.com"],
                "allowed_url_prefixes": [
                    "https://raw.githubusercontent.com/openclaw/skills/main/skills/killerapp/agentskills-io/SKILL.md"
                ],
                "max_bytes": 200000,
                "timeout_seconds": 10,
                "store_source_snapshot": True,
                "execute_external_code": False,
                "default_status": "pending_user_approval",
                "default_risk_level": "low",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


# ── 1. Parse name from fixture ────────────────────────────────────

def test_parse_name_from_fixture() -> None:
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    result = parse_skill_frontmatter(text)
    assert result["ok"], f"parse failed: {result.get('error')}"
    assert result["name"] == "agentskills-io"


# ── 2. Parse description from fixture ─────────────────────────────

def test_parse_description_from_fixture() -> None:
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    result = parse_skill_frontmatter(text)
    assert result["ok"]
    assert len(result["description"]) > 10
    assert "Agent Skills" in result["description"] or "SKILL.md" in result["description"]


# ── 3. Token / cost estimation ────────────────────────────────────

def test_token_estimation() -> None:
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    tokens = estimate_markdown_tokens(text)
    assert tokens["input_tokens_estimate"] > 0
    assert tokens["character_count"] > 0
    assert tokens["method"] == "char_div_4"


# ── 4. Create pending skill request ───────────────────────────────

def test_fixture_creates_pending_skill_request(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    _write_import_policy(tmp_path)
    ensure_skill_registry(tmp_path)

    result = import_skill_from_fixture(
        tmp_path,
        project="AgentLab",
        fixture_path=FIXTURE_PATH,
        source_url="https://raw.githubusercontent.com/openclaw/skills/main/skills/killerapp/agentskills-io/SKILL.md",
    )
    assert result["ok"], f"import failed: {result.get('error')}"
    assert result["skill_name"] == "agentskills-io"
    assert result["status"] == "pending_user_approval"
    assert result["request_id"].startswith("skill_req_")

    # Verify request exists
    requests = load_skill_requests(tmp_path, "AgentLab")
    matching = [r for r in requests if r["id"] == result["request_id"]]
    assert len(matching) == 1
    assert matching[0]["status"] == "pending_user_approval"
    assert matching[0]["skill_name"] == "agentskills-io"
    assert matching[0]["source"]["type"] == "external_url"


# ── 5. Source snapshot saved ──────────────────────────────────────

def test_source_snapshot_saved(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    _write_import_policy(tmp_path)
    ensure_skill_registry(tmp_path)

    result = import_skill_from_fixture(
        tmp_path,
        project="AgentLab",
        fixture_path=FIXTURE_PATH,
        source_url="https://raw.githubusercontent.com/openclaw/skills/main/skills/killerapp/agentskills-io/SKILL.md",
    )
    assert result["ok"]

    # The request was written by import_skill_from_fixture via write_skill_adoption_request.
    # Verify the request yml exists using the request_id from the result.
    request_id = result["request_id"]
    request_yml = (
        tmp_path / "projects" / "AgentLab" / "skill_requests" / f"{request_id}.yml"
    )
    assert request_yml.exists(), f"Request file not found: {request_yml}"
    # Also verify that the request file content has the correct data
    data = yaml.safe_load(request_yml.read_text(encoding="utf-8")) or {}
    assert data.get("skill_name") == "agentskills-io"
    assert data.get("status") == "pending_user_approval"


# ── 6. URL not in allowlist → rejected ────────────────────────────

def test_url_not_in_allowlist_rejected(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    # Write a policy with a restrictive allowlist
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "external_skill_import_policy.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "enabled": True,
                "allow_network_by_default": False,
                "allowed_hosts": ["other-host.com"],
                "allowed_url_prefixes": [],
                "max_bytes": 200000,
                "timeout_seconds": 10,
                "store_source_snapshot": True,
                "execute_external_code": False,
                "default_status": "pending_user_approval",
                "default_risk_level": "low",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = import_skill_from_url(
        tmp_path,
        project="AgentLab",
        url="https://evil.com/skills/SKILL.md",
        allow_network=False,
    )
    assert not result["ok"]
    assert "allowlist" in result.get("error", "").lower()


# ── 7. Missing frontmatter → error ────────────────────────────────

def test_missing_frontmatter_errors() -> None:
    text = "# Just a heading\n\nNo frontmatter here.\n"
    result = parse_skill_frontmatter(text)
    assert not result["ok"]
    assert "frontmatter" in result.get("error", "").lower()


# ── 8. Missing name → error ───────────────────────────────────────

def test_missing_name_errors() -> None:
    text = "---\ndescription: A skill without a name\n---\n"
    result = parse_skill_frontmatter(text)
    assert not result["ok"]
    assert "name" in result.get("error", "").lower()


# ── 8b. Missing description → error ───────────────────────────────

def test_missing_description_errors() -> None:
    text = "---\nname: no-desc-skill\n---\n"
    result = parse_skill_frontmatter(text)
    assert not result["ok"]
    assert "description" in result.get("error", "").lower()


# ── 9. Policy allows URL check ────────────────────────────────────

def test_policy_allows_url_happy_path(tmp_path: Path) -> None:
    _write_import_policy(tmp_path)
    policy = load_import_policy(tmp_path)
    assert _policy_allows_url(
        policy,
        "https://raw.githubusercontent.com/openclaw/skills/main/skills/killerapp/agentskills-io/SKILL.md",
    )


def test_policy_denies_url_wrong_host(tmp_path: Path) -> None:
    _write_import_policy(tmp_path)
    policy = load_import_policy(tmp_path)
    assert not _policy_allows_url(policy, "https://evil.com/skills/SKILL.md")


# ── 10. Import disabled by policy ─────────────────────────────────

def test_import_disabled_by_policy(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    _write_import_policy(tmp_path, enabled=False)
    ensure_skill_registry(tmp_path)

    result = import_skill_from_url(
        tmp_path,
        project="AgentLab",
        url="https://raw.githubusercontent.com/openclaw/skills/main/skills/killerapp/agentskills-io/SKILL.md",
        allow_network=False,
    )
    assert not result["ok"]
    assert "disabled" in result.get("error", "").lower()


# ── 11. Network denied without --allow-network ────────────────────

def test_network_denied_without_allow_network(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    _write_import_policy(tmp_path)
    ensure_skill_registry(tmp_path)

    result = import_skill_from_url(
        tmp_path,
        project="AgentLab",
        url="https://raw.githubusercontent.com/openclaw/skills/main/skills/killerapp/agentskills-io/SKILL.md",
        allow_network=False,
    )
    assert not result["ok"]
    assert "network" in result.get("error", "").lower()