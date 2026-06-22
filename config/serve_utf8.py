#!/usr/bin/env python3
"""
Persistent UTF-8 static file server for AgentLab workspace.
Serves /mnt/hdd2/AgentLab_WorkSpace on port 8080 and forces UTF-8
for Markdown/text/web metadata files so browsers do not display mojibake.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
import os

ROOT = os.environ.get("AGENTLAB_STATIC_ROOT", "/mnt/hdd2/AgentLab_WorkSpace")
HOST = os.environ.get("AGENTLAB_STATIC_HOST", "0.0.0.0")
PORT = int(os.environ.get("AGENTLAB_STATIC_PORT", "8080"))

UTF8_EXTS = {
    ".md", ".markdown", ".txt", ".text", ".log",
    ".html", ".htm", ".css", ".js", ".mjs",
    ".json", ".jsonl", ".yml", ".yaml", ".xml",
    ".csv", ".tsv", ".svg",
}

class UTF8StaticHandler(SimpleHTTPRequestHandler):
    server_version = "AgentLabUTF8Static/1.0"

    # Make Markdown known even on platforms whose mimetypes DB lacks it.
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".md": "text/plain",
        ".markdown": "text/plain",
        ".yml": "text/yaml",
        ".yaml": "text/yaml",
    }

    def guess_type(self, path):
        ctype = super().guess_type(path)
        ext = os.path.splitext(path)[1].lower()
        if ext in UTF8_EXTS and "charset=" not in ctype.lower():
            ctype = f"{ctype}; charset=utf-8"
        return ctype

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

if __name__ == "__main__":
    handler = partial(UTF8StaticHandler, directory=ROOT)
    httpd = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"Serving {ROOT} at http://{HOST}:{PORT}/", flush=True)
    httpd.serve_forever()
