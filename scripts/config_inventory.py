#!/usr/bin/env python3
"""Write a conservative inventory of config files for cleanup planning."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_runtime.config_inventory import (  # noqa: E402
    build_config_inventory,
    config_inventory_payload,
    render_config_inventory_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=Path("acceptance_runs/config_inventory"))
    args = parser.parse_args()

    root = args.root.resolve()
    out = args.out if args.out.is_absolute() else root / args.out
    out.mkdir(parents=True, exist_ok=True)

    items = build_config_inventory(root)
    (out / "CONFIG_INVENTORY.md").write_text(render_config_inventory_markdown(items), encoding="utf-8")
    (out / "config_inventory.json").write_text(
        json.dumps(config_inventory_payload(root), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote config inventory to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
