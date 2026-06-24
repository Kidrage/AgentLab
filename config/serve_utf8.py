#!/usr/bin/env python3
"""
Persistent UTF-8 static file server for AgentLab workspace.
Serves the directory specified by AGENTLAB_STATIC_ROOT on the configured
host/port and forces UTF-8 for Markdown/text/web metadata files so
browsers do not display mojibake.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
import os

ROOT = os.environ.get("AGENTLAB_STATIC_ROOT", "")  # MUST be set via env — no default path
HOST = os.environ.get("AGENTLAB_STATIC_HOST", "127.0.0.1")
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
    if not ROOT:
        raise SystemExit(
            "AGENTLAB_STATIC_ROOT must be set to the directory to serve. "
            "Refusing to start with an empty root."
        )
    if not os.path.isdir(ROOT):
        raise SystemExit(f"AGENTLAB_STATIC_ROOT={ROOT} is not a directory or does not exist.")
    handler = partial(UTF8StaticHandler, directory=ROOT)
    httpd = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"Serving {ROOT} at http://{HOST}:{PORT}/", flush=True)
    httpd.serve_forever()
