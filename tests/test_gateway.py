"""Tests for the web gateway (frontend/gateway.py): HTTP API, browser-to-broker
bridge over Server-Sent Events, command filtering and static file serving.
Each test runs a real broker (in-memory database) and a real gateway on free ports.
Run: python -m unittest discover -s tests"""

import http.client
import json
import os
import queue
import socket
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "frontend"))

import auth  # noqa: E402
import broker  # noqa: E402
import config  # noqa: E402
import gateway  # noqa: E402
import store  # noqa: E402

WAIT = 5


class EventStream:
    """Reads one session's /api/events stream on a thread; lines land in a queue."""

    def __init__(self, port, session):
        self.q = queue.Queue()
        self.conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        self.conn.request("GET", f"/api/events?session={session}")
        self.response = self.conn.getresponse()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        event = "message"
        try:
            for raw in self.response:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    self.q.put((event, line[6:]))
                    event = "message"
        except (OSError, ValueError):
            pass
        self.q.put(("eof", None))

    def next(self, prefix=""):
        """The next data line starting with prefix (other lines are skipped)."""
        while True:
            event, data = self.q.get(timeout=WAIT)
            if event == "eof":
                raise AssertionError(f"stream ended while waiting for {prefix!r}")
            if event == "message" and data.startswith(prefix):
                return data

    def next_event(self):
        while True:
            event, data = self.q.get(timeout=WAIT)
            if event != "message":
                return event, data

    def close(self):
        self.conn.close()


class GatewayTest(unittest.TestCase):

    def setUp(self):
        self.broker = broker.Broker("127.0.0.1", 0, ":memory:", retry_seconds=0.5, retry_check_seconds=0.1,
                                    require_auth=False)  # sign-in: tests/test_auth.py
        _, self.broker_port = self.broker.start()

        # A throwaway web build so static serving can be tested without npm.
        self.static = tempfile.TemporaryDirectory()
        static_dir = Path(self.static.name).resolve()
        (static_dir / "index.html").write_text("<!doctype html><title>eSumbong</title>", encoding="utf-8")
        (static_dir / "assets").mkdir()
        (static_dir / "assets" / "app.js").write_text("console.log('hi')", encoding="utf-8")
        self._old_static = gateway.STATIC_DIR
        gateway.STATIC_DIR = static_dir

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.GatewayHandler)
        self.server.daemon_threads = True
        self.server.broker_addr = ("127.0.0.1", self.broker_port)
        self.server.sessions = gateway.SessionRegistry()
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.streams = []

    def tearDown(self):
        for s in self.streams:
            s.close()
        self.server.shutdown()
        self.server.server_close()
        self.broker.stop()
        gateway.STATIC_DIR = self._old_static
        self.static.cleanup()

    # --- helpers ---------------------------------------------------------------

    def request(self, method, path, body=None, raw=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=WAIT)
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        conn.request(method, path, body=data, headers=headers or {"Content-Type": "application/json"})
        res = conn.getresponse()
        payload = res.read()
        conn.close()
        ctype = res.getheader("Content-Type", "")
        return res.status, (json.loads(payload) if ctype.startswith("application/json") else payload), res

    def connect(self, client_id, role):
        status, body, _ = self.request("POST", "/api/connect", {"client_id": client_id, "role": role})
        self.assertEqual(status, 200, body)
        stream = EventStream(self.port, body["session"])
        self.streams.append(stream)
        # Round-trip SUBS so HELLO has been handled before the test goes on.
        self.send(body["session"], "SUBS")
        stream.next("SUBS")
        return body["session"], stream

    def send(self, session, line, expect=200):
        status, body, _ = self.request("POST", "/api/send", {"session": session, "line": line})
        self.assertEqual(status, expect, body)
        return body

    # --- /api/config -------------------------------------------------------------

    def test_config_exposes_shared_settings(self):
        status, body, _ = self.request("GET", "/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(body["categories"], list(config.CATEGORIES))
        self.assertEqual(body["urgent_categories"], list(config.URGENT_CATEGORIES))
        self.assertEqual(body["roles"], list(config.ROLES))
        self.assertEqual(body["district_name"], config.DISTRICT_NAME)
        self.assertEqual(len(body["barangays"]), len(config.BARANGAYS))
        self.assertIn({"id": "mh-del-pilar", "name": "M.H. del Pilar"}, body["barangays"])

    def test_unknown_api_endpoint_is_404(self):
        self.assertEqual(self.request("GET", "/api/nope")[0], 404)
        self.assertEqual(self.request("POST", "/api/nope", {})[0], 404)

    # --- /api/connect ------------------------------------------------------------

    def test_connect_rejects_bad_client_id(self):
        for bad in ["", "two words", "x" * 65, None, 42, "tab\there"]:
            status, body, _ = self.request("POST", "/api/connect", {"client_id": bad, "role": "resident"})
            self.assertEqual(status, 400, bad)
            self.assertIn("client_id", body["error"])

    def test_connect_rejects_unknown_role(self):
        status, body, _ = self.request("POST", "/api/connect", {"client_id": "x", "role": "admin"})
        self.assertEqual(status, 400)
        self.assertIn("role", body["error"])

    def test_connect_reports_unreachable_broker(self):
        self.broker.stop()
        self.server.broker_addr = ("127.0.0.1", 1)  # nothing listens on port 1
        status, body, _ = self.request("POST", "/api/connect", {"client_id": "x", "role": "resident"})
        self.assertEqual(status, 502)
        self.assertIn("cannot reach broker", body["error"])

    def test_sign_in_is_checked_at_connect(self):
        self.broker.require_auth = True
        self.broker.failed_login_delay = 0
        auth.reset_failures()
        store.save_user("tanod-a", "responder", auth.hash_secret("1234", iterations=1000), "san-roque")
        store.save_user(config.DESK_ID, "desk", auth.hash_secret("city-pass-1", iterations=1000))

        def connect(**body):
            return self.request("POST", "/api/connect", body)[:2]

        status, body = connect(client_id="tanod-a", role="responder", secret="1234")
        self.assertEqual(status, 200, body)
        status, body = connect(client_id=config.DESK_ID, role="desk", secret="city-pass-1")
        self.assertEqual(status, 200, body)
        status, body = connect(client_id="juan", role="resident")  # residents need no PIN
        self.assertEqual(status, 200, body)

        for bad in [dict(client_id="tanod-a", role="responder", secret="9999"),
                    dict(client_id="tanod-a", role="responder"),
                    dict(client_id="nobody", role="responder", secret="1234"),
                    dict(client_id="tanod-a", role="desk", secret="1234"),
                    dict(client_id=config.DESK_ID, role="desk", secret="wrong-pass")]:
            status, body = connect(**bad)
            self.assertEqual(status, 401, bad)
            self.assertIn("sign in", body["error"].replace("sign-in", "sign in"))
        status, _ = connect(client_id="tanod-a", role="responder", secret="has space")
        self.assertEqual(status, 400)

    def test_config_names_the_desk_account(self):
        self.assertEqual(self.request("GET", "/api/config")[1]["desk_id"], config.DESK_ID)

    def test_body_must_be_a_json_object(self):
        self.assertEqual(self.request("POST", "/api/connect", raw=b"not json")[0], 400)
        self.assertEqual(self.request("POST", "/api/connect", raw=b"[1, 2]")[0], 400)

    def test_body_size_limit(self):
        big = b"{" + b" " * (gateway.MAX_BODY_BYTES + 1) + b"}"
        self.assertEqual(self.request("POST", "/api/connect", raw=big)[0], 400)

    # --- /api/send -----------------------------------------------------------------

    def test_send_to_unknown_session_is_gone(self):
        self.send("no-such-session", "PING", expect=410)

    def test_send_rejects_multi_line_and_empty_lines(self):
        session, _ = self.connect("res-1", "resident")
        for bad in ["", "PING\nHELLO x desk", "PING\r", None, 7]:
            self.send(session, bad, expect=400)

    def test_send_rejects_commands_a_browser_may_not_send(self):
        session, _ = self.connect("res-1", "resident")
        for line in ["HELLO someone-else desk", "MSG 1 a NORMAL {}", "report lowercase"]:
            body = self.send(session, line, expect=400)
            self.assertIn("not allowed", body["error"])

    # --- bridge: the full report flow through the gateway ----------------------

    def test_report_flows_from_resident_to_responder_and_back(self):
        tanod, tanod_stream = self.connect("tanod-a", "responder")
        self.send(tanod, "SUB brgy.san-roque.purok-3.#")
        self.send(tanod, "SUBS")
        self.assertEqual(tanod_stream.next("SUBS"), "SUBS brgy.san-roque.purok-3.#")

        resident, res_stream = self.connect("res-1", "resident")
        self.send(resident, "REPORT brgy.san-roque.purok-3.noise N Loud karaoke")
        report_id = res_stream.next("REPORTED").split()[1]

        msg = tanod_stream.next("MSG").split(" ", 4)
        self.assertEqual(msg[2], "brgy.san-roque.purok-3.noise")
        self.assertEqual(msg[3], "NORMAL")
        body = json.loads(msg[4])
        self.assertEqual(body["report_id"], report_id)
        self.assertEqual(body["reporter"], "res-1")
        self.send(tanod, f"ACK {msg[1]}")

        self.send(tanod, f"STATUS {report_id} RESPONDING on the way")
        self.assertEqual(tanod_stream.next("UPDATED"), f"UPDATED {report_id} RESPONDING")
        update = res_stream.next("MSG").split(" ", 4)
        self.assertEqual(update[2], f"report.{report_id}.status")
        self.assertEqual(json.loads(update[4])["status"], "RESPONDING")

    def test_broker_errors_reach_the_browser(self):
        session, stream = self.connect("res-1", "resident")
        self.send(session, "REPORT brgy.not-a-barangay.purok-1.noise N hello")
        self.assertTrue(stream.next("ERR").startswith("ERR "))

    def test_closed_event_when_broker_link_ends(self):
        _, stream = self.connect("res-1", "resident")
        self.broker.stop()
        self.assertEqual(stream.next_event(), ("closed", "broker connection closed"))

    def test_disconnect_closes_session(self):
        session, _ = self.connect("res-1", "resident")
        status, body, _ = self.request("POST", "/api/disconnect", {"session": session})
        self.assertEqual((status, body), (200, {"ok": True}))
        self.assertIsNone(self.server.sessions.get(session))
        self.send(session, "PING", expect=410)

    def test_events_for_unknown_session_is_404(self):
        self.assertEqual(self.request("GET", "/api/events?session=nope")[0], 404)

    # --- static files ----------------------------------------------------------------

    def test_serves_index_and_assets(self):
        status, body, res = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"eSumbong", body)
        self.assertTrue(res.getheader("Content-Type").startswith("text/html"))
        status, body, res = self.request("GET", "/assets/app.js")
        self.assertEqual(status, 200)
        self.assertTrue(res.getheader("Content-Type").startswith("text/javascript"))

    def test_static_rejects_missing_files_and_path_traversal(self):
        self.assertEqual(self.request("GET", "/missing.js")[0], 404)
        self.assertEqual(self.request("GET", "/../config.py")[0], 404)
        self.assertEqual(self.request("GET", "/%2e%2e/config.py")[0], 404)
        self.assertEqual(self.request("GET", "/assets/../../gateway.py")[0], 404)


class IsTokenTest(unittest.TestCase):

    def test_is_token(self):
        self.assertTrue(gateway.is_token("tanod-a"))
        self.assertTrue(gateway.is_token("x" * 64))
        for bad in ["", "a b", "x" * 65, "a\nb", None, 3]:
            self.assertFalse(gateway.is_token(bad), bad)


class BrokerSessionTest(unittest.TestCase):
    """BrokerSession against a scripted fake broker, to control what it sends."""

    def setUp(self):
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.addr = self.listener.getsockname()

    def tearDown(self):
        self.listener.close()

    def fake_broker(self, script):
        """Accept one connection on a thread and run script(conn, reader) there."""
        result = {}

        def run():
            self.listener.settimeout(WAIT)
            conn, _ = self.listener.accept()
            conn.settimeout(WAIT)
            reader = conn.makefile("r", encoding="utf-8", newline="\n")
            result["conn"], result["reader"] = conn, reader
            result["seen"] = script(conn, reader)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, result

    @staticmethod
    def accept_hello(conn, reader):
        """Read HELLO and PING; answer PONG (the broker accepted HELLO)."""
        seen = [reader.readline(), reader.readline()]
        conn.sendall(b"PONG\n")
        return seen

    def test_login_sends_hello_with_secret_then_ping(self):
        thread, fake = self.fake_broker(self.accept_hello)
        session = gateway.BrokerSession("tanod-a", "responder", self.addr, secret="1234")
        thread.join(WAIT)
        self.assertEqual(fake["seen"], ["HELLO tanod-a responder 1234\n", "PING\n"])
        session.close()
        fake["conn"].close()

    def test_login_refused_raises_and_closes(self):
        def refuse(conn, reader):
            seen = [reader.readline(), reader.readline()]
            conn.sendall(b"ERR sign-in failed: wrong ID, PIN or password\n")
            return seen
        thread, fake = self.fake_broker(refuse)
        with self.assertRaises(gateway.LoginRefused) as ctx:
            gateway.BrokerSession("tanod-a", "responder", self.addr, secret="0000")
        self.assertIn("sign-in failed", str(ctx.exception))
        thread.join(WAIT)
        fake["conn"].close()

    def test_catch_up_lines_before_pong_are_kept(self):
        def catch_up(conn, reader):
            reader.readline(), reader.readline()
            conn.sendall(b"MSG m1 brgy.a.b.noise NORMAL {}\nPONG\n")
        thread, fake = self.fake_broker(catch_up)
        session = gateway.BrokerSession("tanod-a", "responder", self.addr, secret="1234")
        self.assertEqual(session.lines.get(timeout=WAIT), "MSG m1 brgy.a.b.noise NORMAL {}")
        session.close()
        thread.join(WAIT)
        fake["conn"].close()

    def test_answers_ping_and_forwards_other_lines(self):
        thread, fake = self.fake_broker(self.accept_hello)
        session = gateway.BrokerSession("res-1", "resident", self.addr)
        thread.join(WAIT)
        self.assertEqual(fake["seen"][0], "HELLO res-1 resident\n")  # no secret for residents
        fake["conn"].sendall(b"PING\nREPORTED abc123\n\n")
        self.assertEqual(fake["reader"].readline(), "PONG\n")  # answered by the gateway
        self.assertEqual(session.lines.get(timeout=WAIT), "REPORTED abc123")  # PING and blank line not forwarded
        session.close()
        fake["conn"].close()

    def test_queues_closed_sentinel_when_broker_hangs_up(self):
        thread, fake = self.fake_broker(self.accept_hello)
        session = gateway.BrokerSession("res-1", "resident", self.addr)
        thread.join(WAIT)
        fake["reader"].close()  # the makefile holds the socket open until it closes too
        fake["conn"].close()
        self.assertIs(session.lines.get(timeout=WAIT), gateway.CLOSED)
        self.assertTrue(session.closed.wait(WAIT))

    def test_close_is_idempotent(self):
        thread, fake = self.fake_broker(self.accept_hello)
        session = gateway.BrokerSession("res-1", "resident", self.addr)
        thread.join(WAIT)
        conn = fake["conn"]
        session.close()
        session.close()
        conn.close()


class SessionRegistryTest(unittest.TestCase):

    def test_add_get_remove_closes(self):
        class Fake:
            id = "s1"
            closed = False

            def close(self):
                self.closed = True

        reg, s = gateway.SessionRegistry(), Fake()
        reg.add(s)
        self.assertIs(reg.get("s1"), s)
        reg.remove("s1")
        self.assertIsNone(reg.get("s1"))
        self.assertTrue(s.closed)
        reg.remove("s1")  # removing twice is harmless


if __name__ == "__main__":
    unittest.main()
