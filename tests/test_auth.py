"""Tests for sign-in and per-barangay limits: auth.py, the users table in
store.py, HELLO with a PIN in broker.py, and the users.py account tool.
Run: python -m unittest discover -s tests"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import auth  # noqa: E402
import broker  # noqa: E402
import config  # noqa: E402
import store  # noqa: E402
import users  # noqa: E402
from test_broker import Client, parse_msg  # noqa: E402

FAST = 1000  # PBKDF2 iterations in tests; the real default is auth.ITERATIONS


def answers(*values):
    """A stand-in for getpass that returns these values in turn."""
    it = iter(values)
    return lambda prompt="": next(it)


class HashTest(unittest.TestCase):

    def test_hash_and_verify(self):
        h = auth.hash_secret("1234", iterations=FAST)
        self.assertTrue(h.startswith("pbkdf2_sha256$1000$"))
        self.assertTrue(auth.verify_secret("1234", h))
        self.assertFalse(auth.verify_secret("1235", h))
        self.assertFalse(auth.verify_secret("", h))

    def test_same_secret_gets_a_different_salt(self):
        self.assertNotEqual(auth.hash_secret("1234", FAST), auth.hash_secret("1234", FAST))

    def test_default_cost_is_strong(self):
        self.assertGreaterEqual(auth.ITERATIONS, 100_000)

    def test_malformed_hashes_never_verify(self):
        for bad in ["", "plain", "md5$1$00$00", "pbkdf2_sha256$x$zz$00", None]:
            self.assertFalse(auth.verify_secret("1234", bad), bad)

    def test_secret_rules(self):
        self.assertIsNone(auth.secret_problem("responder", "1234"))
        self.assertIn("at least", auth.secret_problem("responder", "123"))
        self.assertIsNone(auth.secret_problem("desk", "city-pass-1"))
        self.assertIn("at least", auth.secret_problem("desk", "short"))
        self.assertIn("no spaces", auth.secret_problem("responder", "12 34"))


class CheckLoginTest(unittest.TestCase):

    def setUp(self):
        auth.reset_failures()
        store.init_db(":memory:")
        store.save_user("tanod-a", "responder", auth.hash_secret("1234", FAST), "san-roque")
        store.save_user(config.DESK_ID, "desk", auth.hash_secret("city-pass-1", FAST))

    def tearDown(self):
        store.close_db()

    def test_residents_need_no_account(self):
        self.assertIsNone(auth.check_login("anyone", "resident", ""))

    def test_valid_logins_return_the_account(self):
        self.assertEqual(auth.check_login("tanod-a", "responder", "1234")["barangay"], "san-roque")
        self.assertEqual(auth.check_login(config.DESK_ID, "desk", "city-pass-1")["role"], "desk")

    def test_refusals_all_look_the_same(self):
        cases = [("tanod-a", "responder", "9999"),   # wrong PIN
                 ("ghost", "responder", "1234"),     # no such account
                 ("tanod-a", "desk", "1234"),        # right PIN, wrong role
                 (config.DESK_ID, "responder", "city-pass-1")]
        for case in cases:
            with self.assertRaises(auth.AuthError) as ctx:
                auth.check_login(*case)
            self.assertEqual(str(ctx.exception), auth.LOGIN_FAILED, case)

    def test_lockout_after_repeated_failures(self):
        now = 1000.0
        for _ in range(config.MAX_FAILED_LOGINS):
            with self.assertRaisesRegex(auth.AuthError, "wrong ID"):
                auth.check_login("tanod-a", "responder", "9999", now=now)
        # Locked now: even the right PIN is refused, without saying whether it was right.
        with self.assertRaisesRegex(auth.AuthError, "too many failed sign-ins"):
            auth.check_login("tanod-a", "responder", "1234", now=now + 1)
        # Other accounts are not affected.
        self.assertIsNotNone(auth.check_login(config.DESK_ID, "desk", "city-pass-1", now=now + 1))
        # The lock expires.
        self.assertIsNotNone(auth.check_login("tanod-a", "responder", "1234", now=now + config.LOCKOUT_SECONDS + 1))

    def test_unknown_ids_lock_too(self):
        for _ in range(config.MAX_FAILED_LOGINS):
            with self.assertRaises(auth.AuthError):
                auth.check_login("ghost", "responder", "1234", now=50.0)
        with self.assertRaisesRegex(auth.AuthError, "too many"):
            auth.check_login("ghost", "responder", "1234", now=51.0)

    def test_a_good_sign_in_resets_the_count(self):
        for _ in range(config.MAX_FAILED_LOGINS - 1):
            with self.assertRaises(auth.AuthError):
                auth.check_login("tanod-a", "responder", "9999", now=10.0)
        auth.check_login("tanod-a", "responder", "1234", now=11.0)
        for _ in range(config.MAX_FAILED_LOGINS - 1):
            with self.assertRaises(auth.AuthError):
                auth.check_login("tanod-a", "responder", "9999", now=12.0)
        self.assertIsNotNone(auth.check_login("tanod-a", "responder", "1234", now=13.0))

    def test_missing_secret(self):
        with self.assertRaisesRegex(auth.AuthError, "PIN"):
            auth.check_login("tanod-a", "responder", "")
        with self.assertRaisesRegex(auth.AuthError, "desk password"):
            auth.check_login(config.DESK_ID, "desk", "")


class UserStoreTest(unittest.TestCase):

    def setUp(self):
        store.init_db(":memory:")

    def tearDown(self):
        store.close_db()

    def test_save_replace_list_delete(self):
        store.save_user("tanod-a", "responder", "h1", "san-roque")
        store.save_user(config.DESK_ID, "desk", "h2")
        store.save_user("tanod-a", "responder", "h3", "tacas")  # PIN reset / move
        self.assertEqual(store.get_user("tanod-a")["secret_hash"], "h3")
        self.assertEqual(store.get_user("tanod-a")["barangay"], "tacas")
        listed = store.list_users()
        self.assertEqual([u["client_id"] for u in listed], [config.DESK_ID, "tanod-a"])
        self.assertNotIn("secret_hash", listed[0])
        self.assertEqual(store.delete_user("tanod-a"), "tanod-a")
        self.assertIsNone(store.delete_user("tanod-a"))
        self.assertIsNone(store.get_user("tanod-a"))

    def test_ids_match_without_regard_to_case(self):
        store.save_user("SR-T01", "responder", "h1", "san-roque")
        self.assertEqual(store.get_user("sr-t01")["client_id"], "SR-T01")  # keeps its spelling
        store.save_user("sr-t01", "responder", "h2", "san-roque")  # updates, no second account
        self.assertEqual([u["client_id"] for u in store.list_users()], ["SR-T01"])
        self.assertEqual(store.get_user("SR-T01")["secret_hash"], "h2")

    def test_delete_drops_subscriptions_and_backlog(self):
        store.save_user("SR-T02", "responder", "h", "san-roque")
        store.add_subscription("SR-T02", "brgy.san-roque.#")
        store.save_message("m1", None, "brgy.san-roque.advisory", "NORMAL", "{}", recipients=["SR-T02"])
        self.assertEqual(store.delete_user("sr-t02"), "SR-T02")
        self.assertEqual(store.subscriptions_for("SR-T02"), [])
        self.assertEqual(store.pending_for("SR-T02"), [])

    def test_list_by_barangay(self):
        store.save_user("SR-T01", "responder", "h", "san-roque")
        store.save_user("TAC-T01", "responder", "h", "tacas")
        store.save_user(config.DESK_ID, "desk", "h")
        self.assertEqual([u["client_id"] for u in store.list_users("tacas")], ["TAC-T01"])

    def test_role_is_responder_or_desk_only(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            store.save_user("juan", "resident", "h")


class AuthBrokerTest(unittest.TestCase):
    """HELLO over real sockets with sign-in switched on, as in production."""

    def setUp(self):
        auth.reset_failures()
        self.broker = broker.Broker("127.0.0.1", 0, ":memory:")
        self.assertTrue(self.broker.require_auth)  # on by default
        self.broker.failed_login_delay = 0
        _, self.port = self.broker.start()
        store.save_user("tanod-a", "responder", auth.hash_secret("1234", FAST), "san-roque")
        store.save_user("roving", "responder", auth.hash_secret("5678", FAST))  # all of Jaro
        store.save_user(config.DESK_ID, "desk", auth.hash_secret("city-pass-1", FAST))
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.drain()
            c.close()
        self.broker.stop()

    def hello(self, line):
        c = Client(self.port)
        self.clients.append(c)
        c.send(line)
        c.send("PING")
        return c, c.recv()  # PONG if HELLO was accepted, ERR otherwise

    def login(self, client_id, role, secret=None):
        c, reply = self.hello(f"HELLO {client_id} {role}" + (f" {secret}" if secret else ""))
        self.assertEqual(reply, "PONG", f"{client_id} could not sign in: {reply}")
        return c

    def test_valid_sign_ins(self):
        self.login("tanod-a", "responder", "1234")
        self.login(config.DESK_ID, "desk", "city-pass-1")
        self.login("juan", "resident")
        self.assertEqual(self.broker.online_clients(), sorted([config.DESK_ID, "juan", "tanod-a"]))

    def test_refused_sign_in_sends_err_and_closes(self):
        for line in ["HELLO tanod-a responder 9999", "HELLO tanod-a responder",
                     "HELLO ghost responder 1234", "HELLO intruder desk",
                     f"HELLO {config.DESK_ID} desk wrong-pass", "HELLO tanod-a desk 1234"]:
            c, reply = self.hello(line)
            self.assertTrue(reply.startswith("ERR "), (line, reply))
            with self.assertRaises((ConnectionError, OSError)):
                c.recv()  # the broker hung up
        self.assertEqual(self.broker.online_clients(), [])

    def test_refused_sign_in_does_not_kick_the_real_user(self):
        real = self.login("tanod-a", "responder", "1234")
        self.hello("HELLO tanod-a responder 0000")
        real.sync()  # still connected
        self.assertEqual(self.broker.online_clients(), ["tanod-a"])

    def test_whoami_names_the_account_and_its_barangay(self):
        self.assertEqual(self.login("tanod-a", "responder", "1234").ask("WHOAMI"), "ME tanod-a responder san-roque")
        self.assertEqual(self.login("roving", "responder", "5678").ask("WHOAMI"), "ME roving responder -")
        self.assertEqual(self.login(config.DESK_ID, "desk", "city-pass-1").ask("WHOAMI"), f"ME {config.DESK_ID} desk -")
        self.assertEqual(self.login("juan", "resident").ask("WHOAMI"), "ME juan resident -")
        self.assertTrue(self.login("juan2", "resident").ask("WHOAMI extra").startswith("ERR usage"))

    def test_account_ids_ignore_case_and_keep_their_spelling(self):
        store.save_user("SR-T01", "responder", auth.hash_secret("2468", FAST), "san-roque")
        c = self.login("sr-t01", "responder", "2468")
        self.assertEqual(c.ask("WHOAMI"), "ME SR-T01 responder san-roque")
        self.assertIn("SR-T01", self.broker.online_clients())

    def test_resident_secret_is_ignored(self):
        self.login("juan", "resident", "whatever")

    def test_barangay_account_may_only_subscribe_there(self):
        tanod = self.login("tanod-a", "responder", "1234")
        tanod.send("SUB brgy.san-roque.#")  # SUB is silent when accepted
        tanod.sync()
        for pattern in ["brgy.#", "brgy.*.*.fire", "brgy.tacas.#"]:
            reply = tanod.ask(f"SUB {pattern}")
            self.assertTrue(reply.startswith("ERR your account is for San Roque"), (pattern, reply))
        self.assertEqual(tanod.ask("SUBS"), "SUBS brgy.san-roque.#")
        roving = self.login("roving", "responder", "5678")
        roving.send("SUB brgy.#")
        self.assertEqual(roving.ask("SUBS"), "SUBS brgy.#")

    def test_saved_subscriptions_outside_the_barangay_are_dropped(self):
        store.add_subscription("tanod-a", "brgy.#")
        store.add_subscription("tanod-a", "brgy.san-roque.purok-3.#")
        tanod = self.login("tanod-a", "responder", "1234")
        self.assertEqual(tanod.ask("SUBS"), "SUBS brgy.san-roque.purok-3.#")

    def file_report(self, barangay):
        res = self.login(f"res-{barangay}", "resident")
        reply = res.ask(f"REPORT brgy.{barangay}.purok-1.noise N loud music")
        self.assertTrue(reply.startswith("REPORTED "), reply)
        return reply.split()[1]

    def test_barangay_account_may_only_update_its_reports(self):
        tanod = self.login("tanod-a", "responder", "1234")
        here, there = self.file_report("san-roque"), self.file_report("tacas")
        self.assertEqual(tanod.ask(f"STATUS {here} RESPONDING on the way"), f"UPDATED {here} RESPONDING")
        self.assertEqual(tanod.ask(f"STATUS {there} RESPONDING on the way"), f"ERR report {there} is not in your barangay")
        roving = self.login("roving", "responder", "5678")
        self.assertEqual(roving.ask(f"STATUS {there} RESPONDING ok"), f"UPDATED {there} RESPONDING")

    def test_barangay_account_may_only_post_advisories_there(self):
        tanod = self.login("tanod-a", "responder", "1234")
        self.assertTrue(tanod.ask("ADVISORY san-roque NORMAL Clean-up drive").startswith("POSTED "))
        self.assertTrue(tanod.ask("ADVISORY tacas NORMAL Clean-up drive").startswith("ERR your account is for San Roque"))
        desk = self.login(config.DESK_ID, "desk", "city-pass-1")
        self.assertTrue(desk.ask("ADVISORY tacas URGENT Flood warning").startswith("POSTED "))

    def test_signed_in_tanod_receives_reports_for_their_barangay(self):
        tanod = self.login("tanod-a", "responder", "1234")
        tanod.send("SUB brgy.san-roque.#")
        tanod.sync()
        rid = self.file_report("san-roque")
        _, topic, _, body = parse_msg(tanod.recv())
        self.assertEqual((topic, body["report_id"]), ("brgy.san-roque.purok-1.noise", rid))


class UsersCliTest(unittest.TestCase):
    """users.py, against a temporary database file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "users.db")

    def tearDown(self):
        store.close_db()
        self.tmp.cleanup()

    def run_cli(self, *argv, ask=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = users.main(["--db", self.db, *argv], ask=ask or answers())
        return code, out.getvalue() + err.getvalue()

    def stored(self, client_id):
        store.init_db(self.db)
        try:
            return store.get_user(client_id)
        finally:
            store.close_db()

    def test_tanods_are_numbered_per_barangay(self):
        pins = answers(*["1234"] * 10)
        for expected in ["SR-T01", "SR-T02"]:
            code, out = self.run_cli("add", "--barangay", "san-roque", "--position", "tanod", ask=pins)
            self.assertEqual(code, 0, out)
            self.assertIn(f"Added {expected} (tanod, San Roque)", out)
        code, out = self.run_cli("add", "--barangay", "tacas", "--position", "tanod", ask=pins)
        self.assertIn("Added TAC-T01 (tanod, Tacas)", out)  # each barangay counts on its own
        user = self.stored("SR-T01")
        self.assertEqual(user["barangay"], "san-roque")
        self.assertTrue(auth.verify_secret("1234", user["secret_hash"]))
        self.assertNotIn("1234", user["secret_hash"])

    def test_numbers_continue_after_the_highest(self):
        pins = answers(*["1234"] * 10)
        for _ in range(3):
            self.run_cli("add", "--barangay", "san-roque", "--position", "tanod", ask=pins)
        self.run_cli("remove", "SR-T02")
        _, out = self.run_cli("add", "--barangay", "san-roque", "--position", "tanod", ask=pins)
        self.assertIn("Added SR-T04", out)

    def test_one_captain_per_barangay(self):
        code, out = self.run_cli("add", "--barangay", "mh-del-pilar", "--position", "captain", ask=answers("1234", "1234"))
        self.assertIn("Added MHP-CAPT (captain, M.H. del Pilar)", out)
        code, out = self.run_cli("add", "--barangay", "mh-del-pilar", "--position", "captain", ask=answers())
        self.assertEqual(code, 1)
        self.assertIn("MHP-CAPT already exists", out)
        self.assertIn("reset-pin MHP-CAPT", out)

    def test_custom_ids(self):
        code, out = self.run_cli("add", "--id", "smoke-tanod", "--barangay", "san-roque", ask=answers("1234", "1234"))
        self.assertIn("Added smoke-tanod (responder, San Roque)", out)
        code, out = self.run_cli("add", "--id", "roving-1", ask=answers("1234", "1234"))
        self.assertIn("Added roving-1 (responder, all of Jaro)", out)
        self.assertIsNone(self.stored("roving-1")["barangay"])

    def test_reset_pin_list_and_remove(self):
        self.run_cli("add", "--barangay", "san-roque", "--position", "tanod", ask=answers("1234", "1234"))
        code, out = self.run_cli("reset-pin", "sr-t01", ask=answers("4321", "4321"))  # any case
        self.assertIn("Changed the PIN for SR-T01", out)
        self.assertTrue(auth.verify_secret("4321", self.stored("SR-T01")["secret_hash"]))

        self.run_cli("desk-password", ask=answers("city-pass-1", "city-pass-1"))
        self.run_cli("add", "--barangay", "tacas", "--position", "captain", ask=answers("1234", "1234"))
        code, out = self.run_cli("list")
        lines = out.splitlines()
        self.assertEqual(lines[0].split(), ["ID", "POSITION", "BARANGAY", "ADDED"])
        self.assertTrue(lines[1].startswith("city ") and "City desk" in lines[1])
        self.assertIn("Tanod", out)
        self.assertIn("Captain", out)
        self.assertEqual(lines[-1], "3 accounts")
        code, out = self.run_cli("list", "--barangay", "tacas")
        self.assertIn("TAC-CAPT", out)
        self.assertNotIn("SR-T01", out)

        self.assertIn("Removed SR-T01", self.run_cli("remove", "sr-t01")[1])
        self.assertIsNone(self.stored("SR-T01"))
        self.assertEqual(self.run_cli("remove", "SR-T01")[0], 1)

    def test_codes_command(self):
        code, out = self.run_cli("codes")
        self.assertEqual(code, 0)
        self.assertIn("SR   San Roque", out)
        self.assertEqual(len(out.splitlines()), len(config.BARANGAYS))

    def test_refuses_bad_input(self):
        tanod = ("add", "--barangay", "san-roque", "--position", "tanod")
        cases = [
            (tanod, answers("12", "12"), "at least"),
            (tanod, answers("1234", "9999"), "do not match"),
            (("add", "--barangay", "molo", "--position", "tanod"), answers(), "not a barangay"),
            (("add", "--position", "tanod"), answers(), "needs --barangay"),
            (("add", "--barangay", "san-roque"), answers(), "--position"),
            (("add", "--id", "x1", "--position", "tanod", "--barangay", "san-roque"), answers(), "not both"),
            (("add", "--id", config.DESK_ID), answers(), "desk-password"),
            (("add", "--id", "SR-T07"), answers(), "made by --position"),
            (("add", "--id", "two words"), answers(), "one word"),
            (("reset-pin", "nobody"), answers(), "no account"),
            (("desk-password",), answers("short", "short"), "at least"),
        ]
        for argv, ask, message in cases:
            code, out = self.run_cli(*argv, ask=ask)
            self.assertEqual(code, 1, argv)
            self.assertIn(message, out, argv)
        self.assertIn("No accounts yet", self.run_cli("list")[1])


class BarangayCodesTest(unittest.TestCase):

    def test_every_barangay_has_a_unique_code(self):
        self.assertEqual(set(config.BARANGAY_CODES), set(config.BARANGAYS))
        codes = list(config.BARANGAY_CODES.values())
        self.assertEqual(len(codes), len(set(codes)), "duplicate barangay code")
        for code in codes:
            self.assertRegex(code, r"^[A-Z0-9]{2,4}$")
            self.assertNotEqual(code, "CAPT")


if __name__ == "__main__":
    unittest.main()
