"""Small local demo API; registration.py is the requested implementation."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = '''<!doctype html><html><head><title>CodeOps registration demo</title></head>
<body><h1>Registration demo</h1><form id="registration">
<label>Name <input name="name" required></label>
<label>Email <input name="email" type="email" required></label>
<button>Register</button></form><pre id="result"></pre>
<script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();
const r=await fetch('/register',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});
document.querySelector('#result').textContent=r.status+' '+await r.text();};</script>
</body></html>'''


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(value).encode())

    def do_GET(self):
        if self.path == '/health':
            return self.reply(200, {'status': 'ok'})
        if self.path != '/':
            return self.reply(404, {'error': 'Not found'})
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(PAGE.encode())

    def do_POST(self):
        if self.path != '/register':
            return self.reply(404, {'error': 'Not found'})
        try:
            from registration import register
        except ImportError:
            return self.reply(501, {'error': 'Registration implementation required'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 4096:
                raise ValueError('Invalid request size')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Expected an object')
            result = register(payload.get('name'), payload.get('email'))
        except (ValueError, TypeError) as exc:
            return self.reply(400, {'error': str(exc)})
        return self.reply(201, result)


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
