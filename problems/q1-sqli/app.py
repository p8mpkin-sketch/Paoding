import os, sqlite3, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FLAG = os.environ.get("FLAG", "flag{REDACTED}")
DB = "/tmp/app.db"

def init():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, password TEXT)")
    con.execute("DELETE FROM users")
    con.execute("INSERT INTO users VALUES (1,'guest','guest123')")
    con.execute("INSERT INTO users VALUES (2,'admin',?)", (FLAG,))
    con.commit(); con.close()

PAGE = """<!doctype html><html><body><h2>Cow Corp Admin Login</h2>
<form method="POST" action="/login">
<input name="username" placeholder="username"> <input name="password" type="password"> <button>Login</button>
</form></body></html>"""

class H(BaseHTTPRequestHandler):
    def _send(self, body, code=200):
        self.send_response(code); self.send_header("Content-Type","text/html; charset=utf-8")
        self.end_headers(); self.wfile.write(body.encode())
    def do_GET(self): self._send(PAGE)
    def do_POST(self):
        n = int(self.headers.get("Content-Length",0))
        form = urllib.parse.parse_qs(self.rfile.read(n).decode())
        u = form.get("username",[""])[0]; p = form.get("password",[""])[0]
        con = sqlite3.connect(DB)
        try:
            rows = con.execute("SELECT id,username FROM users WHERE username='%s' AND password='%s'" % (u,p)).fetchall()
        finally: con.close()
        self._send("<h3>Welcome back, <b>%s</b>.</h3>" % rows[0][1] if rows else "<h3>Invalid credentials.</h3>")
    def log_message(self, *a): pass

init()
ThreadingHTTPServer(("0.0.0.0",8080), H).serve_forever()
