from http.server import HTTPServer, BaseHTTPRequestHandler
from .routes import dispatch_request

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        response = dispatch_request(self.path)
        self.send_response(response["status"])
        for k, v in response["headers"].items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(response["body"])
        
    def log_message(self, format, *args):
        # Silence logging
        pass

ALLOWED_LOCAL_HOSTS = {"127.0.0.1", "localhost"}

def validate_dashboard_host(host: str) -> str:
    normalized = (host or "").strip().lower()

    if normalized not in ALLOWED_LOCAL_HOSTS:
        raise ValueError(
            "M2-11 WebUI is local-only. "
            "Use --host 127.0.0.1 or --host localhost."
        )

    return normalized

def run_server(host="127.0.0.1", port=8765):
    validated_host = validate_dashboard_host(host)
    
    server_address = (validated_host, port)
    httpd = HTTPServer(server_address, DashboardHandler)
    print(f"AgentLab WebUI started on http://{validated_host}:{port}/dashboard")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("WebUI server stopped.")
