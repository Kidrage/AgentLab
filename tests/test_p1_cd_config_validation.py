from __future__ import annotations

import yaml
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_p1_cd_configs_disabled_by_default() -> None:
    search = yaml.safe_load((ROOT / "config" / "search_providers.yml").read_text(encoding="utf-8"))
    repo = yaml.safe_load((ROOT / "config" / "repo_indexing.yml").read_text(encoding="utf-8"))
    assert search["search_providers"]["anysearch"]["enabled"] is False
    assert repo["repo_indexing"]["enabled"] is False

