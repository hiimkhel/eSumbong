"""frontend/gateway.py
Purpose: Serve the web frontend (the React build in frontend/dist) and bridge
browser sessions to the Sumbong broker.

Browsers cannot open raw TCP sockets, so each browser session gets its own TCP
connection to the broker through this gateway. The gateway forwards the exact
one-line commands from docs/PROTOCOL.md and streams broker lines back to the
browser with Server-Sent Events. It does not parse or change the protocol beyond
answering broker PINGs with PONG and rejecting commands a browser should not send.

Python 3.12 standard library only.

HTTP API (all JSON unless noted):
    GET  /api/config                     shared settings from config.py
    POST /api/connect    {client_id, role}  -> {session}
    GET  /api/events?session=ID          text/event-stream of broker lines
    POST /api/send       {session, line}
    POST /api/disconnect {session}
"""

import argparse
import json
import logging
import queue
import socket
import sys
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402  (shared team settings live in the repo root)

# The React app's production build (`npm run build` in frontend/).
STATIC_DIR = Path(__file__).resolve().parent / "dist"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}
# Commands a browser may send after the gateway has sent HELLO for it.
ALLOWED_COMMANDS = {"SUB", "UNSUB", "SUBS", "HISTORY", "REPORT", "WITHDRAW", "ACK", "STATUS", "PING", "PONG"}
SSE_KEEPALIVE_SECONDS = 15
MAX_BODY_BYTES = 16 * 1024
CLOSED = object()  # sentinel placed on a session queue when the broker link ends

log = logging.getLogger("gateway")


class BrokerSession:
    """One browser session: a TCP connection to the broker plus a line queue."""

    def __init__(self, client_id, role, broker_addr):
        self.id = uuid.uuid4().hex
        self.client_id = client_id
        self.role = role
        self.lines = queue.Queue()
        self.closed = threading.Event()
        self._send_lock = threading.Lock()
        self.sock = socket.create_connection(broker_addr, timeout=5)
        self.sock.settimeout(None)
        self.send(f"HELLO {client_id} {role}")
        threading.Thread(target=self._read_loop, daemon=True, name=f"read-{client_id}").start()

    def send(self, line):
        data = (line + "\n").encode(config.ENCODING)
        with self._send_lock:
            self.sock.sendall(data)

    def _read_loop(self):
        try:
            with self.sock.makefile("r", encoding=config.ENCODING, newline="\n") as stream:
                for raw in stream:
                    line = raw.rstrip("\r\n")
                    if not line:
                        continue
                    if line == "PING":
                        self.send("PONG")
                        continue
                    self.lines.put(line)
        except OSError as exc:
            if not self.closed.is_set():
                log.info("broker link for %s ended: %s", self.client_id, exc)
        finally:
            self.lines.put(CLOSED)
            self.close()

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class SessionRegistry:
    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()

    def add(self, session):
        with self._lock:
            self._sessions[session.id] = session

    def get(self, session_id):
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id):
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            session.close()


def is_token(value):
    """A protocol field that must be a single space-free token."""
    return isinstance(value, str) and 0 < len(value) <= 64 and value.isprintable() and " " not in value


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "SumbongGateway/1.0"
    protocol_version = "HTTP/1.1"

    # --- routing -------------------------------------------------------------

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/config":
            self._json(HTTPStatus.OK, {
                "categories": list(config.CATEGORIES),
                "urgent_categories": list(config.URGENT_CATEGORIES),
                "roles": list(config.ROLES),
                "report_statuses": list(config.REPORT_STATUSES),
                "city_name": config.CITY_NAME,
                "district_name": config.DISTRICT_NAME,
                "barangays": [{"id": k, "name": v} for k, v in config.BARANGAYS.items()],
            })
        elif url.path == "/api/events":
            self._events(parse_qs(url.query).get("session", [""])[0])
        elif url.path.startswith("/api/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
        else:
            self._static(url.path)

    def do_POST(self):
        url = urlparse(self.path)
        body = self._read_json()
        if body is None:
            return
        if url.path == "/api/connect":
            self._connect(body)
        elif url.path == "/api/send":
            self._send(body)
        elif url.path == "/api/disconnect":
            self.server.sessions.remove(str(body.get("session", "")))
            self._json(HTTPStatus.OK, {"ok": True})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})

    # --- API -----------------------------------------------------------------

    def _connect(self, body):
        client_id = body.get("client_id")
        role = body.get("role")
        if not is_token(client_id):
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "client_id must be 1-64 characters with no spaces"})
        if role not in config.ROLES:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": f"role must be one of {', '.join(config.ROLES)}"})
        try:
            session = BrokerSession(client_id, role, self.server.broker_addr)
        except OSError as exc:
            host, port = self.server.broker_addr
            return self._json(HTTPStatus.BAD_GATEWAY, {"error": f"cannot reach broker at {host}:{port} ({exc})"})
        self.server.sessions.add(session)
        log.info("session %s opened for %s (%s)", session.id[:8], client_id, role)
        self._json(HTTPStatus.OK, {"session": session.id})

    def _send(self, body):
        session = self.server.sessions.get(str(body.get("session", "")))
        if session is None or session.closed.is_set():
            return self._json(HTTPStatus.GONE, {"error": "session closed; reconnect"})
        line = body.get("line")
        if not isinstance(line, str) or not line or "\n" in line or "\r" in line:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": "line must be one non-empty line"})
        command = line.split(" ", 1)[0]
        if command not in ALLOWED_COMMANDS:
            return self._json(HTTPStatus.BAD_REQUEST, {"error": f"command {command!r} not allowed from the browser"})
        try:
            session.send(line)
        except OSError as exc:
            self.server.sessions.remove(session.id)
            return self._json(HTTPStatus.BAD_GATEWAY, {"error": f"broker link lost ({exc})"})
        self._json(HTTPStatus.OK, {"ok": True})

    def _events(self, session_id):
        session = self.server.sessions.get(session_id)
        if session is None:
            return self._json(HTTPStatus.NOT_FOUND, {"error": "unknown session"})
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                try:
                    item = session.lines.get(timeout=SSE_KEEPALIVE_SECONDS)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                if item is CLOSED:
                    self.wfile.write(b"event: closed\ndata: broker connection closed\n\n")
                    self.wfile.flush()
                    break
                self.wfile.write(f"data: {item}\n\n".encode("utf-8"))
                self.wfile.flush()
        except OSError:
            pass  # browser went away
        finally:
            # One event stream per session: when it ends, the session ends.
            self.server.sessions.remove(session.id)
            log.info("session %s closed", session.id[:8])

    # --- helpers -------------------------------------------------------------

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if not target.is_relative_to(STATIC_DIR) or not target.is_file():
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad request body size"})
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = None
        if not isinstance(body, dict):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "body must be a JSON object"})
            return None
        return body

    def _json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)


def main():
    parser = argparse.ArgumentParser(description="Sumbong web gateway")
    parser.add_argument("--host", default="127.0.0.1", help="web interface to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="web port (default 8080)")
    parser.add_argument("--broker-host", default=config.HOST)
    parser.add_argument("--broker-port", type=int, default=config.PORT)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    server = ThreadingHTTPServer((args.host, args.port), GatewayHandler)
    server.daemon_threads = True
    server.broker_addr = (args.broker_host, args.broker_port)
    server.sessions = SessionRegistry()
    log.info("serving http://%s:%d -> broker %s:%d", args.host, args.port, args.broker_host, args.broker_port)
    if not (STATIC_DIR / "index.html").is_file():
        log.warning("no web build in %s; run `npm install` and `npm run build` in frontend/ "
                    "(the API still works, e.g. for `npm run dev`)", STATIC_DIR)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
