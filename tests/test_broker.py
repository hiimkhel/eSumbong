"""Integration tests for broker.py over real TCP sockets.
Run: python -m unittest discover -s tests"""

import json
import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import broker  # noqa: E402
import store  # noqa: E402

TIMEOUT = 3


class Client:
    """Minimal line client for tests."""

    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT)
        self.stream = self.sock.makefile("r", encoding="utf-8", newline="\n")

    def send(self, line):
        self.sock.sendall((line + "\n").encode("utf-8"))

    def recv(self):
        line = self.stream.readline()
        if not line:
            raise ConnectionError("broker closed the connection")
        return line.rstrip("\n")

    def ask(self, line):
        self.send(line)
        return self.recv()

    def sync(self):
        """Round-trip a PING so every earlier command has been processed."""
        self.assertLine(self.ask("PING"), "PONG")

    def assertLine(self, got, want):
        if got != want:
            raise AssertionError(f"expected {want!r}, got {got!r}")

    def nothing_pending(self, wait=0.3):
        self.sock.settimeout(wait)
        try:
            data = self.sock.recv(1, socket.MSG_PEEK)
            return not data
        except socket.timeout:
            return True
        finally:
            self.sock.settimeout(TIMEOUT)

    def close(self):
        self.stream.close()
        self.sock.close()


def parse_msg(line):
    cmd, msg_id, topic, priority, body = line.split(" ", 4)
    assert cmd == "MSG", line
    return msg_id, topic, priority, json.loads(body)


class BrokerTestCase(unittest.TestCase):

    def setUp(self):
        self.broker = broker.Broker("127.0.0.1", 0, ":memory:")
        _, self.port = self.broker.start()
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.broker.stop()

    def client(self, client_id=None, role=None):
        c = Client(self.port)
        self.clients.append(c)
        if client_id:
            c.send(f"HELLO {client_id} {role}")
            c.sync()
        return c


class HelloTest(BrokerTestCase):

    def test_hello_is_silent_on_success(self):
        c = self.client("res1", "resident")
        self.assertTrue(c.nothing_pending())
        self.assertEqual(self.broker.online_clients(), ["res1"])

    def test_commands_before_hello_rejected(self):
        c = self.client()
        self.assertTrue(c.ask("SUB brgy.#").startswith("ERR"))
        self.assertEqual(c.ask("PING"), "PONG")  # PING is fine before HELLO

    def test_bad_hello(self):
        c = self.client()
        self.assertTrue(c.ask("HELLO res1").startswith("ERR"))
        self.assertTrue(c.ask("HELLO res1 mayor").startswith("ERR"))
        c.send("HELLO res1 resident")
        self.assertTrue(c.ask("HELLO res1 resident").startswith("ERR already"))

    def test_reconnect_replaces_old_connection(self):
        old = self.client("tanod1", "responder")
        new = self.client("tanod1", "responder")
        with self.assertRaises((ConnectionError, OSError)):
            old.recv()
        self.assertEqual(new.ask("PING"), "PONG")
        self.assertEqual(self.broker.online_clients(), ["tanod1"])


class MalformedTest(BrokerTestCase):

    def test_errors_keep_connection_open(self):
        c = self.client("res1", "resident")
        for bad in ["FOO", "SUB", "SUB a b", "SUB brgy.#.fire", "UNSUB", "ACK",
                    "REPORT", "REPORT brgy.jaro.p1.fire Y",
                    "REPORT brgy.jaro.p1.earthquake N help",
                    "REPORT brgy.jaro.*.fire N help",
                    "REPORT brgy.jaro.advisory N help",
                    "REPORT brgy.jaro.p1.fire MAYBE help",
                    "sub brgy.#"]:
            self.assertTrue(c.ask(bad).startswith("ERR "), bad)
        self.assertEqual(c.ask("PING"), "PONG")

    def test_line_too_long(self):
        c = self.client("res1", "resident")
        self.assertEqual(c.ask("REPORT brgy.jaro.p1.fire N " + "x" * 5000), "ERR line too long")
        self.assertEqual(c.ask("PING"), "PONG")

    def test_disconnect_mid_line_does_not_crash_broker(self):
        c = self.client("res1", "resident")
        c.sock.sendall(b"REPORT brgy.jaro.p1.fi")
        c.close()
        self.clients.remove(c)
        self.assertEqual(self.client("res2", "resident").ask("PING"), "PONG")


class ReportTest(BrokerTestCase):

    def test_report_fans_out_to_matching_subscribers(self):
        jaro = self.client("tanod-jaro", "responder")
        jaro.send("SUB brgy.jaro.#")
        jaro.sync()
        fires = self.client("fire-desk", "desk")
        fires.send("SUB brgy.*.*.fire")
        fires.sync()
        molo = self.client("tanod-molo", "responder")
        molo.send("SUB brgy.molo.#")
        molo.sync()

        res = self.client("juan", "resident")
        reply = res.ask("REPORT brgy.jaro.purok-1.fire N smoke near the market")
        self.assertRegex(reply, r"^REPORTED [0-9a-f]{8}$")
        report_id = reply.split()[1]

        for sub in (jaro, fires):
            msg_id, topic, priority, body = parse_msg(sub.recv())
            self.assertEqual((topic, priority), ("brgy.jaro.purok-1.fire", "URGENT"))
            self.assertEqual(body, {
                "report_id": report_id, "topic": "brgy.jaro.purok-1.fire",
                "category": "fire", "priority": "URGENT",
                "description": "smoke near the market", "status": "RECEIVED",
                "escalated": False, "reporter": "juan",
            })
        self.assertTrue(molo.nothing_pending())

        r = store.get_report(report_id)
        self.assertEqual((r["status"], r["barangay"], r["reporter_id"]), ("RECEIVED", "jaro", "juan"))
        self.assertIn(f"report.{report_id}.status", store.subscriptions_for("juan"))

    def test_anonymous_report_hides_reporter(self):
        tanod = self.client("tanod1", "responder")
        tanod.send("SUB brgy.#")
        tanod.sync()
        res = self.client("juan", "resident")
        report_id = res.ask("REPORT brgy.jaro.p2.noise Y loud karaoke").split()[1]
        line = tanod.recv()
        _, _, priority, body = parse_msg(line)
        self.assertEqual(priority, "NORMAL")
        self.assertNotIn("reporter", body)
        self.assertNotIn("juan", line)
        self.assertEqual(store.get_report(report_id)["reporter_id"], "juan")  # kept privately

    def test_topic_is_case_insensitive(self):
        res = self.client("juan", "resident")
        report_id = res.ask("REPORT Brgy.Jaro.P1.Fire N help").split()[1]
        self.assertEqual(store.get_report(report_id)["topic"], "brgy.jaro.p1.fire")

    def test_only_residents_report(self):
        tanod = self.client("tanod1", "responder")
        self.assertEqual(tanod.ask("REPORT brgy.jaro.p1.fire N x"), "ERR only residents can REPORT")

    def test_unique_report_ids(self):
        res = self.client("juan", "resident")
        ids = {res.ask(f"REPORT brgy.jaro.p1.noise N report {i}").split()[1] for i in range(20)}
        self.assertEqual(len(ids), 20)


class DeliveryTest(BrokerTestCase):

    def test_ack_marks_delivered_and_is_silent(self):
        tanod = self.client("tanod1", "responder")
        tanod.send("SUB brgy.#")
        tanod.sync()
        self.client("juan", "resident").ask("REPORT brgy.jaro.p1.fire N help")
        msg_id = parse_msg(tanod.recv())[0]
        self.assertEqual(store.get_delivery(msg_id, "tanod1")["status"], "PENDING")
        tanod.send(f"ACK {msg_id}")
        tanod.send(f"ACK {msg_id}")       # duplicate ACK is ignored
        tanod.send("ACK not-a-real-id")   # unknown ACK is ignored
        tanod.sync()
        d = store.get_delivery(msg_id, "tanod1")
        self.assertEqual((d["status"], d["attempts"]), ("DELIVERED", 1))

    def test_offline_subscriber_gets_pending_row(self):
        tanod = self.client("tanod1", "responder")
        tanod.send("SUB brgy.#")
        tanod.sync()
        tanod.close()
        self.clients.remove(tanod)
        res = self.client("juan", "resident")
        res.ask("REPORT brgy.jaro.p1.fire N help")
        res.sync()  # REPORTED is sent before fan-out; wait for fan-out to finish
        pending = store.pending_for("tanod1")
        self.assertEqual(len(pending), 1)
        self.assertEqual((pending[0]["attempts"], pending[0]["last_sent_at"]), (0, None))

    def test_unsub_stops_delivery(self):
        tanod = self.client("tanod1", "responder")
        tanod.send("SUB brgy.#")
        tanod.send("UNSUB brgy.#")
        tanod.sync()
        self.client("juan", "resident").ask("REPORT brgy.jaro.p1.fire N help")
        self.assertTrue(tanod.nothing_pending())

    def test_status_not_available_yet(self):
        tanod = self.client("tanod1", "responder")
        self.assertTrue(tanod.ask("STATUS abc RESPONDING on the way").startswith("ERR"))


if __name__ == "__main__":
    unittest.main()
