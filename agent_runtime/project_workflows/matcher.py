from typing import Any, Dict

def match_template(project_type: str, templates_config: Dict[str, Any]) -> Dict[str, Any]:
    """Match project_type to its corresponding workflow template."""
    templates = templates_config.get("templates", {})
    if project_type in templates:
        return templates[project_type]
    
    # Fallback to unknown_project if available
    if "unknown_project" in templates:
        return templates["unknown_project"]
        
    return {}
