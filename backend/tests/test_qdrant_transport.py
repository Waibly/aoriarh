"""Qdrant must be allowed to finish a cold search beyond ten seconds."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.rag.qdrant_store import _create_client


def test_slow_qdrant_response_is_received_once(monkeypatch):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            time.sleep(11)
            body = json.dumps({"result": {"collections": []}, "status": "ok", "time": 11}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr("app.rag.qdrant_store.settings.qdrant_host", "127.0.0.1")
    monkeypatch.setattr("app.rag.qdrant_store.settings.qdrant_port", server.server_port)
    monkeypatch.setattr("app.rag.qdrant_store.settings.qdrant_api_key", "")
    client = _create_client()
    try:
        assert client.get_collections().collections == []
        assert calls == ["/collections"]
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
