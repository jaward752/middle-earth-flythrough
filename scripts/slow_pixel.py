#!/usr/bin/env python3
"""Headless-test helper: GET /<ms> sleeps that long, then returns a 1x1 GIF.
An <img> pointing here holds the page's load event open so headless Chrome
waits real wall-clock time before --screenshot / --dump-dom."""
import sys, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
GIF = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        try: ms = int(self.path.strip('/').split('?')[0])
        except ValueError: ms = 0
        time.sleep(ms / 1000)
        self.send_response(200); self.send_header('Content-Type', 'image/gif')
        self.send_header('Content-Length', str(len(GIF))); self.end_headers(); self.wfile.write(GIF)
    def log_message(self, *a): pass
ThreadingHTTPServer(('0.0.0.0', int(sys.argv[1]) if len(sys.argv) > 1 else 8090), H).serve_forever()
