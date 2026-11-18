"""Tests for the command-line clients: client.py, resident.py, responder.py, status.py.
Run: python -m unittest discover -s tests"""

import os
import queue
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import broker  # noqa: E402
import client  # noqa: E402
import resident  # noqa: E402
import responder  # noqa: E402
import status  # noqa: E402
import store  # noqa: E402

WAIT = 5


class Events:
    """A handler that queues (kind, data) so a test can wait for them."""

    def __init__(self):
        self.q = queue.Queue()

    def __call__(self, kind, data):
        self.q.put((kind, data))

    def next(self, *kinds):
        """The next event of one of these kinds, skipping others."""
        while True:
            kind, data = self.q.get(timeout=WAIT)
            if kind in kinds:
                return kind, data


class ClientTest(unittest.TestCase):

    def setUp(self):
        self.broker = broker.Broker("127.0.0.1", 0, ":memory:", retry_seconds=0.5, retry_check_seconds=0.1,
                                    require_auth=False)  # sign-in: tests/test_auth.py
        _, self.port = self.broker.start()
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.broker.stop()

    def connect(self, client_id, role, **kw):
        events = Events()
        c = client.Client(client_id, role, events, "127.0.0.1", self.port, **kw)
        self.clients.append(c)
        c.send("PING")
        events.next("PONG")  # HELLO has been handled
        return c, events

    def test_report_reaches_responder_and_status_reaches_resident(self):
        tanod, tanod_events = self.connect("tanod-a", "responder")
        tanod.send("SUB brgy.san-roque.#")
        juan, juan_events = self.connect("juan", "resident")
        juan.send(resident.parse_report("san-roque purok-3 noise anon Loud karaoke"))
        _, report_id = juan_events.next("REPORTED")
        _, msg = tanod_events.next("MSG")
        self.assertEqual(msg["body"]["report_id"], report_id)
        self.assertIn("NEW REPORT", client.describe(msg))
        self.assertIn("from anonymous", client.describe(msg))

        tanod.send(f"STATUS {report_id} RESPONDING on the way")
        _, msg = juan_events.next("MSG")
        self.assertIn("is now RESPONDING by tanod-a - on the way", client.describe(msg))

    def test_lost_ack_shows_retry_and_duplicate_ignored(self):
        tanod, events = self.connect("tanod-b", "responder")
        # Lose the first ACK on the way to the broker (a network fault).
        real_send, lost = tanod.send, []
        def lossy_send(line):
            if line.startswith("ACK ") and not lost:
                lost.append(line)
                return
            real_send(line)
        tanod.send = lossy_send
        tanod.send("SUB brgy.san-roque.#")
        juan, _ = self.connect("juan", "resident")
        juan.send("REPORT brgy.san-roque.purok-3.fire N smoke")
        _, msg = events.next("MSG")
        self.assertEqual(lost, [f"ACK {msg['msg_id']}"])
        _, dup = events.next("DUPLICATE")  # the broker's resend, same msg_id
        self.assertEqual(dup, msg["msg_id"])
        tanod.send("PING")
        events.next("PONG")
        self.assertEqual(store.get_delivery(msg["msg_id"], "tanod-b")["status"], "DELIVERED")


class ParseTest(unittest.TestCase):

    def test_parse_report(self):
        self.assertEqual(resident.parse_report("San-Roque Purok-3 FIRE smoke  near   chapel"),
                         "REPORT brgy.san-roque.purok-3.fire N smoke near chapel")
        self.assertEqual(resident.parse_report("tacas near-plaza noise anon karaoke"),
                         "REPORT brgy.tacas.near-plaza.noise Y karaoke")
        for bad in ["", "san-roque purok-3 noise", "molo p1 noise x", "san-roque p1 earthquake x",
                    "san-roque p1 noise anon"]:
            with self.assertRaises(ValueError, msg=bad):
                resident.parse_report(bad)

    def test_advisory_line(self):
        self.assertEqual(responder.advisory_line("san-roque urgent Flood warning"),
                         "ADVISORY san-roque URGENT Flood warning")
        self.assertEqual(responder.advisory_line("tacas Clean-up Saturday"),
                         "ADVISORY tacas NORMAL Clean-up Saturday")
        for bad in ["", "molo hi", "tacas", "tacas urgent"]:
            with self.assertRaises(ValueError, msg=bad):
                responder.advisory_line(bad)


class StatusScreenTest(unittest.TestCase):

    def test_no_database_yet(self):
        self.assertIn("No database yet", status.render(None))

    def test_empty_and_filled_screen(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "s.db")
            store.init_db(path)
            try:
                conn = status.connect(path)
                self.assertIn("No reports yet.", status.render(conn))
                conn.close()
                store.save_report("r1", "brgy.tacas.purok-1.noise", "tacas", "NORMAL", "karaoke", "juan", True)
                store.save_report("r2", "brgy.tacas.purok-2.fire", "tacas", "URGENT", "smoke", "maria", False)
                store.log_status("r2", "RESPONDING", "tanod-a", "on the way")
                conn = status.connect(path)
                screen = status.render(conn)
                conn.close()
            finally:
                store.close_db()
        self.assertIn("2 total", screen)
        self.assertIn("(anonymous)", screen)
        self.assertNotIn("juan", screen)   # anonymous reporter stays hidden
        self.assertIn("maria", screen)
        self.assertIn("on the way", screen)


if __name__ == "__main__":
    unittest.main()
