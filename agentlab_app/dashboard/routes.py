import re
from .api import json_response

def handle_dashboard(path):
    return json_response({"page": "dashboard", "message": "Welcome to AgentLab WebUI"})

def handle_projects(path):
    return json_response({"page": "projects", "projects": []})

def handle_project_detail(path):
    # Extracts id from /project/<id>
    match = re.match(r"^/project/([^/]+)(?:/(.*))?$", path)
    if not match:
        return json_response({"error": "not found"}, 404)
        
    project_id = match.group(1)
    sub_route = match.group(2)
    
    if not sub_route:
        return json_response({"page": "project_detail", "project_id": project_id})
    elif sub_route in ["timeline", "costs", "phases", "artifacts", "routes"]:
        return json_response({"page": f"project_{sub_route}", "project_id": project_id})
    else:
        return json_response({"error": "not found"}, 404)

def handle_workers(path):
    match = re.match(r"^/workers(?:/([^/]+))?$", path)
    worker_id = match.group(1) if match else None
    
    if worker_id:
        return json_response({"page": "worker_detail", "worker_id": worker_id})
    else:
        return json_response({"page": "workers", "workers": []})

def handle_simple_route(page_name):
    return lambda path: json_response({"page": page_name})

ROUTES = [
    (r"^/dashboard$", handle_dashboard),
    (r"^/projects$", handle_projects),
    (r"^/project/", handle_project_detail),
    (r"^/workers", handle_workers),
    (r"^/roles$", handle_simple_route("roles")),
    (r"^/skills$", handle_simple_route("skills")),
    (r"^/capabilities$", handle_simple_route("capabilities")),
    (r"^/executors$", handle_simple_route("executors")),
    (r"^/settings$", handle_simple_route("settings")),
    (r"^/recovery$", handle_simple_route("recovery")),
    (r"^/approvals$", handle_simple_route("approvals")),
]

def dispatch_request(path):
    for pattern, handler in ROUTES:
        if re.match(pattern, path):
            return handler(path)
    return json_response({"error": "Not Found"}, 404)
