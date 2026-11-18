"""Pass 3 tests: ACK, retry, offline catch-up, broker restart, client crash.
These mirror fault tests 1-4 in FAULT_TEST_REPORT.md.
Run: python -m unittest discover -s tests"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import broker  # noqa: E402
import store  # noqa: E402
from test_broker import BrokerTestCase, Client, parse_msg  # noqa: E402

FAST_RETRY = {"retry_seconds": 0.5, "retry_check_seconds": 0.1}


def subscribe(test, client_id, pattern="brgy.#"):
    c = test.client(client_id, "responder")
    c.send(f"SUB {pattern}")
    c.sync()
    return c


def report(test, text="help", client_id="juan"):
    res = test.client(client_id, "resident")
    report_id = res.ask(f"REPORT brgy.san-roque.p1.fire N {text}").split()[1]
    res.sync()  # fan-out has finished once PING is answered
    return report_id


class OfflineCatchUpTest(BrokerTestCase):
    """Fault test 1: a subscriber that was offline gets missed messages on HELLO."""

    def test_catch_up_in_order(self):
        tanod = subscribe(self, "tanod1")
        self.disconnect(tanod, "tanod1")
        first = report(self, "first", "juan")
        second = report(self, "second", "maria")

        tanod = self.client()
        self.clients.append(tanod)
        tanod.send("HELLO tanod1 responder")
        bodies = [parse_msg(tanod.recv()) for _ in range(2)]
        self.assertEqual([b[3]["report_id"] for b in bodies], [first, second])
        for msg_id, *_ in bodies:
            tanod.send(f"ACK {msg_id}")
        tanod.sync()
        self.assertEqual(store.pending_for("tanod1"), [])

    def test_nothing_pending_means_no_catch_up(self):
        tanod = subscribe(self, "tanod1")
        self.disconnect(tanod, "tanod1")
        tanod = self.client("tanod1", "responder")
        self.assertTrue(tanod.nothing_pending())

    def test_acked_messages_not_resent_on_reconnect(self):
        tanod = subscribe(self, "tanod1")
        report(self)
        tanod.send(f"ACK {parse_msg(tanod.recv())[0]}")
        tanod.sync()
        self.disconnect(tanod, "tanod1")
        tanod = self.client("tanod1", "responder")
        self.assertTrue(tanod.nothing_pending())


class RetryTest(BrokerTestCase):
    """Fault test 2: a lost ACK makes the broker resend with the same msg_id."""
    broker_kwargs = FAST_RETRY

    def test_resend_until_ack(self):
        tanod = subscribe(self, "tanod1")
        report(self)
        first = parse_msg(tanod.recv())
        # No ACK: the broker must resend the identical message.
        again = parse_msg(tanod.recv())
        self.assertEqual(again, first)
        tanod.send(f"ACK {first[0]}")
        tanod.sync()
        self.assertTrue(tanod.nothing_pending(wait=1.2))  # no more resends
        d = store.get_delivery(first[0], "tanod1")
        self.assertEqual(d["status"], "DELIVERED")
        self.assertGreaterEqual(d["attempts"], 2)

    def test_retry_skips_offline_clients(self):
        tanod = subscribe(self, "tanod1")
        report(self)
        msg_id = parse_msg(tanod.recv())[0]
        self.disconnect(tanod, "tanod1")
        attempts = store.get_delivery(msg_id, "tanod1")["attempts"]
        time.sleep(1.2)  # two retry windows
        self.assertEqual(store.get_delivery(msg_id, "tanod1")["attempts"], attempts)

    def test_acked_subscriber_not_resent_while_other_is(self):
        a = subscribe(self, "tanod-a")
        b = subscribe(self, "tanod-b")
        report(self)
        msg_id = parse_msg(a.recv())[0]
        a.send(f"ACK {msg_id}")
        a.sync()
        self.assertEqual(parse_msg(b.recv())[0], msg_id)   # live send
        self.assertEqual(parse_msg(b.recv())[0], msg_id)   # retry
        self.assertTrue(a.nothing_pending(wait=0.8))


class ClientCrashTest(BrokerTestCase):
    """Fault test 4: a client that crashes before ACKing gets the message again."""

    def test_crash_before_ack_redelivers_on_reconnect(self):
        tanod = subscribe(self, "tanod1")
        report(self)
        msg_id = parse_msg(tanod.recv())[0]
        self.disconnect(tanod, "tanod1")  # crash: no ACK sent

        # The broker keeps serving everyone else.
        self.assertEqual(self.client("other", "resident").ask("PING"), "PONG")

        tanod = self.client()
        self.clients.append(tanod)
        tanod.send("HELLO tanod1 responder")
        self.assertEqual(parse_msg(tanod.recv())[0], msg_id)


class RestartTest(unittest.TestCase):
    """Fault test 3: pending deliveries survive a broker restart."""

    def test_restart_keeps_pending_deliveries(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db = os.path.join(tmp, "sumbong.db")

            b1 = broker.Broker("127.0.0.1", 0, db, require_auth=False)
            _, port = b1.start()
            tanod = Client(port)
            tanod.send("HELLO tanod1 responder")
            tanod.send("SUB brgy.san-roque.#")
            tanod.sync()
            tanod.close()
            res = Client(port)
            res.send("HELLO juan resident")
            report_id = res.ask("REPORT brgy.san-roque.p1.fire N smoke").split()[1]
            res.sync()
            res.close()
            b1.stop()

            b2 = broker.Broker("127.0.0.1", 0, db, require_auth=False)
            _, port = b2.start()
            try:
                self.assertEqual(store.get_report(report_id)["status"], "RECEIVED")
                tanod = Client(port)
                tanod.send("HELLO tanod1 responder")
                msg_id, _, _, body = parse_msg(tanod.recv())
                self.assertEqual(body["report_id"], report_id)
                tanod.send(f"ACK {msg_id}")
                tanod.sync()
                self.assertEqual(store.get_delivery(msg_id, "tanod1")["status"], "DELIVERED")
                tanod.close()
            finally:
                b2.stop()


class RetryThreadTest(unittest.TestCase):
    """store.start_retry_thread on its own, without sockets."""

    def test_calls_resend_for_due_rows_and_stops(self):
        import threading
        store.init_db(":memory:")
        try:
            store.save_message("m1", "r1", "t", "URGENT", "{}", recipients=["c1"])
            store.mark_sent("m1", "c1", now=time.time() - 10)
            seen = []
            stop = threading.Event()
            t = store.start_retry_thread(lambda row: seen.append(row["msg_id"]), stop,
                                         retry_seconds=5, check_every=0.05)
            time.sleep(0.3)
            stop.set()
            t.join(timeout=1)
            self.assertFalse(t.is_alive())
            self.assertIn("m1", seen)
        finally:
            store.close_db()


if __name__ == "__main__":
    unittest.main()
