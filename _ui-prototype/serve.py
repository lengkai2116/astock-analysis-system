#!/usr/bin/env python3.11
"""Static file server with API proxy to Flask backend on port 5001"""

import http.server
import socketserver
import os
import sys
import urllib.request
import urllib.error

os.chdir(os.path.dirname(os.path.abspath(__file__)))
PORT = int(sys.argv[sys.argv.index('--port') + 1]) if '--port' in sys.argv else int(os.environ.get('PORT', 8082))
BACKEND = os.environ.get('BACKEND_URL', 'http://127.0.0.1:5001')


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    """Serves static files, proxying /api/ requests to the Flask backend."""

    def do_GET(self):
        if self.path.startswith('/api/'):
            self._proxy('GET')
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith('/api/'):
            self._proxy('POST')
        else:
            self.send_error(405)

    def do_OPTIONS(self):
        if self.path.startswith('/api/'):
            self._proxy('OPTIONS')
        else:
            self.send_error(405)

    def _proxy(self, method):
        url = BACKEND + self.path
        try:
            body = None
            if method in ('POST', 'PUT'):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length) if length > 0 else None

            req = urllib.request.Request(url, data=body, method=method)
            # Forward relevant headers
            for h in ('Content-Type', 'Accept', 'Authorization'):
                if h in self.headers:
                    req.add_header(h, self.headers[h])

            resp = urllib.request.urlopen(req, timeout=30)
            self.send_response(resp.status)
            self.send_header('Content-Type', resp.headers.get('Content-Type', 'application/json'))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            self.end_headers()
            self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_error(502, f'Proxy error: {e}')


with socketserver.TCPServer(("127.0.0.1", PORT), ProxyHandler) as httpd:
    print(f"Serving at http://127.0.0.1:{PORT} (API proxy -> {BACKEND})")
    httpd.serve_forever()
