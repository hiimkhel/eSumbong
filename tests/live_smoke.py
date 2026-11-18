"""Live smoke test: drives a RUNNING eSumbong server (gateway + broker) end to end
through the same HTTP API the React app uses. Not part of `unittest discover`
(the name does not start with test_), because it needs a live server and it
writes real reports into that server's database.

    python tests/live_smoke.py                              # http://127.0.0.1:8080
    python tests/live_smoke.py --url https://sumbong.example.org
    python tests/live_smoke.py --full                       # also URGENT fire + advisory

What it checks (each step prints PASS/FAIL; exit code 1 if any step fails):
   1. the web app is served (index.html) and /api/config answers
   2. resident, responder and desk can connect (unique IDs per run)
   3. the gateway refuses commands a browser may not send (HELLO)
   4. role rules: a resident may not SUB to incident topics (ERR)
   5. a NORMAL report reaches only the subscribed responder, with the reporter
   6. an anonymous report hides the reporter
   7. RESPONDING and RESOLVED reach the resident on report.<id>.status
   8. a resident can WITHDRAW a report nobody has responded to
   9. HISTORY returns this run's reports
  --full adds:
  10. an URGENT fire report reaches the city desk at once, and the desk resolves it
  11. an advisory reaches a resident following the barangay

Safety on a shared server: every ID and purok carries this run's tag, every
description starts with "[SMOKE TEST]", every report is left RESOLVED or
WITHDRAWN, and subscriptions are removed at the end. Anyone subscribed to the
whole barangay (e.g. brgy.<barangay>.#) will still see the test reports, and
--full sends an URGENT report to the city desk and an advisory to residents
following the barangay, so tell the team before running it on production.
Standard library only.
"""

import argparse
import json
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

    def __init__(self, base, client_id, role):
        self.base = base
        self.client_id = client_id
        self.role = role
        self.lines = queue.Queue()
        self.session = post(base, "/api/connect", {"client_id": client_id, "role": role})["session"]
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


def main():
    parser = argparse.ArgumentParser(description="eSumbong live smoke test")
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="gateway base URL")
    parser.add_argument("--barangay", default="san-roque", help="barangay used for test reports")
    parser.add_argument("--full", action="store_true", help="also test URGENT escalation and advisories")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    tag = uuid.uuid4().hex[:6]
    brgy = args.barangay
    purok = f"smoke-{tag}"
    prefix = "[SMOKE TEST]"
    results = []
    sessions = []
    cleanup = []  # lines to send at the end: (session, line)

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

    print(f"eSumbong live smoke test against {base}  (run tag {tag})\n")
    ctx = {}

    def web_app():
        status, ctype, body = get(base, "/")
        if status != 200 or "text/html" not in ctype or b"<div id=\"root\"" not in body:
            raise Failure("GET / did not return the React index.html (run `npm run build` in frontend/?)")
        status, _, body = get(base, "/api/config")
        cfg = json.loads(body)
        if brgy not in {b["id"] for b in cfg["barangays"]}:
            raise Failure(f"{brgy} is not in /api/config barangays")
        ctx["cfg"] = cfg

    def connect_all():
        for name, cid, role in [("resident", f"smoke-res-{tag}", "resident"),
                                ("tanod", f"smoke-tanod-{tag}", "responder"),
                                ("other", f"smoke-other-{tag}", "responder"),
                                ("desk", f"smoke-desk-{tag}", "desk")]:
            s = Session(base, cid, role)
            sessions.append(s)
            ctx[name] = s
        tanod, other, desk = ctx["tanod"], ctx["other"], ctx["desk"]
        tanod.send(f"SUB brgy.{brgy}.{purok}.#")
        other.send(f"SUB brgy.{brgy}.{purok}-elsewhere.#")  # must NOT get this run's reports
        cleanup.append((tanod, f"UNSUB brgy.{brgy}.{purok}.#"))
        cleanup.append((other, f"UNSUB brgy.{brgy}.{purok}-elsewhere.#"))
        if args.full:
            desk.send(f"SUB city.iloilo.escalated.{brgy}")
            cleanup.append((desk, f"UNSUB city.iloilo.escalated.{brgy}"))
        for s in (tanod, other, desk):
            s.send("SUBS")
            s.wait_for("SUBS reply", lambda l: l.startswith("SUBS"))

    def gateway_filter():
        res = post(base, "/api/send", {"session": ctx["resident"].session, "line": "HELLO someone desk"}, expect_ok=False)
        if res.get("status") != 400:
            raise Failure(f"gateway accepted HELLO from the browser: {res}")

    def role_rules():
        ctx["resident"].send(f"SUB brgy.{brgy}.#")
        ctx["resident"].wait_for("ERR for a resident SUB to incidents", lambda l: l.startswith("ERR "))

    def normal_report():
        res, tanod = ctx["resident"], ctx["tanod"]
        res.send(f"REPORT brgy.{brgy}.{purok}.noise N {prefix} loud karaoke, please ignore")
        rid = res.wait_for("REPORTED", lambda l: l.startswith("REPORTED ")).split()[1]
        topic, priority, body = tanod.wait_msg("the report", lambda t, b: b.get("report_id") == rid)
        if topic != f"brgy.{brgy}.{purok}.noise" or priority != "NORMAL":
            raise Failure(f"wrong topic/priority: {topic} {priority}")
        if body.get("reporter") != res.client_id:
            raise Failure(f"reporter should be {res.client_id}, got {body.get('reporter')}")
        ctx["rid"] = rid

    def anonymous_report():
        res, tanod = ctx["resident"], ctx["tanod"]
        res.send(f"REPORT brgy.{brgy}.{purok}.drinking Y {prefix} anonymous check, please ignore")
        rid = res.wait_for("REPORTED", lambda l: l.startswith("REPORTED ")).split()[1]
        _, _, body = tanod.wait_msg("the anonymous report", lambda t, b: b.get("report_id") == rid)
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

    def withdraw():
        res = ctx["resident"]
        res.send(f"REPORT brgy.{brgy}.{purok}.road N {prefix} withdraw check, please ignore")
        rid = res.wait_for("REPORTED", lambda l: l.startswith("REPORTED ")).split()[1]
        res.send(f"WITHDRAW {rid} smoke test")
        res.wait_for("UPDATED WITHDRAWN", lambda l: l == f"UPDATED {rid} WITHDRAWN")
        ctx["tanod"].wait_msg("the withdrawal", lambda t, b: b.get("report_id") == rid and b.get("status") == "WITHDRAWN")

    def history():
        tanod = ctx["tanod"]
        tanod.send("HISTORY")
        seen = set()
        tanod.wait_for("HISTEND", lambda l: (l.startswith("HIST ") and seen.add(json.loads(l.split(" ", 3)[3])["report_id"]))
                       or l.startswith("HISTEND"))
        if ctx["rid"] not in seen:
            raise Failure(f"HISTORY did not include report {ctx['rid']}")

    def not_leaked():
        # Everything above has already been delivered; give stragglers 3 seconds.
        other, deadline = ctx["other"], time.monotonic() + 3
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                line = other.lines.get(timeout=remaining)
            except queue.Empty:
                break
            if line and line.startswith("MSG ") and f" brgy.{brgy}.{purok}." in line:
                raise Failure(f"a responder subscribed elsewhere received: {line[:120]}")

    def urgent_escalation():
        res, desk = ctx["resident"], ctx["desk"]
        res.send(f"REPORT brgy.{brgy}.{purok}.fire N {prefix} urgent escalation check, please ignore")
        rid = res.wait_for("REPORTED", lambda l: l.startswith("REPORTED ")).split()[1]
        topic, priority, body = desk.wait_msg("the escalated fire report", lambda t, b: b.get("report_id") == rid)
        if topic != f"city.iloilo.escalated.{brgy}" or priority != "URGENT" or not body.get("escalated"):
            raise Failure(f"expected URGENT escalation on city.iloilo.escalated.{brgy}, got {topic} {priority}")
        ctx["tanod"].send(f"STATUS {rid} RESOLVED {prefix} tanod tries")
        ctx["tanod"].wait_for("ERR: only the desk may resolve", lambda l: l.startswith("ERR "))
        desk.send(f"STATUS {rid} RESOLVED {prefix} handled by the desk")
        desk.wait_for("UPDATED RESOLVED", lambda l: l == f"UPDATED {rid} RESOLVED")

    def advisory():
        res, tanod = ctx["resident"], ctx["tanod"]
        res.send(f"SUB brgy.{brgy}.advisory")
        cleanup.append((res, f"UNSUB brgy.{brgy}.advisory"))
        res.send("SUBS")
        res.wait_for("SUBS reply", lambda l: l.startswith("SUBS") and f"brgy.{brgy}.advisory" in l)
        tanod.send(f"ADVISORY {brgy} NORMAL {prefix} test advisory, please ignore")
        aid = tanod.wait_for("POSTED", lambda l: l.startswith("POSTED ")).split()[1]
        res.wait_msg("the advisory", lambda t, b: b.get("advisory_id") == aid)

    try:
        ok = step("web app and /api/config are served", web_app)
        ok = ok and step("resident, responders and desk connect", connect_all)
        if ok:
            step("gateway refuses HELLO from a browser", gateway_filter)
            step("resident may not subscribe to incident topics", role_rules)
            if step("NORMAL report reaches the subscribed responder", normal_report):
                step("anonymous report hides the reporter", anonymous_report)
                if "anon_rid" in ctx:
                    step("RESPONDING and RESOLVED reach the resident", status_updates)
                step("HISTORY includes this run's report", history)
            step("resident withdraws an unanswered report", withdraw)
            step("responder on another purok receives none of it", not_leaked)
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

    passed = sum(results)
    print(f"\n{passed}/{len(results)} steps passed")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
