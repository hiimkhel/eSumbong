"""broker.py
Owner: Arvin
Purpose: TCP server, one thread per client, command parsing, routing reports to subscribers.

Protocol: docs/PROTOCOL.md. One UTF-8 line per command, ending in "\\n".

Run:
    python broker.py                 # 127.0.0.1:5050, sumbong.db (from config.py)
    python broker.py --port 6000 --db test.db --verbose

Delivery is at-least-once:
  * every MSG is stored with a PENDING delivery row per subscriber, online or not;
  * a connected subscriber gets it at once; ACK <msg_id> marks it DELIVERED;
  * the retry thread resends unACKed messages every config.RETRY_SECONDS,
    with the same msg_id, so clients can drop duplicates;
  * a subscriber that was offline gets all its PENDING messages, oldest
    first, as soon as it sends HELLO (store-and-forward catch-up).
Because state lives in sumbong.db, all of this survives a broker restart.

STATUS rules (who may update, which moves are allowed) are in escalation.py.
Sign-in (PINs for responders, the desk password) is checked in auth.py.
"""

import argparse
import json
import logging
import os
import socket
import sqlite3
import threading
import time
import uuid

import auth
import config
import escalation
import store
import topic_matcher

MAX_LINE_BYTES = 4096
MAX_CLIENT_ID = 64
HISTORY_LIMIT = 50  # most recent reports sent in reply to HISTORY
FAILED_LOGIN_DELAY = 1.0  # seconds before ending a refused sign-in (slows PIN guessing)
REFUSED_LINGER_SECONDS = 5  # how long a refused connection may stay open before it is cut

log = logging.getLogger("broker")


class CommandError(Exception):
    """Raised by a handler; the broker answers with ERR <message>."""


# ---------------------------------------------------------------- sessions

class Session:
    """One TCP connection. client_id, role and barangay are set by HELLO;
    barangay is the one a responder account is tied to (None: all of Jaro)."""

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.client_id = None
        self.role = None
        self.barangay = None
        self.refused = False  # sign-in refused: lines are ignored until the client hangs up
        self._send_lock = threading.Lock()
        self.closed = threading.Event()

    @property
    def name(self):
        return self.client_id or f"{self.addr[0]}:{self.addr[1]}"

    def send(self, line):
        """Send one line. Returns False if the connection is gone."""
        data = (line + "\n").encode(config.ENCODING)
        try:
            with self._send_lock:
                self.sock.sendall(data)
            log.debug("-> %s: %s", self.name, line)
            return True
        except OSError:
            self.close()
            return False

    def refuse(self):
        """End a refused sign-in gracefully: stop sending (the ERR already sent
        arrives, followed by end-of-stream) but keep reading, and ignoring,
        until the client hangs up. Closing at once with the client's next
        line still unread would reset the connection, and the client could
        lose the ERR. Called from this session's own reader thread."""
        self.refused = True
        try:
            self.sock.settimeout(REFUSED_LINGER_SECONDS)
            self.sock.shutdown(socket.SHUT_WR)
        except OSError:
            self.close()

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


# ---------------------------------------------------------------- broker

class Broker:

    def __init__(self, host=config.HOST, port=config.PORT, db_path=None,
                 retry_seconds=config.RETRY_SECONDS, retry_check_seconds=1.0,
                 escalation_check_seconds=config.ESCALATION_CHECK_SECONDS,
                 require_auth=True):
        self.host = host
        self.port = port
        self.db_path = db_path
        self.retry_seconds = retry_seconds
        self.retry_check_seconds = retry_check_seconds
        self.escalation_check_seconds = escalation_check_seconds
        # Off only in tests that are not about sign-in; the real broker always checks.
        self.require_auth = require_auth
        self.failed_login_delay = FAILED_LOGIN_DELAY
        self._online = {}               # client_id -> Session
        self._online_lock = threading.Lock()
        self._stop = threading.Event()
        self._server = None
        self._threads = []
        self.handlers = {
            "HELLO": self.cmd_hello,
            "SUB": self.cmd_sub,
            "UNSUB": self.cmd_unsub,
            "REPORT": self.cmd_report,
            "ACK": self.cmd_ack,
            "STATUS": self.cmd_status,
            "WITHDRAW": self.cmd_withdraw,
            "ADVISORY": self.cmd_advisory,
            "PING": self.cmd_ping,
            "PONG": self.cmd_pong,
            "SUBS": self.cmd_subs,
            "HISTORY": self.cmd_history,
            "WHOAMI": self.cmd_whoami,
        }

    # ------------------------------------------------------------ lifecycle

    def start(self):
        """Open the database and start accepting clients in a background thread.
        Returns the (host, port) actually bound (port 0 picks a free one)."""
        store.init_db(self.db_path)
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            # On Windows SO_REUSEADDR would let two brokers share the port.
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen()
        srv.settimeout(0.5)  # so the accept loop notices stop()
        self._server = srv
        self.port = srv.getsockname()[1]
        t = threading.Thread(target=self._accept_loop, name="accept", daemon=True)
        t.start()
        self._threads.append(t)
        self._threads.append(store.start_retry_thread(
            self._resend, self._stop, self.retry_seconds, self.retry_check_seconds))
        self._threads.append(escalation.start_escalation_thread(
            self.publish_escalation, self._stop, self.escalation_check_seconds))
        log.info("listening on %s:%d (db: %s, retry every %ss)", self.host, self.port,
                 self.db_path or config.DB_PATH, self.retry_seconds)
        return self.host, self.port

    def stop(self):
        self._stop.set()
        if self._server is not None:
            self._server.close()
        with self._online_lock:
            sessions = list(self._online.values())
        for s in sessions:
            s.close()
        for t in self._threads:
            t.join(timeout=2)
        store.close_db()
        log.info("stopped")

    def serve_forever(self):
        self.start()
        try:
            while not self._stop.wait(0.5):  # short waits keep Ctrl+C working on Windows
                pass
        except KeyboardInterrupt:
            log.info("shutting down")
        finally:
            self.stop()

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                sock, addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sock.settimeout(None)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            session = Session(sock, addr)
            threading.Thread(target=self._client_loop, args=(session,),
                             name=f"client-{addr[1]}", daemon=True).start()

    # ------------------------------------------------------------ per client

    def _client_loop(self, session):
        log.info("connection from %s:%d", *session.addr)
        try:
            stream = session.sock.makefile("rb")
            while not session.closed.is_set():
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break  # client closed the connection
                if len(raw) > MAX_LINE_BYTES and not raw.endswith(b"\n"):
                    # Discard the rest of the oversized line, then complain.
                    while raw and not raw.endswith(b"\n"):
                        raw = stream.readline(MAX_LINE_BYTES + 1)
                    session.send("ERR line too long")
                    continue
                line = raw.decode(config.ENCODING, errors="replace").rstrip("\r\n")
                if line.strip():
                    self.handle_line(session, line)
        except OSError:
            pass  # connection reset: client crashed or network dropped
        finally:
            self._drop(session)

    def _drop(self, session):
        session.close()
        if session.client_id is None:
            return
        with self._online_lock:
            # Only remove the mapping if it still points at this session; a
            # reconnect with the same client_id may already have replaced it.
            if self._online.get(session.client_id) is session:
                del self._online[session.client_id]
                log.info("%s disconnected", session.client_id)

    def handle_line(self, session, line):
        log.debug("<- %s: %s", session.name, line)
        if session.refused:
            return  # sign-in was refused; waiting for the client to hang up
        command = line.split(" ", 1)[0]
        handler = self.handlers.get(command)
        try:
            if handler is None:
                raise CommandError(f"unknown command {command[:32]}")
            if session.client_id is None and command not in ("HELLO", "PING", "PONG"):
                raise CommandError("send HELLO <client_id> <role> [<pin/password>] first")
            handler(session, line)
        except CommandError as exc:
            session.send(f"ERR {exc}")
        except Exception:  # never let one bad command kill the client thread
            log.exception("error handling %r from %s", line, session.name)
            session.send("ERR internal error")

    # ------------------------------------------------------------ commands

    def cmd_hello(self, session, line):
        parts = line.split(" ")
        if len(parts) not in (3, 4) or not parts[1]:
            raise CommandError("usage: HELLO <client_id> <role> [<pin/password>]")
        _, client_id, role = parts[:3]
        secret = parts[3] if len(parts) == 4 else ""
        if session.client_id is not None:
            raise CommandError("already identified")
        if len(client_id) > MAX_CLIENT_ID or not client_id.isprintable():
            raise CommandError("client_id must be 1-64 printable characters")
        if role not in config.ROLES:
            raise CommandError(f"role must be one of {'/'.join(config.ROLES)}")
        # Check the PIN before anything else: a refused sign-in must not take
        # over (and disconnect) the real owner of that ID.
        user = None
        if self.require_auth:
            try:
                user = auth.check_login(client_id, role, secret)
            except auth.AuthError as exc:
                log.warning("refused sign-in as %s (%s) from %s", client_id, role, session.addr[0])
                time.sleep(self.failed_login_delay)  # before answering, so guessing is slow
                session.send(f"ERR {exc}")
                session.refuse()
                return
        session.client_id = client_id
        session.role = role
        session.barangay = user["barangay"] if user else None
        with self._online_lock:
            old = self._online.get(client_id)
            self._online[client_id] = session
        if old is not None:
            # Same client reconnected before its old socket died: newest wins.
            log.info("%s reconnected; closing old connection", client_id)
            old.close()
        log.info("%s online as %s", client_id, role)
        self._drop_disallowed_subscriptions(session)
        self.on_hello(session)

    @staticmethod
    def _drop_disallowed_subscriptions(session):
        """A client_id may have saved subscriptions from an older version or
        another role; keep only what this role may hold (escalation.py)."""
        for pattern in store.subscriptions_for(session.client_id):
            if not escalation.may_keep(session.role, pattern, session.barangay):
                store.remove_subscription(session.client_id, pattern)
                log.info("%s: dropped subscription %s (not allowed for %s)",
                         session.client_id, pattern, session.role)

    def on_hello(self, session):
        """Catch-up: send every message this client has not ACKed yet, oldest
        first. Covers messages published while it was offline, and messages
        sent to a connection that died before the ACK came back."""
        pending = store.pending_for(session.client_id)
        if not pending:
            return
        sent = sum(1 for row in pending
                   if self.send_to(session.client_id, row["msg_id"], self.msg_line(row)))
        log.info("catch-up: sent %d/%d pending message(s) to %s",
                 sent, len(pending), session.client_id)

    def cmd_sub(self, session, line):
        pattern = self._pattern_arg(line, "SUB")
        error = escalation.subscription_error(session.role, pattern, session.barangay)
        if error:
            raise CommandError(error)
        if store.add_subscription(session.client_id, pattern):
            log.info("%s subscribed to %s", session.client_id, pattern)

    def cmd_unsub(self, session, line):
        pattern = self._pattern_arg(line, "UNSUB")
        if store.remove_subscription(session.client_id, pattern):
            log.info("%s unsubscribed from %s", session.client_id, pattern)

    @staticmethod
    def _pattern_arg(line, command):
        parts = line.split(" ")
        if len(parts) != 2:
            raise CommandError(f"usage: {command} <pattern>")
        pattern = topic_matcher.normalize(parts[1])
        if not topic_matcher.is_valid_pattern(pattern):
            raise CommandError(f"invalid pattern {parts[1][:64]}")
        return pattern

    def cmd_report(self, session, line):
        parts = line.split(" ", 3)
        if len(parts) != 4 or not parts[3].strip():
            raise CommandError("usage: REPORT <topic> <anon:Y/N> <description>")
        _, topic, anon, description = parts
        if session.role != "resident":
            raise CommandError("only residents can REPORT")
        topic = topic_matcher.normalize(topic)
        parsed = topic_matcher.parse_topic(topic)
        if parsed is None or parsed["kind"] != "incident":
            raise CommandError(
                "topic must be brgy.<barangay>.<purok>.<category> with category one of "
                + "/".join(config.CATEGORIES))
        if parsed["barangay"] not in config.BARANGAYS:
            raise CommandError(f"{parsed['barangay'][:40]} is not a barangay of "
                               f"{config.DISTRICT_NAME}, {config.CITY_NAME}")
        anon = anon.upper()
        if anon not in ("Y", "N"):
            raise CommandError("anon must be Y or N")
        description = description.strip()
        priority = topic_matcher.priority_for(parsed["category"])

        report_id = self._save_new_report(topic, parsed["barangay"], priority,
                                          description, session.client_id, anon == "Y")
        # The reporter follows their own report's status, even while offline.
        store.add_subscription(session.client_id, topic_matcher.status_topic(report_id))
        session.send(f"REPORTED {report_id}")
        log.info("report %s from %s on %s (%s%s)", report_id, session.client_id, topic,
                 priority, ", anonymous" if anon == "Y" else "")

        # Fire, fight and flood go to the city desk at once. Escalating before
        # publishing means the tanods' copy already says escalated.
        report, reason = escalation.escalate_if_urgent(report_id)
        self.publish(topic, priority, report or store.get_report(report_id))
        if report is not None:
            self.publish(topic_matcher.escalation_topic(report["barangay"]), priority,
                         report, note=reason)

    @staticmethod
    def _save_new_report(topic, barangay, priority, description, reporter_id, anonymous):
        for _ in range(5):
            report_id = uuid.uuid4().hex[:8]
            try:
                store.save_report(report_id, topic, barangay, priority, description,
                                  reporter_id, anonymous)
                return report_id
            except sqlite3.IntegrityError:
                continue  # 8-char id collision; pick another
        raise CommandError("could not allocate a report id")

    def cmd_ack(self, session, line):
        parts = line.split(" ")
        if len(parts) != 2 or not parts[1]:
            raise CommandError("usage: ACK <msg_id>")
        # Unknown or repeated ACKs are ignored: at-least-once delivery means
        # clients may ACK the same message more than once.
        store.mark_delivered(parts[1], session.client_id)

    def cmd_status(self, session, line):
        """STATUS <report_id> <RESPONDING/RESOLVED> <note>. The rules live in
        escalation.py; the broker answers UPDATED and publishes the change."""
        parts = line.split(" ", 3)
        if len(parts) < 3 or not parts[1]:
            raise CommandError("usage: STATUS <report_id> <RESPONDING/RESOLVED> <note>")
        if session.role not in ("responder", "desk"):
            raise CommandError("only responders and the desk can send STATUS")
        report_id, status = parts[1], parts[2].upper()
        note = escalation.clean_note(parts[3] if len(parts) == 4 else "")
        try:
            report = escalation.apply_status(report_id, status, session.client_id,
                                             session.role, note, session.barangay)
        except escalation.StatusError as exc:
            raise CommandError(str(exc)) from None
        session.send(f"UPDATED {report_id} {status}")
        log.info("report %s is now %s (by %s)", report_id, status, session.client_id)
        for topic in escalation.status_topics(report):
            self.publish(topic, report["priority"], report,
                         note=note, updated_by=session.client_id)

    def cmd_withdraw(self, session, line):
        """WITHDRAW <report_id> [<reason>]: the resident who filed a report
        takes it back while nobody has responded (rules in escalation.py)."""
        parts = line.split(" ", 2)
        if len(parts) < 2 or not parts[1]:
            raise CommandError("usage: WITHDRAW <report_id> <reason>")
        if session.role != "resident":
            raise CommandError("only the resident who filed a report can WITHDRAW it")
        report_id = parts[1]
        note = escalation.clean_note(parts[2] if len(parts) == 3 else "") or "Withdrawn by the resident"
        try:
            report = escalation.withdraw(report_id, session.client_id, note)
        except escalation.StatusError as exc:
            raise CommandError(str(exc)) from None
        session.send(f"UPDATED {report_id} WITHDRAWN")
        log.info("report %s withdrawn by its reporter", report_id)
        # No updated_by: for an anonymous report it would name the reporter.
        for topic in escalation.status_topics(report):
            self.publish(topic, report["priority"], report, note=note)

    def cmd_advisory(self, session, line):
        """ADVISORY <barangay> <URGENT/NORMAL> <text>: a captain, tanod or the
        city desk posts an announcement on brgy.<barangay>.advisory, which
        residents of that barangay follow. Replies POSTED <advisory_id>."""
        parts = line.split(" ", 3)
        if len(parts) != 4 or not parts[3].strip():
            raise CommandError("usage: ADVISORY <barangay> <URGENT/NORMAL> <text>")
        if session.role not in ("responder", "desk"):
            raise CommandError("only responders and the desk can post an ADVISORY")
        _, barangay, priority, text = parts
        barangay = topic_matcher.normalize(barangay)
        if barangay not in config.BARANGAYS:
            raise CommandError(f"{barangay[:40]} is not a barangay of "
                               f"{config.DISTRICT_NAME}, {config.CITY_NAME}")
        if session.barangay and barangay != session.barangay:
            raise CommandError(f"your account is for {config.BARANGAYS[session.barangay]}; "
                               "you can only post advisories there")
        priority = priority.upper()
        if priority not in ("URGENT", "NORMAL"):
            raise CommandError("priority must be URGENT or NORMAL")
        advisory_id = uuid.uuid4().hex[:8]
        topic = topic_matcher.advisory_topic(barangay)
        body = json.dumps({
            "advisory_id": advisory_id, "topic": topic, "barangay": barangay,
            "priority": priority, "description": text.strip(),
            # Who posted it, so residents can tell an official notice from a prank.
            "from": session.client_id, "from_role": session.role,
        }, ensure_ascii=False, separators=(",", ":"))
        session.send(f"POSTED {advisory_id}")
        log.info("advisory %s for %s from %s (%s)", advisory_id, barangay, session.client_id, priority)
        self._publish_body(topic, priority, body, report_id=None)

    def cmd_subs(self, session, line):
        """SUBS -> SUBS <pattern> <pattern> ... (just "SUBS" when there are none).
        Lets a client that reconnects see the subscriptions the broker kept."""
        if line != "SUBS":
            raise CommandError("usage: SUBS")
        session.send(" ".join(["SUBS", *store.subscriptions_for(session.client_id)]))

    def cmd_history(self, session, line):
        """HISTORY -> one HIST <topic> <priority> <body> per report, oldest
        first, then HISTEND <count>. Covers the latest HISTORY_LIMIT reports
        the client's subscriptions reach: incident topics, the report's status
        topic (so residents get their own reports), and the escalation topic
        once a report is escalated. Reports resolved more than
        config.RESOLVED_HIDE_SECONDS ago are left out. HIST is not ACKed; it is a snapshot of each
        report's current state, not a delivery."""
        if line != "HISTORY":
            raise CommandError("usage: HISTORY")
        patterns = store.subscriptions_for(session.client_id)
        reports = []
        for report in store.list_reports():
            if not self._covers(patterns, report):
                continue
            history = store.status_history(report["report_id"])
            if escalation.resolved_long_ago(report, history):
                continue  # closed a while ago: kept in the database, not on screens
            reports.append((report, history))
        reports = reports[-HISTORY_LIMIT:]
        for report, history in reports:
            extra = {"created_at": report["created_at"]}
            if report["reporter_id"] == session.client_id:
                extra["anonymous"] = bool(report["anonymous"])  # only the reporter learns this
            if history and history[-1]["note"]:
                extra["note"] = history[-1]["note"]
            body = self.message_body(report, **extra)
            session.send(f"HIST {report['topic']} {report['priority']} {body}")
        session.send(f"HISTEND {len(reports)}")

    @staticmethod
    def _covers(patterns, report):
        topics = [report["topic"], topic_matcher.status_topic(report["report_id"])]
        if report["escalated"]:
            topics.append(topic_matcher.escalation_topic(report["barangay"]))
        return any(topic_matcher.any_match(patterns, t) for t in topics)

    def cmd_whoami(self, session, line):
        """WHOAMI -> ME <client_id> <role> <barangay>, with "-" when the account
        covers all of Jaro (or is not a barangay account). Lets a client offer
        only the coverage its account allows."""
        if line != "WHOAMI":
            raise CommandError("usage: WHOAMI")
        session.send(f"ME {session.client_id} {session.role} {session.barangay or '-'}")

    def cmd_ping(self, session, line):
        session.send("PONG")

    def cmd_pong(self, session, line):
        pass

    # ------------------------------------------------------------ fan-out

    @staticmethod
    def message_body(report, **extra):
        """JSON body for MSG (docs/PROTOCOL.md). reporter is omitted when the
        report is anonymous."""
        body = {
            "report_id": report["report_id"],
            "topic": report["topic"],
            "category": topic_matcher.parse_topic(report["topic"])["category"],
            "priority": report["priority"],
            "description": report["description"],
            "status": report["status"],
            "escalated": bool(report["escalated"]),
        }
        if not report["anonymous"]:
            body["reporter"] = report["reporter_id"]
        body.update(extra)
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    def publish(self, topic, priority, report, **extra):
        """Store one message for every subscriber of topic (online or not), then
        send it right away to those who are connected. Returns the msg_id."""
        return self._publish_body(topic, priority, self.message_body(report, **extra),
                                  report_id=report["report_id"])

    def _publish_body(self, topic, priority, body, report_id):
        """publish() for any JSON body (a report or an advisory)."""
        msg_id = uuid.uuid4().hex[:12]
        recipients = store.subscribers_for(topic)
        store.save_message(msg_id, report_id, topic, priority, body,
                           recipients=recipients)
        line = self.msg_line({"msg_id": msg_id, "topic": topic,
                              "priority": priority, "body": body})
        sent = 0
        for client_id in recipients:
            if self.send_to(client_id, msg_id, line):
                sent += 1
        log.info("published %s on %s to %d/%d subscribers online",
                 msg_id, topic, sent, len(recipients))
        return msg_id

    def publish_escalation(self, report, reason):
        """Escalation-thread callback: tell the city desk, the resident and
        the barangay's responders that a report went to the city."""
        for topic in escalation.escalation_topics(report):
            self.publish(topic, report["priority"], report, note=reason)

    @staticmethod
    def msg_line(row):
        """MSG <msg_id> <topic> <priority> <body> from a stored message row."""
        return f"MSG {row['msg_id']} {row['topic']} {row['priority']} {row['body']}"

    def _resend(self, row):
        """Retry-thread callback: resend one unACKed message if the client is
        online. Offline clients are skipped; HELLO catch-up handles them."""
        if self.send_to(row["client_id"], row["msg_id"], self.msg_line(row)):
            log.info("retry: resent %s to %s (attempt %d)",
                     row["msg_id"], row["client_id"], row["attempts"] + 1)

    def send_to(self, client_id, msg_id, line):
        """Send a MSG line to one client if connected, recording the attempt."""
        with self._online_lock:
            session = self._online.get(client_id)
        if session is None:
            return False
        # Count the attempt before sending: a fast client's ACK can otherwise
        # arrive first, and the attempt would never be recorded.
        store.mark_sent(msg_id, client_id)
        return session.send(line)

    def online_clients(self):
        with self._online_lock:
            return sorted(self._online)


def main():
    parser = argparse.ArgumentParser(description="Sumbong broker")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--db", default=config.DB_PATH, help="SQLite file (default: config.DB_PATH)")
    parser.add_argument("--verbose", action="store_true", help="log every line sent and received")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    Broker(args.host, args.port, args.db).serve_forever()


if __name__ == "__main__":
    main()
