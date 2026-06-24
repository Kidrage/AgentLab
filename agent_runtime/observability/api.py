from __future__ import annotations
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Union

from agent_runtime.observability.event import Event, validate_event_type
from agent_runtime.observability.timeline import Timeline

logger = logging.getLogger(__name__)

def emit_event(
    project_id: str,
    project_dir: Union[Path, str],
    event_type: str,
    details: Dict[str, Any],
    source: str = "system",
    user_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    task_id: Optional[str] = None,
    role_id: Optional[str] = None,
    cost_usd: Optional[float] = None,
) -> Optional[Event]:
    """Emit an observability event safely without crashing the main pipeline."""
    try:
        validate_event_type(event_type)
        timeline = Timeline(project_id, str(project_dir))
        return timeline.add_event(
            event_type=event_type,
            details=details,
            source=source,
            user_id=user_id,
            worker_id=worker_id,
            task_id=task_id,
            role_id=role_id,
            cost_usd=cost_usd
        )
    except Exception as e:
        logger.warning(f"Failed to emit observability event '{event_type}': {e}")
        return None
