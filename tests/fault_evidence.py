"""tests/fault_evidence.py
Purpose: Run the 7 fault tests of FAULT_TEST_REPORT.md against a real broker
process and print a readable transcript to screenshot as evidence.

Run from the repository folder (about 1 minute):
    python tests/fault_evidence.py
    python tests/fault_evidence.py --only 1 2     # just some tests
    python tests/fault_evidence.py --quiet        # PASS/FAIL lines only

It never touches sumbong.db: it starts its own broker on port 5099 with a
throwaway database in the system temp folder and its own test accounts
(SR-T01 PIN 1111, SR-T02 PIN 2222, desk password deskpass1). Test 6 runs the
broker with a 6 s escalation timer instead of the 2 min demo value so it fits
in the run; everything else uses the timers in config.py.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import auth    # noqa: E402
import client  # noqa: E402
import config  # noqa: E402
import store   # noqa: E402

PORT = 5099
DB = os.path.join(tempfile.gettempdir(), "sumbong-fault-evidence.db")
FAST_ESCALATE = 6
QUIET = False
results = {}


# ---------------------------------------------------------------- output

def log(text):
    if not QUIET:
        print(f"  {time.strftime('%H:%M:%S')}  {text}")


def heading(number, title):
    print(f"\n=== Test {number}: {title} ===")


def check(number, name, ok, detail=""):
    results.setdefault(number, []).append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))


# ---------------------------------------------------------------- broker and accounts

def fresh_db():
    """Delete the throwaway database and create the test accounts."""
    for ext in ("", "-wal", "-shm"):
        try:
            os.remove(DB + ext)
        except FileNotFoundError:
            pass
    store.init_db(DB)
    store.save_user("SR-T01", "responder", auth.hash_secret("1111"), "san-roque")
    store.save_user("SR-T02", "responder", auth.hash_secret("2222"), "san-roque")
    store.save_user(config.DESK_ID, "desk", auth.hash_secret("deskpass1"))
    store.close_db()


def start_broker(escalate_seconds=None):
    """Start broker.py as its own process. With escalate_seconds, the escalation
    timers are shortened before the broker module is loaded."""
    if escalate_seconds is None:
        cmd = [sys.executable, "broker.py", "--port", str(PORT), "--db", DB]
    else:
        boot = ("import sys, config;"
                f"config.ESCALATE_SECONDS={escalate_seconds};"
                f"config.UNRESOLVED_ESCALATE_SECONDS={escalate_seconds * 10};"
                "config.ESCALATION_CHECK_SECONDS=1;"
                "import broker;"
                f"sys.argv=['broker.py','--port','{PORT}','--db',r'{DB}'];"
                "broker.main()")
        cmd = [sys.executable, "-c", boot]
    proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection((config.HOST, PORT), 0.2).close()
            log(f"broker started (pid {proc.pid}, port {PORT})")
            return proc
        except OSError:
            time.sleep(0.1)
    raise SystemExit("the broker did not start; is port 5099 free?")


def stop_broker(proc):
    proc.terminate()
    proc.wait(10)
    log("broker stopped")


class Raw:
    """A bare protocol client: sends lines, records every line received, and
    ACKs MSG lines only when auto_ack is True."""

    def __init__(self, name, hello, auto_ack=True):
        self.name, self.auto_ack = name, auto_ack
        self.sock = socket.create_connection((config.HOST, PORT))
        self.sock.settimeout(0.2)
        self.buf, self.lines = b"", []
        self.send(hello)

    def send(self, line):
        # Hide secrets in HELLO and shorten very long lines in the transcript.
        shown = line if not line.startswith("HELLO") or len(line.split()) < 4 else " ".join(line.split()[:3]) + " ****"
        if len(shown) > 100:
            shown = f"{shown[:40]}... ({len(line)} characters)"
        log(f"{self.name} -> {shown}")
        self.sock.sendall((line + "\n").encode(config.ENCODING))

    def pump(self, seconds=1.0):
        """Read for `seconds`, logging each line."""
        end = time.time() + seconds
        while time.time() < end:
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            self.buf += data
            while b"\n" in self.buf:
                raw, self.buf = self.buf.split(b"\n", 1)
                line = raw.decode(config.ENCODING)
                self.lines.append(line)
                if line == "PING":
                    self.sock.sendall(b"PONG\n")
                    continue
                log(f"{self.name} <- {line if len(line) < 110 else line[:107] + '...'}")
                if line.startswith("MSG ") and self.auto_ack:
                    self.send("ACK " + line.split()[1])
        return self.lines

    def msgs(self):
        return [line for line in self.lines if line.startswith("MSG ")]

    def close(self):
        log(f"{self.name} disconnects")
        self.sock.close()


def topics(lines):
    return [line.split()[2] for line in lines]


def body(line):
    return json.loads(line.split(" ", 4)[4])


def reported_id(c):
    return next((line.split()[1] for line in c.lines if line.startswith("REPORTED ")), None)


def delivery_status(msg_id, client_id):
    store.init_db(DB)
    try:
        row = store.get_delivery(msg_id, client_id)
        return row and row["status"], row and row["attempts"]
    finally:
        store.close_db()


# ---------------------------------------------------------------- the 7 tests

def test1():
    heading(1, "Offline subscriber catch-up")
    fresh_db()
    b = start_broker()
    try:
        t2 = Raw("TanodB", "HELLO SR-T02 responder 2222")
        t2.send("SUB brgy.san-roque.purok-5.#")
        t2.send("SUB brgy.san-roque.advisory")
        t2.pump(0.6)
        t2.close()
        t1 = Raw("Captain", "HELLO SR-T01 responder 1111")
        t1.send("ADVISORY san-roque NORMAL Clean-up drive on Saturday")
        t1.pump(0.6)
        time.sleep(0.3)
        r2 = Raw("Resident2", "HELLO resident2 resident")
        r2.send("REPORT brgy.san-roque.purok-5.fire N Smoke near the chapel")
        r2.pump(0.8)
        log("Tanod B reconnects with the same ID")
        t2 = Raw("TanodB", "HELLO SR-T02 responder 2222")
        t2.pump(1.5)
        got = t2.msgs()
        check(1, "Tanod B receives both missed messages on reconnect", len(got) == 2, got)
        check(1, "URGENT fire report arrives before the older advisory",
              len(got) == 2 and got[0].split()[2].endswith(".fire") and got[1].split()[2].endswith(".advisory"),
              topics(got))
        time.sleep(0.3)
        check(1, "both deliveries are DELIVERED after the ACKs",
              all(delivery_status(m.split()[1], "SR-T02")[0] == "DELIVERED" for m in got))
        for c in (t1, r2, t2):
            c.close()
    finally:
        stop_broker(b)


def test2():
    heading(2, "Lost ACK retry and duplicate ignored")
    fresh_db()
    b = start_broker()
    try:
        r = Raw("BareResident", "HELLO raw-res resident", auto_ack=False)
        r.send("REPORT brgy.san-roque.purok-3.noise N lost ack demo")
        r.pump(0.6)
        rid = reported_id(r)
        t1 = Raw("TanodA", "HELLO SR-T01 responder 1111")
        t1.send(f"STATUS {rid} RESPONDING on the way")
        t1.pump(0.6)
        log(f"the bare resident never ACKs; waiting {2 * config.RETRY_SECONDS + 2} s for resends")
        r.pump(2 * config.RETRY_SECONDS + 2)
        ids = [m.split()[1] for m in r.msgs()]
        check(2, f"same msg_id resent until ACKed ({len(ids)} copies)", len(ids) >= 2 and len(set(ids)) == 1, ids)
        attempts = delivery_status(ids[0], "raw-res")[1] if ids else 0
        log(f"deliveries table: attempts = {attempts}, still PENDING")
        check(2, "ATTEMPTS goes up in the deliveries table", (attempts or 0) >= 2)
        r.close()

        log("now a real client (client.py) whose first ACK is lost")
        events = []
        real = client.Client("resident9", "resident", lambda k, d: events.append((k, d)), config.HOST, PORT)
        real.send("REPORT brgy.san-roque.purok-3.noise N second lost ack demo")
        time.sleep(0.6)
        rid2 = next(d for k, d in events if k == "REPORTED")
        dropped = []
        original = real.send

        def lossy(line):
            if line.startswith("ACK ") and not dropped:
                dropped.append(line)
                log(f"resident9 -> {line}   (LOST on purpose)")
                return
            original(line)
        real.send = lossy
        t1.send(f"STATUS {rid2} RESOLVED settled")
        t1.pump(0.5)
        time.sleep(config.RETRY_SECONDS + 2)
        for kind, data in events:
            if kind in ("MSG", "DUPLICATE"):
                log(f"resident9 handler: {kind} {data['msg_id'] if kind == 'MSG' else data}")
        dup = [d for k, d in events if k == "DUPLICATE"]
        shown = [d["msg_id"] for k, d in events if k == "MSG"]
        check(2, "the resend is recognised as a duplicate and not shown twice", bool(dup) and dup[0] in shown,
              events)
        time.sleep(0.3)
        check(2, "delivery ends DELIVERED", bool(dup) and delivery_status(dup[0], "resident9")[0] == "DELIVERED")
        real.close()
        t1.close()
    finally:
        stop_broker(b)


def test3():
    heading(3, "Broker restart with no data loss")
    fresh_db()
    b = start_broker()
    try:
        t1 = Raw("TanodA", "HELLO SR-T01 responder 1111")
        t1.send("SUB brgy.san-roque.purok-3.#")
        t1.pump(0.5)
        t1.close()
        r = Raw("Resident1", "HELLO resident1 resident")
        r.send("REPORT brgy.san-roque.purok-3.noise N Loud karaoke past midnight")
        r.pump(0.6)
        rid = reported_id(r)
        r.close()
        log("restarting the broker on the same database")
        stop_broker(b)
        b = start_broker()
        store.init_db(DB)
        report = store.get_report(rid)
        store.close_db()
        check(3, "report survives the restart (status RECEIVED)", report is not None and report["status"] == "RECEIVED")
        t1 = Raw("TanodA", "HELLO SR-T01 responder 1111")
        t1.pump(1.5)
        check(3, "Tanod A gets its pending message after the restart",
              any(body(m).get("report_id") == rid for m in t1.msgs()), t1.lines)
        t1.close()
    finally:
        stop_broker(b)


def test4():
    heading(4, "Client crash during session")
    fresh_db()
    b = start_broker()
    try:
        t1 = Raw("TanodA", "HELLO SR-T01 responder 1111", auto_ack=False)
        t1.send("SUB brgy.san-roque.purok-3.#")
        t1.pump(0.5)
        r = Raw("Resident1", "HELLO resident1 resident")
        r.send("REPORT brgy.san-roque.purok-3.fight N Fight outside the store")
        r.pump(0.6)
        t1.pump(0.6)
        first = [m.split()[1] for m in t1.msgs()]
        log("Tanod A crashes before ACKing (socket closed abruptly)")
        t1.sock.close()
        half = socket.create_connection((config.HOST, PORT))
        half.sendall(b"HELLO half resident\nREPORT brgy.san-")
        half.close()
        log("another client sent half a line and vanished")
        r.send("PING")
        r.lines.clear()
        r.pump(0.6)
        check(4, "the broker keeps serving other clients (PONG)", "PONG" in r.lines, r.lines)
        t1 = Raw("TanodA", "HELLO SR-T01 responder 1111")
        t1.pump(1.5)
        again = [m.split()[1] for m in t1.msgs()]
        check(4, "the unACKed message is sent again on reconnect (same msg_id)", bool(first) and first[0] in again,
              f"{first} {again}")
        for c in (t1, r):
            c.close()
    finally:
        stop_broker(b)


def test5():
    heading(5, "Malformed command returns ERR")
    fresh_db()
    b = start_broker()
    try:
        c = Raw("Raw", "HELLO raw resident")
        bad = ["FOO", "SUB", "SUB brgy.#.fire", "REPORT brgy.san-roque.p1.earthquake N help",
               "REPORT brgy.molo.p1.fire N help", "sub brgy.#", "X" * 5000]
        replies = []
        for line in bad:
            c.lines.clear()
            c.send(line)
            c.pump(0.5)
            replies.append(next((l for l in c.lines if l.startswith("ERR")), None))
        check(5, f"every bad line gets ERR ({sum(bool(x) for x in replies)}/{len(bad)})", all(replies), replies)
        c.lines.clear()
        c.send("PING")
        c.pump(0.5)
        check(5, "the connection stays open (PING -> PONG)", "PONG" in c.lines, c.lines)
        c.close()
    finally:
        stop_broker(b)


def test6():
    heading(6, f"Escalation fires exactly once (timer shortened to {FAST_ESCALATE} s)")
    fresh_db()
    b = start_broker(escalate_seconds=FAST_ESCALATE)
    try:
        desk = Raw("CityDesk", f"HELLO {config.DESK_ID} desk deskpass1")
        desk.send("SUB city.iloilo.escalated.#")
        desk.pump(0.5)
        r = Raw("Resident1", "HELLO resident1 resident")
        r.send("REPORT brgy.san-roque.purok-3.noise N Barking dogs all night")
        r.send("REPORT brgy.san-roque.purok-4.noise N Resolved before the timer")
        r.pump(0.6)
        ids = [line.split()[1] for line in r.lines if line.startswith("REPORTED ")]
        t1 = Raw("TanodA", "HELLO SR-T01 responder 1111")
        t1.send(f"STATUS {ids[1]} RESOLVED handled")
        t1.pump(0.5)
        log(f"nobody responds to {ids[0]}; waiting {3 * FAST_ESCALATE} s (three timer lengths)")
        desk.pump(3 * FAST_ESCALATE)
        esc = [m for m in desk.msgs() if body(m).get("report_id") == ids[0]]
        check(6, "the city desk gets exactly one escalation for the ignored report", len(esc) == 1, desk.msgs())
        check(6, "the reason says no response", bool(esc) and "No response" in (body(esc[0]).get("note") or ""),
              esc)
        check(6, "the resolved report never escalates",
              not any(body(m).get("report_id") == ids[1] for m in desk.msgs()))
        for c in (desk, r, t1):
            c.close()
    finally:
        stop_broker(b)


def test7():
    heading(7, "Wrong PIN, false role and PIN guessing")
    fresh_db()
    b = start_broker()
    try:
        real = Raw("SR-T01(real)", "HELLO SR-T01 responder 1111")
        real.send("WHOAMI")
        real.pump(0.5)
        cases = [("wrong PIN", "HELLO SR-T01 responder 9999"),
                 ("missing PIN", "HELLO SR-T01 responder"),
                 ("false desk claim", "HELLO city responder 1111")]
        for name, hello in cases:
            c = Raw("Attacker", hello)
            start = time.time()
            c.pump(2.0)
            err = next((l for l in c.lines if l.startswith("ERR")), "")
            check(7, f"{name} refused after about {time.time() - start:.0f} s", "sign-in failed" in err
                  or "must sign in" in err, c.lines)
        for attempt in range(1, config.MAX_FAILED_LOGINS + 1):
            c = Raw("Guesser", f"HELLO {config.DESK_ID} desk wrongpass{attempt}")
            c.pump(1.6)
        c = Raw("Guesser", f"HELLO {config.DESK_ID} desk deskpass1")
        c.pump(1.6)
        check(7, f"after {config.MAX_FAILED_LOGINS} failures even the right password is locked out",
              any("too many failed sign-ins" in l for l in c.lines), c.lines)
        real.lines.clear()
        real.send("PING")
        real.pump(0.5)
        check(7, "the real SR-T01 is never disconnected", "PONG" in real.lines, real.lines)
        real.close()
    finally:
        stop_broker(b)


TESTS = {1: test1, 2: test2, 3: test3, 4: test4, 5: test5, 6: test6, 7: test7}


def main():
    global QUIET
    parser = argparse.ArgumentParser(description="Run the fault tests live and print evidence")
    parser.add_argument("--only", type=int, nargs="+", choices=sorted(TESTS), help="test numbers to run")
    parser.add_argument("--quiet", action="store_true", help="PASS/FAIL lines only")
    args = parser.parse_args()
    QUIET = args.quiet
    client.utf8_console()
    print(f"eSumbong fault evidence | {time.strftime('%Y-%m-%d %H:%M:%S')} | Python {sys.version.split()[0]} "
          f"| {sys.platform}")
    for number in args.only or sorted(TESTS):
        try:
            TESTS[number]()
        except Exception as exc:  # report and continue with the next test
            check(number, f"test crashed: {exc!r}", False)
    print("\n=== Summary ===")
    for number in sorted(results):
        print(f"  Test {number}: {'PASS' if all(results[number]) else 'FAIL'} "
              f"({sum(results[number])}/{len(results[number])} checks)")
    passed = all(all(v) for v in results.values())
    print(f"\n{'ALL FAULT TESTS PASSED' if passed else 'SOME FAULT TESTS FAILED'}")
    for ext in ("", "-wal", "-shm"):
        try:
            os.remove(DB + ext)
        except OSError:
            pass
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
