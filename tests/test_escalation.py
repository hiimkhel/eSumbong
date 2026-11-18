"""Tests for escalation.py: STATUS updates and escalation over real TCP sockets.
Run: python -m unittest discover -s tests"""

import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import escalation  # noqa: E402
import store  # noqa: E402
from test_broker import BrokerTestCase, parse_msg  # noqa: E402


class StatusTest(BrokerTestCase):

    def setUp(self):
        super().setUp()
        self.tanod = self.client("tanod1", "responder")
        self.tanod.send("SUB brgy.san-roque.#")
        self.tanod.sync()
        self.res = self.client("juan", "resident")
        self.report_id = self.res.ask("REPORT brgy.san-roque.p1.noise N karaoke").split()[1]
        self.ack(self.tanod)  # the new report itself
        # From here on tanod1 only acts; its replies are then the next line it reads.
        self.tanod.send("UNSUB brgy.san-roque.#")
        self.tanod.sync()

    def watcher(self):
        """Another responder covering Jaro, to see what responders receive."""
        w = self.client("tanod-watch", "responder")
        w.send("SUB brgy.san-roque.#")
        w.sync()
        return w

    def ack(self, c):
        msg_id, topic, priority, body = parse_msg(c.recv())
        c.send(f"ACK {msg_id}")
        return topic, priority, body

    def test_responding_reaches_resident_and_responders(self):
        watch = self.watcher()
        reply = self.tanod.ask(f"STATUS {self.report_id} RESPONDING on the way")
        self.assertEqual(reply, f"UPDATED {self.report_id} RESPONDING")

        topic, priority, body = self.ack(self.res)
        self.assertEqual((topic, priority), (f"report.{self.report_id}.status", "NORMAL"))
        self.assertEqual((body["status"], body["note"], body["updated_by"]),
                         ("RESPONDING", "on the way", "tanod1"))

        topic, _, body = self.ack(watch)  # responders see it on the incident topic
        self.assertEqual((topic, body["status"]), ("brgy.san-roque.p1.noise", "RESPONDING"))

        r = store.get_report(self.report_id)
        self.assertEqual((r["status"], r["assigned_to"]), ("RESPONDING", "tanod1"))
        log = store.status_history(self.report_id)
        self.assertEqual([(h["status"], h["responder_id"], h["note"]) for h in log],
                         [("RESPONDING", "tanod1", "on the way")])

    def test_full_lifecycle(self):
        self.tanod.ask(f"STATUS {self.report_id} RESPONDING on the way")
        self.tanod.ask(f"STATUS {self.report_id} RESOLVED fire is out")
        statuses = [self.ack(self.res)[2]["status"] for _ in range(2)]
        self.assertEqual(statuses, ["RESPONDING", "RESOLVED"])
        self.assertEqual(store.get_report(self.report_id)["status"], "RESOLVED")

    def test_resolve_straight_from_received(self):
        self.assertEqual(self.tanod.ask(f"STATUS {self.report_id} RESOLVED false alarm"),
                         f"UPDATED {self.report_id} RESOLVED")

    def test_no_going_back_or_repeating(self):
        self.tanod.ask(f"STATUS {self.report_id} RESPONDING on the way")
        self.assertEqual(self.tanod.ask(f"STATUS {self.report_id} RESPONDING again"),
                         f"ERR report {self.report_id} is already RESPONDING")
        self.tanod.ask(f"STATUS {self.report_id} RESOLVED done")
        self.assertEqual(self.tanod.ask(f"STATUS {self.report_id} RESPONDING back"),
                         f"ERR report {self.report_id} is already RESOLVED")
        self.assertEqual(len(store.status_history(self.report_id)), 2)

    def test_first_responder_stays_assigned(self):
        other = self.client("tanod2", "responder")
        self.tanod.ask(f"STATUS {self.report_id} RESPONDING on the way")
        self.assertTrue(other.ask(f"STATUS {self.report_id} RESPONDING me too").startswith("ERR"))
        other.ask(f"STATUS {self.report_id} RESOLVED handled")
        self.assertEqual(store.get_report(self.report_id)["assigned_to"], "tanod1")

    def test_desk_may_update(self):
        desk = self.client("city", "desk")
        self.assertTrue(desk.ask(f"STATUS {self.report_id} RESOLVED closed").startswith("UPDATED"))

    def test_note_is_optional(self):
        self.tanod.ask(f"STATUS {self.report_id} RESOLVED")
        self.assertEqual(self.ack(self.res)[2]["note"], "")

    def test_refused_updates(self):
        self.assertEqual(self.res.ask(f"STATUS {self.report_id} RESOLVED x"),
                         "ERR only responders and the desk can send STATUS")
        for bad in ["STATUS", f"STATUS {self.report_id}",
                    f"STATUS {self.report_id} RECEIVED x",
                    f"STATUS {self.report_id} DONE x",
                    "STATUS nope RESOLVED x"]:
            self.assertTrue(self.tanod.ask(bad).startswith("ERR "), bad)
        self.assertEqual(store.get_report(self.report_id)["status"], "RECEIVED")

    def test_anonymous_reporter_stays_hidden(self):
        watch = self.watcher()
        report_id = self.res.ask("REPORT brgy.san-roque.p2.noise Y karaoke").split()[1]
        self.ack(watch)
        self.tanod.ask(f"STATUS {report_id} RESPONDING on the way")
        line = watch.recv()
        self.assertNotIn("juan", line)
        self.assertNotIn("reporter", parse_msg(line)[3])

    def test_offline_resident_gets_update_on_reconnect(self):
        self.disconnect(self.res, "juan")
        self.tanod.ask(f"STATUS {self.report_id} RESPONDING on the way")
        res = self.client()
        self.clients.append(res)
        res.send("HELLO juan resident")
        _, _, body = self.ack(res)
        self.assertEqual(body["status"], "RESPONDING")

    def test_history_drops_reports_resolved_long_ago(self):
        self.tanod.ask(f"STATUS {self.report_id} RESOLVED settled")
        self.ack(self.res)
        self.assertEqual(self.res.ask("HISTORY").split()[0], "HIST")  # just resolved: still shown
        self.assertEqual(self.res.recv(), "HISTEND 1")
        with mock.patch.object(config, "RESOLVED_HIDE_SECONDS", -1):
            self.assertEqual(self.res.ask("HISTORY"), "HISTEND 0")
        self.assertEqual(store.get_report(self.report_id)["status"], "RESOLVED")  # never deleted

    def test_history_shows_latest_note(self):
        self.tanod.ask(f"STATUS {self.report_id} RESPONDING on the way")
        self.ack(self.res)
        self.res.send("HISTORY")
        body = parse_msg("MSG x " + self.res.recv().split(" ", 1)[1])[3]
        self.assertEqual((body["status"], body["note"]), ("RESPONDING", "on the way"))


class WithdrawTest(BrokerTestCase):
    """A resident takes back their own report while nobody has responded."""

    def setUp(self):
        super().setUp()
        self.watch = self.client("tanod-watch", "responder")
        self.watch.send("SUB brgy.san-roque.#")
        self.watch.sync()
        self.res = self.client("juan", "resident")

    def ack(self, c):
        msg_id, topic, priority, body = parse_msg(c.recv())
        c.send(f"ACK {msg_id}")
        return topic, priority, body

    def file(self, category="noise", anon="N"):
        report_id = self.res.ask(f"REPORT brgy.san-roque.p1.{category} {anon} help").split()[1]
        self.ack(self.watch)
        return report_id

    def test_withdraw_tells_responders(self):
        report_id = self.file()
        self.assertEqual(self.res.ask(f"WITHDRAW {report_id} sent twice by mistake"),
                         f"UPDATED {report_id} WITHDRAWN")
        _, _, body = self.ack(self.watch)
        self.assertEqual((body["status"], body["note"]), ("WITHDRAWN", "sent twice by mistake"))
        self.assertNotIn("updated_by", body)
        self.assertEqual(store.get_report(report_id)["status"], "WITHDRAWN")  # kept, not deleted
        self.assertEqual([h["status"] for h in store.status_history(report_id)], ["WITHDRAWN"])

    def test_anonymous_withdrawal_stays_anonymous(self):
        report_id = self.file(anon="Y")
        self.res.ask(f"WITHDRAW {report_id}")
        line = self.watch.recv()
        self.assertNotIn("juan", line)
        self.assertEqual(parse_msg(line)[3]["note"], "Withdrawn by the resident")

    def test_only_own_report_and_only_before_response(self):
        report_id = self.file()
        other = self.client("maria", "resident")
        self.assertEqual(other.ask(f"WITHDRAW {report_id}"), f"ERR you did not file report {report_id}")
        self.assertEqual(other.ask("WITHDRAW nope"), "ERR you did not file report nope")  # same answer
        self.assertTrue(self.watch.ask(f"WITHDRAW {report_id}").startswith("ERR only the resident"))
        self.watch.ask(f"STATUS {report_id} RESPONDING on the way")
        self.ack(self.watch)  # its own update on the incident topic
        self.ack(self.res)
        self.assertTrue(self.res.ask(f"WITHDRAW {report_id}").startswith(
            f"ERR report {report_id} is already RESPONDING"))

    def test_withdrawn_report_is_closed(self):
        report_id = self.file()
        self.res.ask(f"WITHDRAW {report_id}")
        self.ack(self.watch)
        self.assertEqual(self.watch.ask(f"STATUS {report_id} RESPONDING on the way"),
                         f"ERR report {report_id} is already WITHDRAWN")
        self.assertEqual(escalation.check_once(self.broker.publish_escalation,
                                               now=time.time() + config.UNRESOLVED_ESCALATE_SECONDS + 100), 0)

    def test_escalated_withdrawal_tells_desk(self):
        desk = self.client("city", "desk")
        desk.send("SUB city.iloilo.escalated.#")
        desk.sync()
        report_id = self.file("fire")
        self.ack(desk)  # the immediate escalation
        self.res.ask(f"WITHDRAW {report_id} false alarm")
        topic, _, body = self.ack(desk)
        self.assertEqual((topic, body["status"]), ("city.iloilo.escalated.san-roque", "WITHDRAWN"))


class EscalationTest(BrokerTestCase):
    """Escalation to the city desk. Timers are tested with check_once(now=...)
    so no test has to wait a minute."""

    def setUp(self):
        super().setUp()
        self.desk = self.client("city", "desk")
        self.desk.send("SUB city.iloilo.escalated.#")
        self.desk.sync()
        self.tanod = self.client("tanod1", "responder")
        self.res = self.client("juan", "resident")

    def ack(self, c):
        msg_id, topic, priority, body = parse_msg(c.recv())
        c.send(f"ACK {msg_id}")
        return topic, priority, body

    def file(self, category):
        report_id = self.res.ask(f"REPORT brgy.san-roque.p1.{category} N help").split()[1]
        self.res.sync()  # fan-out finished
        return report_id

    def run_check(self, after_seconds):
        """Run one escalation pass as if `after_seconds` had passed. It
        publishes before returning, so no sync is needed."""
        return escalation.check_once(self.broker.publish_escalation, now=time.time() + after_seconds)

    def test_urgent_goes_to_city_at_once(self):
        tanods = self.client("tanod-watch", "responder")
        tanods.send("SUB brgy.san-roque.#")
        tanods.sync()
        report_id = self.file("fire")
        topic, priority, body = self.ack(self.desk)
        self.assertEqual((topic, priority), ("city.iloilo.escalated.san-roque", "URGENT"))
        self.assertEqual((body["report_id"], body["escalated"]), (report_id, True))
        self.assertIn("Urgent fire", body["note"])
        _, _, body = self.ack(tanods)  # the tanods still get it, already marked escalated
        self.assertTrue(body["escalated"])
        self.assertTrue(tanods.nothing_pending())  # once, not twice

    def test_normal_report_waits_for_the_timer(self):
        report_id = self.file("noise")
        self.assertTrue(self.desk.nothing_pending())
        self.assertEqual(self.run_check(config.ESCALATE_SECONDS - 5), 0)
        self.assertEqual(self.run_check(config.ESCALATE_SECONDS + 1), 1)
        topic, _, body = self.ack(self.desk)
        self.assertEqual((topic, body["report_id"]), ("city.iloilo.escalated.san-roque", report_id))
        self.assertTrue(body["note"].startswith("No response within"))
        _, _, body = self.ack(self.res)  # the resident is told too
        self.assertTrue(body["escalated"])

    def test_escalates_exactly_once(self):
        self.file("noise")
        self.assertEqual(self.run_check(config.ESCALATE_SECONDS + 1), 1)
        self.assertEqual(self.run_check(config.ESCALATE_SECONDS + 100), 0)
        self.ack(self.desk)
        self.assertTrue(self.desk.nothing_pending())

    def test_responded_but_unresolved_escalates_later(self):
        report_id = self.file("noise")
        self.tanod.ask(f"STATUS {report_id} RESPONDING on the way")
        self.assertEqual(self.run_check(config.ESCALATE_SECONDS + 1), 0)  # someone responded
        self.assertEqual(self.run_check(config.UNRESOLVED_ESCALATE_SECONDS + 1), 1)
        _, _, body = self.ack(self.desk)
        self.assertEqual(body["status"], "RESPONDING")
        self.assertTrue(body["note"].startswith("Not resolved within"))

    def test_resolved_report_never_escalates(self):
        report_id = self.file("noise")
        self.tanod.ask(f"STATUS {report_id} RESOLVED settled")
        self.assertEqual(self.run_check(config.UNRESOLVED_ESCALATE_SECONDS + 100), 0)

    def test_only_desk_resolves_escalated(self):
        report_id = self.file("flood")
        self.ack(self.desk)
        self.assertEqual(self.tanod.ask(f"STATUS {report_id} RESPONDING on the way"),
                         f"UPDATED {report_id} RESPONDING")  # tanods may still respond
        self.assertEqual(self.tanod.ask(f"STATUS {report_id} RESOLVED done"),
                         f"ERR report {report_id} was escalated; only the city desk can resolve it")
        self.assertEqual(self.ack(self.desk)[2]["status"], "RESPONDING")  # desk was told
        self.assertEqual(self.desk.ask(f"STATUS {report_id} RESOLVED pumped out"),
                         f"UPDATED {report_id} RESOLVED")

    def test_desk_told_when_tanod_responds_to_escalated(self):
        report_id = self.file("fire")
        self.ack(self.desk)  # the escalation itself
        self.tanod.ask(f"STATUS {report_id} RESPONDING on the way")
        topic, _, body = self.ack(self.desk)
        self.assertEqual((topic, body["status"], body["updated_by"]),
                         ("city.iloilo.escalated.san-roque", "RESPONDING", "tanod1"))

    def test_desk_not_told_about_normal_updates(self):
        report_id = self.file("noise")
        self.tanod.ask(f"STATUS {report_id} RESPONDING on the way")
        self.assertTrue(self.desk.nothing_pending())

    def test_escalation_is_logged(self):
        report_id = self.file("fight")
        log = store.status_history(report_id)
        self.assertEqual([(h["status"], h["responder_id"]) for h in log], [("ESCALATED", None)])

    def test_thread_escalates_on_its_own(self):
        with mock.patch.object(config, "ESCALATE_SECONDS", 0):
            stop = threading.Event()
            thread = escalation.start_escalation_thread(
                self.broker.publish_escalation, stop, check_every=0.05)
            try:
                report_id = self.file("noise")
                _, _, body = self.ack(self.desk)
                self.assertEqual(body["report_id"], report_id)
            finally:
                stop.set()
                thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
