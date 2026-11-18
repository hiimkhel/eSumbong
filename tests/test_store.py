"""Unit tests for store.py. Run: python -m unittest discover -s tests"""

import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import store  # noqa: E402


def _report(rid="r1", topic="brgy.jaro.purok-1.fire", anonymous=0, created_at=1000.0):
    store.save_report(rid, topic, "jaro", "URGENT", "smoke near the market",
                      "res1", anonymous, created_at=created_at)


class StoreTestCase(unittest.TestCase):

    def setUp(self):
        store.init_db(":memory:")

    def tearDown(self):
        store.close_db()


class SchemaTest(StoreTestCase):

    def test_tables_exist(self):
        rows = store._db().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        names = {r["name"] for r in rows}
        for t in ("reports", "messages", "subscriptions", "deliveries", "status_log"):
            self.assertIn(t, names)

    def test_indexes_exist(self):
        rows = store._db().execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
        names = {r["name"] for r in rows}
        self.assertIn("idx_deliveries_client_status", names)
        self.assertIn("idx_reports_status_escalated", names)

    def test_requires_init(self):
        store.close_db()
        with self.assertRaises(RuntimeError):
            store.get_report("x")


class ReportsTest(StoreTestCase):

    def test_save_and_get(self):
        _report(anonymous=1)
        r = store.get_report("r1")
        self.assertEqual(r["status"], "RECEIVED")
        self.assertEqual(r["anonymous"], 1)
        self.assertEqual(r["escalated"], 0)
        self.assertIsNone(r["assigned_to"])
        self.assertEqual(r["created_at"], 1000.0)
        self.assertIsNone(store.get_report("nope"))

    def test_duplicate_id_rejected(self):
        _report()
        with self.assertRaises(store.sqlite3.IntegrityError):
            _report()

    def test_bad_priority(self):
        with self.assertRaises(ValueError):
            store.save_report("r9", "t", "jaro", "HIGH", "d", "res1", 0)

    def test_status_update_assigns_first_responder(self):
        _report()
        r = store.update_report_status("r1", "RESPONDING", "tanod1")
        self.assertEqual((r["status"], r["assigned_to"]), ("RESPONDING", "tanod1"))
        r = store.update_report_status("r1", "RESPONDING", "tanod2")
        self.assertEqual(r["assigned_to"], "tanod1")
        r = store.update_report_status("r1", "RESOLVED", "tanod2")
        self.assertEqual((r["status"], r["assigned_to"]), ("RESOLVED", "tanod1"))

    def test_status_update_unknown_or_invalid(self):
        self.assertIsNone(store.update_report_status("nope", "RESOLVED", "t"))
        _report()
        with self.assertRaises(ValueError):
            store.update_report_status("r1", "DONE", "t")

    def test_default_timestamp_is_now(self):
        store.save_report("r2", "t", "jaro", "NORMAL", "d", "res1", 0)
        self.assertAlmostEqual(store.get_report("r2")["created_at"], store.time.time(), delta=5)


class EscalationTest(StoreTestCase):

    def test_reports_to_escalate(self):
        _report("old", created_at=1000.0)
        _report("new", created_at=1100.0)
        _report("busy", created_at=900.0)
        store.update_report_status("busy", "RESPONDING", "tanod1")
        due = [r["report_id"] for r in store.reports_to_escalate(120, now=1130.0)]
        self.assertEqual(due, ["old"])

    def test_mark_escalated_exactly_once(self):
        _report()
        self.assertTrue(store.mark_escalated("r1"))
        self.assertFalse(store.mark_escalated("r1"))
        self.assertEqual(store.get_report("r1")["escalated"], 1)
        self.assertEqual(store.reports_to_escalate(0, now=99999.0), [])

    def test_mark_escalated_skips_resolved_report(self):
        _report()
        store.update_report_status("r1", "RESOLVED", "tanod1")
        self.assertFalse(store.mark_escalated("r1"))

    def test_mark_escalated_allows_unresolved_report(self):
        _report()
        store.update_report_status("r1", "RESPONDING", "tanod1")
        self.assertTrue(store.mark_escalated("r1"))

    def test_reports_unresolved(self):
        _report("slow", created_at=1000.0)
        _report("recent", created_at=1100.0)
        _report("waiting", created_at=900.0)   # never answered: not this query's job
        _report("done", created_at=900.0)
        for rid in ("slow", "recent", "done"):
            store.update_report_status(rid, "RESPONDING", "tanod1")
        store.update_report_status("done", "RESOLVED", "tanod1")
        due = [r["report_id"] for r in store.reports_unresolved(120, now=1130.0)]
        self.assertEqual(due, ["slow"])

    def test_mark_escalated_race(self):
        _report()
        results = []
        threads = [threading.Thread(target=lambda: results.append(store.mark_escalated("r1")))
                   for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(True), 1)


class SubscriptionsTest(StoreTestCase):

    def test_add_remove(self):
        self.assertTrue(store.add_subscription("tanod1", "brgy.jaro.#"))
        self.assertFalse(store.add_subscription("tanod1", "brgy.jaro.#"))
        store.add_subscription("tanod1", "city.iloilo.escalated.*")
        self.assertEqual(store.subscriptions_for("tanod1"),
                         ["brgy.jaro.#", "city.iloilo.escalated.*"])
        self.assertTrue(store.remove_subscription("tanod1", "brgy.jaro.#"))
        self.assertFalse(store.remove_subscription("tanod1", "brgy.jaro.#"))
        self.assertEqual(store.subscriptions_for("tanod1"), ["city.iloilo.escalated.*"])

    def test_subscribers_for_topic(self):
        store.add_subscription("tanod1", "brgy.jaro.#")
        store.add_subscription("tanod2", "brgy.jaro.*.fire")
        store.add_subscription("tanod2", "brgy.jaro.purok-1.*")  # overlaps: still once
        store.add_subscription("tanod3", "brgy.molo.#")
        self.assertEqual(store.subscribers_for("brgy.jaro.purok-1.fire"), ["tanod1", "tanod2"])
        self.assertEqual(store.subscribers_for("brgy.molo.purok-1.noise"), ["tanod3"])
        self.assertEqual(store.subscribers_for("city.iloilo.escalated.jaro"), [])


class DeliveriesTest(StoreTestCase):

    def setUp(self):
        super().setUp()
        _report()
        store.save_message("m1", "r1", "brgy.jaro.purok-1.fire", "URGENT", '{"a": 1}',
                           recipients=["tanod1", "tanod2"], created_at=1000.0)

    def test_message_saved_with_pending_deliveries(self):
        self.assertEqual(store.get_message("m1")["body"], '{"a": 1}')
        d = store.get_delivery("m1", "tanod1")
        self.assertEqual((d["status"], d["attempts"], d["last_sent_at"]), ("PENDING", 0, None))
        self.assertFalse(store.add_delivery("m1", "tanod1"))
        self.assertTrue(store.add_delivery("m1", "tanod3"))

    def test_sent_then_ack(self):
        self.assertTrue(store.mark_sent("m1", "tanod1", now=1001.0))
        store.mark_sent("m1", "tanod1", now=1006.0)
        d = store.get_delivery("m1", "tanod1")
        self.assertEqual((d["attempts"], d["last_sent_at"]), (2, 1006.0))
        self.assertTrue(store.mark_delivered("m1", "tanod1"))
        self.assertFalse(store.mark_delivered("m1", "tanod1"))  # duplicate ACK
        self.assertFalse(store.mark_delivered("zz", "tanod1"))  # unknown msg
        self.assertEqual(store.get_delivery("m1", "tanod1")["status"], "DELIVERED")
        self.assertFalse(store.mark_sent("m1", "tanod1"))  # no resend after ACK

    def test_ack_only_affects_that_client(self):
        store.mark_delivered("m1", "tanod1")
        self.assertEqual(store.get_delivery("m1", "tanod2")["status"], "PENDING")

    def test_pending_for_client_in_order(self):
        store.save_message("m0", "r1", "t", "URGENT", "{}", recipients=["tanod1"],
                           created_at=999.0)
        store.save_message("m2", "r1", "t", "URGENT", "{}", recipients=["tanod1"],
                           created_at=1002.0)
        store.mark_delivered("m0", "tanod1")
        rows = store.pending_for("tanod1")
        self.assertEqual([r["msg_id"] for r in rows], ["m1", "m2"])
        self.assertEqual(rows[0]["topic"], "brgy.jaro.purok-1.fire")
        self.assertEqual(rows[0]["priority"], "URGENT")
        self.assertEqual(store.pending_for("nobody"), [])

    def test_due_for_retry(self):
        store.mark_sent("m1", "tanod1", now=1000.0)
        store.mark_sent("m1", "tanod2", now=1004.0)
        due = store.due_for_retry(5, now=1006.0)
        self.assertEqual([(r["msg_id"], r["client_id"]) for r in due], [("m1", "tanod1")])
        store.mark_delivered("m1", "tanod1")
        self.assertEqual(store.due_for_retry(5, now=1006.0), [])

    def test_never_sent_not_retried(self):
        self.assertEqual(store.due_for_retry(5, now=99999.0), [])


class StatusLogTest(StoreTestCase):

    def test_history(self):
        _report()
        store.log_status("r1", "RESPONDING", "tanod1", "on the way", at=1010.0)
        store.log_status("r1", "RESOLVED", "tanod1", "fire out", at=1050.0)
        h = store.status_history("r1")
        self.assertEqual([(x["status"], x["note"]) for x in h],
                         [("RESPONDING", "on the way"), ("RESOLVED", "fire out")])
        self.assertEqual(store.status_history("nope"), [])


class PersistenceTest(unittest.TestCase):
    """Data survives closing and reopening the file (broker restart)."""

    def test_restart_keeps_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sumbong.db")
            store.init_db(path)
            _report()
            store.add_subscription("tanod1", "brgy.jaro.#")
            store.save_message("m1", "r1", "brgy.jaro.purok-1.fire", "URGENT", "{}",
                               recipients=["tanod1"])
            store.close_db()

            store.init_db(path)  # "restart"
            try:
                self.assertIsNotNone(store.get_report("r1"))
                self.assertEqual(store.subscriptions_for("tanod1"), ["brgy.jaro.#"])
                self.assertEqual([r["msg_id"] for r in store.pending_for("tanod1")], ["m1"])
            finally:
                store.close_db()


class ConcurrencyTest(StoreTestCase):

    def test_parallel_writes(self):
        _report()

        def worker(n):
            for i in range(25):
                mid = f"m{n}-{i}"
                store.save_message(mid, "r1", "t", "URGENT", "{}", recipients=[f"c{n}"])
                store.mark_sent(mid, f"c{n}")
                store.mark_delivered(mid, f"c{n}")

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        count = store._db().execute(
            "SELECT COUNT(*) FROM deliveries WHERE status = 'DELIVERED'").fetchone()[0]
        self.assertEqual(count, 200)


if __name__ == "__main__":
    unittest.main()
