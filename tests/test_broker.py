"""Integration tests for broker.py over real TCP sockets.
Run: python -m unittest discover -s tests"""

import json
import os
import socket
import sys
import time
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

    def drain(self):
        """PING and skip lines until PONG; ignores a connection that is gone."""
        try:
            self.send("PING")
            while self.recv() != "PONG":
                pass
        except (OSError, ConnectionError):
            pass

    def close(self):
        self.stream.close()
        self.sock.close()


def parse_msg(line):
    cmd, msg_id, topic, priority, body = line.split(" ", 4)
    assert cmd == "MSG", line
    return msg_id, topic, priority, json.loads(body)


class BrokerTestCase(unittest.TestCase):
    broker_kwargs = {}

    def setUp(self):
        self.broker = broker.Broker("127.0.0.1", 0, ":memory:", **self.broker_kwargs)
        _, self.port = self.broker.start()
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.drain()  # let the broker finish fan-out before the db closes
            c.close()
        self.broker.stop()

    def disconnect(self, c, client_id):
        """Close a client and wait until the broker has noticed."""
        c.close()
        self.clients.remove(c)
        deadline = time.time() + TIMEOUT
        while client_id in self.broker.online_clients():
            if time.time() > deadline:
                raise AssertionError(f"broker still thinks {client_id} is online")
            time.sleep(0.02)

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
                    "REPORT", "REPORT brgy.san-roque.p1.fire Y",
                    "REPORT brgy.san-roque.p1.earthquake N help",
                    "REPORT brgy.san-roque.*.fire N help",
                    "REPORT brgy.san-roque.advisory N help",
                    "REPORT brgy.san-roque.p1.fire MAYBE help",
                    "sub brgy.#"]:
            self.assertTrue(c.ask(bad).startswith("ERR "), bad)
        self.assertEqual(c.ask("PING"), "PONG")

    def test_line_too_long(self):
        c = self.client("res1", "resident")
        self.assertEqual(c.ask("REPORT brgy.san-roque.p1.fire N " + "x" * 5000), "ERR line too long")
        self.assertEqual(c.ask("PING"), "PONG")

    def test_disconnect_mid_line_does_not_crash_broker(self):
        c = self.client("res1", "resident")
        c.sock.sendall(b"REPORT brgy.san-roque.p1.fi")
        c.close()
        self.clients.remove(c)
        self.assertEqual(self.client("res2", "resident").ask("PING"), "PONG")


class ReportTest(BrokerTestCase):

    def test_report_fans_out_to_matching_subscribers(self):
        jaro = self.client("tanod-jaro", "responder")
        jaro.send("SUB brgy.san-roque.#")
        jaro.sync()
        fires = self.client("fire-watch", "responder")
        fires.send("SUB brgy.*.*.fire")
        fires.sync()
        molo = self.client("tanod-molo", "responder")
        molo.send("SUB brgy.tacas.#")
        molo.sync()

        res = self.client("juan", "resident")
        reply = res.ask("REPORT brgy.san-roque.purok-1.fire N smoke near the market")
        self.assertRegex(reply, r"^REPORTED [0-9a-f]{8}$")
        report_id = reply.split()[1]

        for sub in (jaro, fires):
            msg_id, topic, priority, body = parse_msg(sub.recv())
            self.assertEqual((topic, priority), ("brgy.san-roque.purok-1.fire", "URGENT"))
            self.assertEqual(body, {
                "report_id": report_id, "topic": "brgy.san-roque.purok-1.fire",
                "category": "fire", "priority": "URGENT",
                "description": "smoke near the market", "status": "RECEIVED",
                "escalated": True, "reporter": "juan",  # fire goes to the city at once
            })
        self.assertTrue(molo.nothing_pending())

        r = store.get_report(report_id)
        self.assertEqual((r["status"], r["barangay"], r["reporter_id"]), ("RECEIVED", "san-roque", "juan"))
        self.assertIn(f"report.{report_id}.status", store.subscriptions_for("juan"))

    def test_anonymous_report_hides_reporter(self):
        tanod = self.client("tanod1", "responder")
        tanod.send("SUB brgy.#")
        tanod.sync()
        res = self.client("juan", "resident")
        report_id = res.ask("REPORT brgy.san-roque.p2.noise Y loud karaoke").split()[1]
        line = tanod.recv()
        _, _, priority, body = parse_msg(line)
        self.assertEqual(priority, "NORMAL")
        self.assertNotIn("reporter", body)
        self.assertNotIn("juan", line)
        self.assertEqual(store.get_report(report_id)["reporter_id"], "juan")  # kept privately

    def test_topic_is_case_insensitive(self):
        res = self.client("juan", "resident")
        report_id = res.ask("REPORT Brgy.San-Roque.P1.Fire N help").split()[1]
        self.assertEqual(store.get_report(report_id)["topic"], "brgy.san-roque.p1.fire")

    def test_only_residents_report(self):
        tanod = self.client("tanod1", "responder")
        self.assertEqual(tanod.ask("REPORT brgy.san-roque.p1.fire N x"), "ERR only residents can REPORT")

    def test_unique_report_ids(self):
        res = self.client("juan", "resident")
        ids = {res.ask(f"REPORT brgy.san-roque.p1.noise N report {i}").split()[1] for i in range(20)}
        self.assertEqual(len(ids), 20)


class DeliveryTest(BrokerTestCase):

    def test_ack_marks_delivered_and_is_silent(self):
        tanod = self.client("tanod1", "responder")
        tanod.send("SUB brgy.#")
        tanod.sync()
        self.client("juan", "resident").ask("REPORT brgy.san-roque.p1.fire N help")
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
        self.disconnect(tanod, "tanod1")
        res = self.client("juan", "resident")
        res.ask("REPORT brgy.san-roque.p1.fire N help")
        res.sync()  # REPORTED is sent before fan-out; wait for fan-out to finish
        pending = store.pending_for("tanod1")
        self.assertEqual(len(pending), 1)
        self.assertEqual((pending[0]["attempts"], pending[0]["last_sent_at"]), (0, None))

    def test_unsub_stops_delivery(self):
        tanod = self.client("tanod1", "responder")
        tanod.send("SUB brgy.#")
        tanod.send("UNSUB brgy.#")
        tanod.sync()
        self.client("juan", "resident").ask("REPORT brgy.san-roque.p1.fire N help")
        self.assertTrue(tanod.nothing_pending())


class ScopeTest(BrokerTestCase):
    """Jaro's barangays only, and who may subscribe to what (escalation.py)."""

    def test_report_outside_jaro_rejected(self):
        res = self.client("juan", "resident")
        self.assertEqual(res.ask("REPORT brgy.molo.p1.fire N help"),
                         "ERR molo is not a barangay of Jaro, Iloilo City")
        self.assertTrue(res.ask("REPORT brgy.san-roque.near-jaro-plaza.noise N karaoke")
                        .startswith("REPORTED "))  # a landmark works as the purok level

    def test_desk_only_escalations(self):
        desk = self.client("city", "desk")
        desk.send("SUB city.iloilo.escalated.#")
        desk.send("SUB city.iloilo.escalated.tacas")
        self.assertEqual(desk.ask("SUBS"), "SUBS city.iloilo.escalated.# city.iloilo.escalated.tacas")
        for bad in ["brgy.#", "#", "report.*.status", "city.iloilo.escalated.molo"]:
            self.assertTrue(desk.ask(f"SUB {bad}").startswith("ERR "), bad)

    def test_responder_only_barangays(self):
        tanod = self.client("tanod1", "responder")
        for ok in ["brgy.#", "brgy.tacas.#", "brgy.*.*.fire", "brgy.tacas.advisory"]:
            tanod.send(f"SUB {ok}")
        self.assertEqual(len(tanod.ask("SUBS").split()), 5)
        for bad in ["city.iloilo.escalated.#", "#", "report.*.status", "brgy.sanroque.#"]:
            self.assertTrue(tanod.ask(f"SUB {bad}").startswith("ERR "), bad)

    def test_resident_only_advisories(self):
        res = self.client("juan", "resident")
        res.send("SUB brgy.tacas.advisory")
        self.assertEqual(res.ask("SUBS"), "SUBS brgy.tacas.advisory")
        # Reading other people's reports or status updates is not allowed.
        for bad in ["brgy.#", "brgy.tacas.#", "brgy.*.advisory", "report.*.status",
                    "report.abc12345.status", "brgy.molo.advisory"]:
            self.assertTrue(res.ask(f"SUB {bad}").startswith("ERR "), bad)

    def test_hello_drops_subscriptions_role_may_not_hold(self):
        store.add_subscription("city", "brgy.#")                       # saved by an older version
        store.add_subscription("city", "city.iloilo.escalated.#")
        self.client("city", "desk")
        self.assertEqual(store.subscriptions_for("city"), ["city.iloilo.escalated.#"])

    def test_resident_keeps_own_status_subscription(self):
        res = self.client("juan", "resident")
        report_id = res.ask("REPORT brgy.tacas.p1.noise N karaoke").split()[1]
        self.disconnect(res, "juan")
        self.client("juan", "resident")
        self.assertIn(f"report.{report_id}.status", store.subscriptions_for("juan"))


class HistoryTest(BrokerTestCase):
    """SUBS and HISTORY let a client that signs in again rebuild its view."""

    def hist(self, c):
        """Send HISTORY; return the HIST bodies and check the HISTEND count."""
        c.send("HISTORY")
        bodies = []
        while True:
            line = c.recv()
            if line.startswith("HISTEND "):
                self.assertEqual(int(line.split()[1]), len(bodies))
                return bodies
            cmd, topic, priority, body = line.split(" ", 3)
            self.assertEqual(cmd, "HIST", line)
            body = json.loads(body)
            self.assertEqual((topic, priority), (body["topic"], body["priority"]))
            bodies.append(body)

    def test_subs_lists_saved_patterns(self):
        tanod = self.client("tanod1", "responder")
        self.assertEqual(tanod.ask("SUBS"), "SUBS")
        tanod.send("SUB brgy.san-roque.#")
        tanod.send("SUB brgy.*.*.fire")
        self.assertEqual(tanod.ask("SUBS"), "SUBS brgy.san-roque.# brgy.*.*.fire")

    def test_history_has_matching_reports_oldest_first(self):
        res = self.client("juan", "resident")
        first = res.ask("REPORT brgy.san-roque.p1.fire N smoke").split()[1]
        res.ask("REPORT brgy.tacas.p1.noise N karaoke")
        second = res.ask("REPORT brgy.san-roque.p2.noise Y loud").split()[1]

        tanod = self.client("tanod1", "responder")
        tanod.send("SUB brgy.san-roque.#")  # subscribed after the reports were filed
        bodies = self.hist(tanod)
        self.assertEqual([b["report_id"] for b in bodies], [first, second])
        self.assertEqual(bodies[0]["reporter"], "juan")
        self.assertNotIn("reporter", bodies[1])   # anonymous stays anonymous
        self.assertNotIn("anonymous", bodies[1])  # only the reporter is told
        self.assertIsInstance(bodies[0]["created_at"], float)

    def test_resident_gets_own_reports(self):
        juan = self.client("juan", "resident")
        mine = juan.ask("REPORT brgy.san-roque.p1.fire Y smoke").split()[1]
        self.client("maria", "resident").ask("REPORT brgy.san-roque.p1.noise N karaoke")
        bodies = self.hist(juan)
        self.assertEqual([b["report_id"] for b in bodies], [mine])
        self.assertTrue(bodies[0]["anonymous"])

    def test_desk_gets_escalated_reports_only(self):
        res = self.client("juan", "resident")
        late = res.ask("REPORT brgy.san-roque.p1.fire N smoke").split()[1]
        res.ask("REPORT brgy.san-roque.p1.noise N karaoke")
        store.mark_escalated(late)
        desk = self.client("city", "desk")
        desk.send("SUB city.iloilo.escalated.#")
        bodies = self.hist(desk)
        self.assertEqual([b["report_id"] for b in bodies], [late])
        self.assertTrue(bodies[0]["escalated"])

    def test_history_is_not_a_delivery(self):
        tanod = self.client("tanod1", "responder")
        tanod.send("SUB brgy.#")
        self.client("juan", "resident").ask("REPORT brgy.san-roque.p1.fire N help")
        msg_id = parse_msg(tanod.recv())[0]
        tanod.send(f"ACK {msg_id}")
        self.assertEqual(len(self.hist(tanod)), 1)
        self.assertEqual(store.pending_for("tanod1"), [])

    def test_history_limit(self):
        res = self.client("juan", "resident")
        ids = [res.ask(f"REPORT brgy.san-roque.p1.noise N r{i}").split()[1]
               for i in range(broker.HISTORY_LIMIT + 5)]
        bodies = self.hist(res)
        self.assertEqual([b["report_id"] for b in bodies], ids[-broker.HISTORY_LIMIT:])

    def test_bad_usage(self):
        c = self.client("tanod1", "responder")
        self.assertTrue(c.ask("SUBS extra").startswith("ERR"))
        self.assertTrue(c.ask("HISTORY 10").startswith("ERR"))
        self.assertTrue(self.client().ask("HISTORY").startswith("ERR"))  # before HELLO


if __name__ == "__main__":
    unittest.main()
