"""Cache profile calculation and monitoring for execution economy."""

import hashlib
from typing import List, Optional
from agent_runtime.execution_economy.activation_cost import CacheProfile

def compute_hash(data: str) -> str:
    """Helper to compute sha256 prefix hash."""
    return f"sha256:{hashlib.sha256(data.encode('utf-8')).hexdigest()[:20]}"

def calculate_cache_profile(
    worker_id: str,
    skills: Optional[List[str]] = None,
    mcp_servers: Optional[List[str]] = None,
    last_hit: str = "unknown"
) -> CacheProfile:
    """Generate a CacheProfile for a given worker and its capabilities."""
    stable_prefix = compute_hash(f"role-prefix-{worker_id}")
    
    skill_hash = None
    if skills:
        sorted_skills = sorted(skills)
        skill_hash = compute_hash(",".join(sorted_skills))
        
    mcp_hash = None
    if mcp_servers:
        sorted_mcps = sorted(mcp_servers)
        mcp_hash = compute_hash(",".join(sorted_mcps))
        
    confidence = "medium"
    if worker_id in ("rg", "git"):
        confidence = "high"
        
    return CacheProfile(
        stable_prefix_hash=stable_prefix,
        skill_context_hash=skill_hash,
        mcp_manifest_hash=mcp_hash,
        last_cache_hit_observed=last_hit,
        cache_confidence=confidence
    )
