"""Live smoke test: drives a RUNNING eSumbong server (gateway + broker) end to end
through the same HTTP API the React app uses. Not part of `unittest discover`
(the name does not start with test_), because it needs a live server and it
writes real reports into that server's database.

It signs in as a real responder account, so make a dedicated one first, on the
server, tied to the test barangay (once):
    python users.py add smoke-tanod --barangay san-roque

Then, from any machine that can reach the server:
    python tests/live_smoke.py --url <URL>                 # asks for the PIN
    python tests/live_smoke.py --url <URL> --full          # also asks for the desk password
PINs are asked at a hidden prompt, or read from SMOKE_TANOD_PIN and
SMOKE_DESK_PASSWORD (for CI), never from the command line.

What it checks (each step prints PASS/FAIL; exit code 1 if any step fails):
   1. the web app is served (index.html) and /api/config answers
   2. sign-in: wrong PIN, missing PIN and a false desk claim are refused (401)
   3. a resident and the responder account sign in
   4. the gateway refuses commands a browser may not send (HELLO)
   5. role rules: a resident may not SUB to incident topics (ERR)
   6. a NORMAL report reaches the subscribed responder, with the reporter
   7. an anonymous report hides the reporter
   8. RESPONDING and RESOLVED reach the resident on report.<id>.status
   9. HISTORY returns this run's reports
  10. a resident can WITHDRAW a report nobody has responded to
  11. a report on a purok the responder does not cover never reaches it
  --full adds (needs the desk password):
  12. an URGENT fire report reaches the city desk at once; only the desk resolves it
  13. an advisory reaches a resident following the barangay

Safety on a shared server: the resident ID and purok carry this run's tag,
every description starts with "[SMOKE TEST]", every report is left RESOLVED or
WITHDRAWN, and only subscriptions this run added are removed at the end.
Anyone subscribed to the whole barangay (e.g. brgy.<barangay>.#) still sees
the test reports. --full signs in as the city desk, which DISCONNECTS an open
desk session (one session per ID), sends it an URGENT report and posts an
advisory to the barangay's residents: tell the team before running it on
production. Standard library only.
"""

import argparse
import getpass
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

WAIT = 10  # seconds to wait for any one broker reply


class Failure(Exception):
    pass


class Session:
    """One browser-like session: POST /api/connect, read /api/events, ACK every MSG."""

    def __init__(self, base, client_id, role, secret=None):
        self.base = base
        self.client_id = client_id
        self.role = role
        self.lines = queue.Queue()
        body = {"client_id": client_id, "role": role}
        if secret:
            body["secret"] = secret
        self.session = post(base, "/api/connect", body)["session"]
        self._stream = urllib.request.urlopen(f"{base}/api/events?session={self.session}", timeout=60)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for raw in self._stream:
                line = raw.decode("utf-8").rstrip("\r\n")
                if line.startswith("event: closed"):
                    self.lines.put(None)
                    return
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.startswith("MSG "):
                    self.send(f"ACK {data.split(' ', 2)[1]}")
                self.lines.put(data)
        except Exception:  # noqa: BLE001  (stream ended or was closed by us)
            pass
        self.lines.put(None)

    def send(self, line):
        post(self.base, "/api/send", {"session": self.session, "line": line})

    def wait_for(self, what, test):
        """The next line for which test(line) is true; other lines are skipped."""
        deadline = time.monotonic() + WAIT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Failure(f"{self.client_id}: no {what} within {WAIT}s")
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                raise Failure(f"{self.client_id}: event stream closed while waiting for {what}")
            if line.startswith("ERR ") and not what.startswith("ERR"):
                raise Failure(f"{self.client_id}: broker said {line!r} while waiting for {what}")
            if test(line):
                return line

    def wait_msg(self, what, test):
        """The next MSG whose (topic, body) passes test; returns (topic, priority, body)."""
        def parse(line):
            if not line.startswith("MSG "):
                return None
            _, _, topic, priority, body = line.split(" ", 4)
            return topic, priority, json.loads(body)
        line = self.wait_for(what, lambda l: (p := parse(l)) is not None and test(p[0], p[2]))
        return parse(line)

    def subs(self):
        self.send("SUBS")
        return self.wait_for("SUBS reply", lambda l: l.startswith("SUBS")).split()[1:]

    def close(self):
        try:
            post(self.base, "/api/disconnect", {"session": self.session})
        finally:
            self._stream.close()


def post(base, path, body, expect_ok=True):
    req = urllib.request.Request(f"{base}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=WAIT) as res:
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read() or b"{}")
        if expect_ok:
            raise Failure(f"POST {path} -> HTTP {exc.code}: {payload.get('error')}") from None
        return {"status": exc.code, **payload}


def get(base, path):
    with urllib.request.urlopen(f"{base}{path}", timeout=WAIT) as res:
        return res.status, res.headers.get("Content-Type", ""), res.read()


def secret_from(env, prompt):
    return os.environ.get(env) or getpass.getpass(prompt)


def main():
    parser = argparse.ArgumentParser(description="eSumbong live smoke test")
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="gateway base URL")
    parser.add_argument("--barangay", default="san-roque", help="barangay used for test reports")
    parser.add_argument("--tanod", default="smoke-tanod",
                        help="responder account to sign in as (make it with users.py); PIN from SMOKE_TANOD_PIN or a prompt")
    parser.add_argument("--full", action="store_true",
                        help="also test URGENT escalation and advisories (signs in as the city desk)")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    tag = uuid.uuid4().hex[:6]
    brgy = args.barangay
    purok = f"smoke-{tag}"
    prefix = "[SMOKE TEST]"
    pin = secret_from("SMOKE_TANOD_PIN", f"PIN for {args.tanod}: ")
    desk_password = secret_from("SMOKE_DESK_PASSWORD", "City desk password: ") if args.full else None
    results = []
    sessions = []
    cleanup = []  # (session, line) sent at the end
    ctx = {}

    def step(name, fn):
        start = time.monotonic()
        try:
            fn()
        except (Failure, OSError, ValueError, KeyError) as exc:
            results.append(False)
            print(f"  FAIL  {name}\n        {exc}")
            return False
        results.append(True)
        print(f"  PASS  {name}  ({time.monotonic() - start:.1f}s)")
        return True

    def subscribe(session, pattern):
        """SUB, and UNSUB at the end only if this run added it."""
        if pattern not in session.subs():
            session.send(f"SUB {pattern}")
            cleanup.append((session, f"UNSUB {pattern}"))
        if pattern not in session.subs():
            raise Failure(f"{session.client_id} could not subscribe to {pattern}")

    print(f"eSumbong live smoke test against {base}  (run tag {tag})\n")

    def web_app():
        status, ctype, body = get(base, "/")
        if status != 200 or "text/html" not in ctype or b"<div id=\"root\"" not in body:
            raise Failure("GET / did not return the React index.html (run `npm run build` in frontend/?)")
        _, _, body = get(base, "/api/config")
        cfg = json.loads(body)
        if brgy not in {b["id"] for b in cfg["barangays"]}:
            raise Failure(f"{brgy} is not in /api/config barangays")
        ctx["desk_id"] = cfg.get("desk_id", "city")

    def sign_in_refused():
        wrong = "0" if pin != "0" * len(pin) else "1"
        cases = [({"client_id": args.tanod, "role": "responder", "secret": wrong * max(4, len(pin))}, "wrong PIN"),
                 ({"client_id": args.tanod, "role": "responder"}, "missing PIN"),
                 ({"client_id": args.tanod, "role": "desk", "secret": pin}, "responder PIN used as desk"),
                 ({"client_id": f"nobody-{tag}", "role": "responder", "secret": pin}, "unknown account")]
        for body, what in cases:
            res = post(base, "/api/connect", body, expect_ok=False)
            if res.get("status") != 401:
                if "session" in res:
                    post(base, "/api/disconnect", {"session": res["session"]})
                raise Failure(f"{what}: expected 401, got {res}")

    def connect_all():
        ctx["resident"] = Session(base, f"smoke-res-{tag}", "resident")
        sessions.append(ctx["resident"])
        try:
            ctx["tanod"] = Session(base, args.tanod, "responder", pin)
        except Failure as exc:
            raise Failure(f"{exc} (does the account exist? python users.py add {args.tanod} --barangay {brgy})") from None
        sessions.append(ctx["tanod"])
        subscribe(ctx["tanod"], f"brgy.{brgy}.{purok}.#")
        if args.full:
            ctx["desk"] = Session(base, ctx["desk_id"], "desk", desk_password)
            sessions.append(ctx["desk"])
            subscribe(ctx["desk"], f"city.iloilo.escalated.{brgy}")

    def gateway_filter():
        res = post(base, "/api/send", {"session": ctx["resident"].session, "line": "HELLO someone desk"}, expect_ok=False)
        if res.get("status") != 400:
            raise Failure(f"gateway accepted HELLO from the browser: {res}")

    def role_rules():
        ctx["resident"].send(f"SUB brgy.{brgy}.#")
        ctx["resident"].wait_for("ERR for a resident SUB to incidents", lambda l: l.startswith("ERR "))

    def file_report(category, anon, text):
        res = ctx["resident"]
        res.send(f"REPORT brgy.{brgy}.{purok}.{category} {anon} {prefix} {text}, please ignore")
        return res.wait_for("REPORTED", lambda l: l.startswith("REPORTED ")).split()[1]

    def normal_report():
        rid = file_report("noise", "N", "loud karaoke")
        topic, priority, body = ctx["tanod"].wait_msg("the report", lambda t, b: b.get("report_id") == rid)
        if topic != f"brgy.{brgy}.{purok}.noise" or priority != "NORMAL":
            raise Failure(f"wrong topic/priority: {topic} {priority}")
        if body.get("reporter") != ctx["resident"].client_id:
            raise Failure(f"reporter should be {ctx['resident'].client_id}, got {body.get('reporter')}")
        ctx["rid"] = rid

    def anonymous_report():
        rid = file_report("drinking", "Y", "anonymous check")
        _, _, body = ctx["tanod"].wait_msg("the anonymous report", lambda t, b: b.get("report_id") == rid)
        if "reporter" in body:
            raise Failure(f"anonymous report revealed the reporter: {body['reporter']}")
        ctx["anon_rid"] = rid

    def status_updates():
        res, tanod, rid = ctx["resident"], ctx["tanod"], ctx["rid"]
        for status in ("RESPONDING", "RESOLVED"):
            tanod.send(f"STATUS {rid} {status} {prefix} {status.lower()}")
            tanod.wait_for(f"UPDATED {status}", lambda l, s=status: l == f"UPDATED {rid} {s}")
            res.wait_msg(f"{status} on report.{rid}.status",
                         lambda t, b, s=status: t == f"report.{rid}.status" and b.get("status") == s)
        tanod.send(f"STATUS {ctx['anon_rid']} RESOLVED {prefix} cleanup")
        tanod.wait_for("UPDATED for cleanup", lambda l: l.startswith(f"UPDATED {ctx['anon_rid']}"))

    def history():
        tanod = ctx["tanod"]
        tanod.send("HISTORY")
        seen = set()
        tanod.wait_for("HISTEND", lambda l: (l.startswith("HIST ") and seen.add(json.loads(l.split(" ", 3)[3])["report_id"]))
                       or l.startswith("HISTEND"))
        if ctx["rid"] not in seen:
            raise Failure(f"HISTORY did not include report {ctx['rid']}")

    def withdraw():
        res = ctx["resident"]
        rid = file_report("road", "N", "withdraw check")
        res.send(f"WITHDRAW {rid} smoke test")
        res.wait_for("UPDATED WITHDRAWN", lambda l: l == f"UPDATED {rid} WITHDRAWN")
        ctx["tanod"].wait_msg("the withdrawal", lambda t, b: b.get("report_id") == rid and b.get("status") == "WITHDRAWN")

    def isolation():
        # A report one purok over: the responder covers only this run's purok.
        res, other = ctx["resident"], f"{purok}-x"
        res.send(f"REPORT brgy.{brgy}.{other}.noise N {prefix} isolation check, please ignore")
        rid = res.wait_for("REPORTED", lambda l: l.startswith("REPORTED ")).split()[1]
        res.send(f"WITHDRAW {rid} smoke test")  # so it never escalates to the desk
        res.wait_for("UPDATED WITHDRAWN", lambda l: l == f"UPDATED {rid} WITHDRAWN")
        deadline = time.monotonic() + 3
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                line = ctx["tanod"].lines.get(timeout=remaining)
            except queue.Empty:
                break
            if line and line.startswith("MSG ") and rid in line:
                raise Failure(f"the responder received a report outside its subscription: {line[:120]}")

    def urgent_escalation():
        desk = ctx["desk"]
        rid = file_report("fire", "N", "urgent escalation check")
        topic, priority, body = desk.wait_msg("the escalated fire report", lambda t, b: b.get("report_id") == rid)
        if topic != f"city.iloilo.escalated.{brgy}" or priority != "URGENT" or not body.get("escalated"):
            raise Failure(f"expected URGENT escalation on city.iloilo.escalated.{brgy}, got {topic} {priority}")
        ctx["tanod"].send(f"STATUS {rid} RESOLVED {prefix} tanod tries")
        ctx["tanod"].wait_for("ERR: only the desk may resolve", lambda l: l.startswith("ERR "))
        desk.send(f"STATUS {rid} RESOLVED {prefix} handled by the desk")
        desk.wait_for("UPDATED RESOLVED", lambda l: l == f"UPDATED {rid} RESOLVED")

    def advisory():
        res, tanod = ctx["resident"], ctx["tanod"]
        subscribe(res, f"brgy.{brgy}.advisory")
        tanod.send(f"ADVISORY {brgy} NORMAL {prefix} test advisory, please ignore")
        aid = tanod.wait_for("POSTED", lambda l: l.startswith("POSTED ")).split()[1]
        res.wait_msg("the advisory", lambda t, b: b.get("advisory_id") == aid)

    try:
        ok = step("web app and /api/config are served", web_app)
        ok = ok and step("wrong PIN, missing PIN and false desk claim are refused", sign_in_refused)
        ok = ok and step("resident and responder sign in", connect_all)
        if ok:
            step("gateway refuses HELLO from a browser", gateway_filter)
            step("resident may not subscribe to incident topics", role_rules)
            if step("NORMAL report reaches the subscribed responder", normal_report):
                if step("anonymous report hides the reporter", anonymous_report):
                    step("RESPONDING and RESOLVED reach the resident", status_updates)
                step("HISTORY includes this run's report", history)
            step("resident withdraws an unanswered report", withdraw)
            step("a purok the responder does not cover never reaches it", isolation)
            if args.full:
                step("URGENT fire goes to the city desk; only the desk resolves", urgent_escalation)
                step("advisory reaches a following resident", advisory)
    finally:
        for s, line in cleanup:
            try:
                s.send(line)
            except Exception:  # noqa: BLE001
                pass
        for s in sessions:
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass

    print(f"\n{sum(results)}/{len(results)} steps passed")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
