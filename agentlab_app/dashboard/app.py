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

def run_server(host="127.0.0.1", port=8765):
    if host != "127.0.0.1":
        print(f"WARNING: Binding to non-localhost {host} is restricted.")
    
    server_address = (host, port)
    httpd = HTTPServer(server_address, DashboardHandler)
    print(f"AgentLab WebUI started on http://{host}:{port}/dashboard")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("WebUI server stopped.")
