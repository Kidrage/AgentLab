from __future__ import annotations
from typing import List
from agent_runtime.observability.event import Event

def render_timeline(events: List[Event]) -> str:
    """Format events for CLI/TUI output."""
    lines = []
    lines.append("=== Project Timeline ===")
    if not events:
        lines.append("No events found.")
        return "\n".join(lines)
        
    for ev in events:
        ts = ev.timestamp[:19].replace("T", " ")
        cost_str = f" [Cost: ${ev.cost_usd:.4f}]" if ev.cost_usd is not None else ""
        worker_str = f" [Worker: {ev.worker_id}]" if ev.worker_id else ""
        lines.append(f"[{ts}] {ev.event_type.upper()}{worker_str}{cost_str}")
        
        if ev.details:
            detail_str = str(ev.details)
            if len(detail_str) > 120:
                detail_str = detail_str[:117] + "..."
            lines.append(f"  └─ {detail_str}")
            
    return "\n".join(lines)
