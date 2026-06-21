#!/usr/bin/env python3
"""Auto-adjust policy script for AgentLab.

This script scans active environment variables (API keys) and model catalog capabilities,
then generates dynamic overrides for agent model profiles.
"""

import os
import sys
from pathlib import Path
import yaml

def main():
    # 1. Locate paths
    agentlab_root = Path(__file__).resolve().parent.parent
    providers_path = agentlab_root / "config" / "model_providers.yml"
    catalog_path = agentlab_root / "config" / "model_catalog.yml"
    
    # 2. Check keys
    has_deepseek = bool(os.getenv("DEEPSEEK_API_KEY"))
    has_dashscope = bool(os.getenv("DASHSCOPE_API_KEY"))
    
    print(f"Auto-adjust Scanner:")
    print(f"  DEEPSEEK_API_KEY: {'Active' if has_deepseek else 'Missing'}")
    print(f"  DASHSCOPE_API_KEY: {'Active' if has_dashscope else 'Missing'}")
    
    if not has_deepseek and not has_dashscope:
        print("  WARNING: No active keys found. Fallback to default static config.")
        return 0

    # 3. Create temporary overrides or print mapping
    print("  Optimal API Mapping (Full Tier):")
    roles = ["supervisor", "coder", "reposcout", "interface_mapper", "prompt_engineer", "tester_auditor", "verifier", "archivist"]
    for role in roles:
        model = None
        if role in {"supervisor", "verifier", "tester_auditor"}:
            model = "deepseek_v4_pro" if has_deepseek else "qwen3_7_max_dashscope"
        elif role == "coder":
            model = "qwen3_coder_plus_dashscope" if has_dashscope else "deepseek_v4_pro"
        elif role in {"reposcout", "interface_mapper", "prompt_engineer"}:
            model = "qwen3_7_max_dashscope" if has_dashscope else "deepseek_v4_pro"
        elif role in {"researcher", "archivist"}:
            model = "deepseek_v4_flash" if has_deepseek else "qwen3_6_plus_dashscope"
        print(f"    {role:20} -> {model}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
