import os, json, subprocess, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER = os.environ.get("ANSWER", "answer-not-set")
KEY = "S3cr3t-K3y-9f2a"
INTERNAL = os.environ.get("INTERNAL_PATH", "/var/private/internal.txt")
import os as _os; _os.makedirs(_os.path.dirname(INTERNAL), exist_ok=True)
ANSWER_PATH = os.environ.get("ANSWER_PATH", "/answer")
with open(ANSWER_PATH,"w") as f: f.write(ANSWER)
with open(INTERNAL,"w") as f:
    f.write("Internal reporting API: port 8081, POST /api/run\nHeader X-Internal-Key: %s\nBody: {\"cmd\": \"<shell command>\"}\n" % KEY)

PAGE = """<!doctype html><html><body><h2>Cow Corp Public Files</h2>
<p>Files: <a href="/download?name=readme.txt">readme.txt</a> <a href="/download?name=cow.jpg">cow.jpg</a></p>
</body></html>"""

class Files(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.urlparse(self.path); params = urllib.parse.parse_qs(q.query)
        if q.path == "/download":
            name = params.get("name",[""])[0]
            path = os.path.join("/srv/files", name)          # 无遍历防护
            try: body = open(path,"rb").read()
            except Exception: self.send_error(404); return
            self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers()
            self.wfile.write(body); return
        self.send_response(200); self.send_header("Content-Type","text/html"); self.end_headers(); self.wfile.write(PAGE.encode())
    def log_message(self, *a): pass

class Api(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/run" or self.headers.get("X-Internal-Key") != KEY:
            self.send_error(403); return
        n = int(self.headers.get("Content-Length",0))
        try: cmd = json.loads(self.rfile.read(n)).get("cmd","")
        except Exception: self.send_error(400); return
        out = subprocess.run(["sh","-c",cmd], capture_output=True)   # 直接拼接，无过滤
        self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers()
        self.wfile.write(out.stdout + out.stderr)
    def log_message(self, *a): pass

import threading
def serve(h): h.serve_forever()
t1 = threading.Thread(target=serve, args=(ThreadingHTTPServer(("0.0.0.0",8080), Files),), daemon=True)
t2 = threading.Thread(target=serve, args=(ThreadingHTTPServer(("0.0.0.0",8081), Api),), daemon=True)
t1.start(); t2.start(); t1.join(); t2.join()
