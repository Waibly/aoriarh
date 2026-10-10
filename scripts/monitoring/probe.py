"""Sondes techniques publiques, sans appel LLM ni contournement de Turnstile."""
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

CHECKS = {
    'homepage': ('https://aoriarh.fr/', None, 200),
    'demo_page': ('https://app.aoriarh.fr/demo', None, 200),
    'api_health': ('https://api.aoriarh.fr/health', None, 200),
    # Jeton absent : le schéma doit être accepté, puis Turnstile doit refuser.
    # Un 422 détecte une rupture de contrat ; un 200 détecte une protection absente.
    'demo_contract': ('https://api.aoriarh.fr/api/v1/public/ask',
                      {'message': 'Sonde technique de démonstration', 'turnstile_token': None}, 403),
}
RESULTS = {}
LOCK = threading.Lock()


def check(url, payload, expected):
    request = urllib.request.Request(url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type': 'application/json', 'User-Agent': 'Aoria-Technical-Monitor/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = response.status
            body = response.read(1048576)
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read(1048576)
    if status != expected:
        return False
    if url.endswith('/health'):
        return json.loads(body).get('status') == 'ok'
    return True


def collect():
    while True:
        for name, args in CHECKS.items():
            try:
                result = int(check(*args))
            except Exception:
                result = 0
            with LOCK:
                RESULTS[name] = (result, time.time())
        time.sleep(60)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/metrics':
            self.send_error(404)
            return
        with LOCK:
            values = dict(RESULTS)
        lines = ['# TYPE aoria_public_probe_success gauge',
                 '# TYPE aoria_public_probe_timestamp_seconds gauge']
        for name in CHECKS:
            success, timestamp = values.get(name, (0, 0))
            lines.extend([
                f'aoria_public_probe_success{{check="{name}"}} {success}',
                f'aoria_public_probe_timestamp_seconds{{check="{name}"}} {timestamp}',
            ])
        body = ('\n'.join(lines) + '\n').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    threading.Thread(target=collect, daemon=True).start()
    HTTPServer(('0.0.0.0', 9116), Handler).serve_forever()
