def handle_approve():
    return "approved"

def handle_reject():
    return "rejected"

def handle_pause():
    return "paused"

def handle_resume():
    return "resumed"

def handle_retry():
    return "retrying"

def handle_rollback():
    return "rolled back"

def handle_enable_worker(worker_id):
    return f"enabled {worker_id}"

def handle_disable_worker(worker_id):
    return f"disabled {worker_id}"
