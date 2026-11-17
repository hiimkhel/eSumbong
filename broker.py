"""broker.py
Owner: Arvin
Purpose: TCP server, one thread per client, command parsing, routing reports to subscribers.

Protocol: docs/PROTOCOL.md. One UTF-8 line per command, ending in "\\n".

Run:
    python broker.py                 # 127.0.0.1:5050, sumbong.db (from config.py)
    python broker.py --port 6000 --db test.db --verbose

Pass 2 scope: sessions, HELLO / SUB / UNSUB / REPORT / ACK / PING / PONG,
report ids, persistence through store.py, and live fan-out of MSG to
connected subscribers. Offline subscribers get a PENDING delivery row that
the Pass 3 retry / catch-up code will send. STATUS arrives in Pass 4.
"""

import argparse
import json
import logging
import os
import socket
import sqlite3
import threading
import uuid

import config
import store
import topic_matcher

MAX_LINE_BYTES = 4096
MAX_CLIENT_ID = 64

log = logging.getLogger("broker")


class CommandError(Exception):
    """Raised by a handler; the broker answers with ERR <message>."""


# ---------------------------------------------------------------- sessions

class Session:
    """One TCP connection. client_id and role are set by HELLO."""

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.client_id = None
        self.role = None
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

    def __init__(self, host=config.HOST, port=config.PORT, db_path=None):
        self.host = host
        self.port = port
        self.db_path = db_path
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
            "PING": self.cmd_ping,
            "PONG": self.cmd_pong,
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
        log.info("listening on %s:%d (db: %s)", self.host, self.port,
                 self.db_path or config.DB_PATH)
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
        command = line.split(" ", 1)[0]
        handler = self.handlers.get(command)
        try:
            if handler is None:
                raise CommandError(f"unknown command {command[:32]}")
            if session.client_id is None and command not in ("HELLO", "PING", "PONG"):
                raise CommandError("send HELLO <client_id> <role> first")
            handler(session, line)
        except CommandError as exc:
            session.send(f"ERR {exc}")
        except Exception:  # never let one bad command kill the client thread
            log.exception("error handling %r from %s", line, session.name)
            session.send("ERR internal error")

    # ------------------------------------------------------------ commands

    def cmd_hello(self, session, line):
        parts = line.split(" ")
        if len(parts) != 3 or not parts[1]:
            raise CommandError("usage: HELLO <client_id> <role>")
        _, client_id, role = parts
        if session.client_id is not None:
            raise CommandError("already identified")
        if len(client_id) > MAX_CLIENT_ID or not client_id.isprintable():
            raise CommandError("client_id must be 1-64 printable characters")
        if role not in config.ROLES:
            raise CommandError(f"role must be one of {'/'.join(config.ROLES)}")
        session.client_id = client_id
        session.role = role
        with self._online_lock:
            old = self._online.get(client_id)
            self._online[client_id] = session
        if old is not None:
            # Same client reconnected before its old socket died: newest wins.
            log.info("%s reconnected; closing old connection", client_id)
            old.close()
        log.info("%s online as %s", client_id, role)
        self.on_hello(session)

    def on_hello(self, session):
        """Hook for Pass 3: send this client's PENDING deliveries (catch-up)."""

    def cmd_sub(self, session, line):
        pattern = self._pattern_arg(line, "SUB")
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

        self.publish(topic, priority, store.get_report(report_id))

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
        raise CommandError("STATUS is not available yet")  # Pass 4

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
        msg_id = uuid.uuid4().hex[:12]
        body = self.message_body(report, **extra)
        recipients = store.subscribers_for(topic)
        store.save_message(msg_id, report["report_id"], topic, priority, body,
                           recipients=recipients)
        line = f"MSG {msg_id} {topic} {priority} {body}"
        sent = 0
        for client_id in recipients:
            if self.send_to(client_id, msg_id, line):
                sent += 1
        log.info("published %s on %s to %d/%d subscribers online",
                 msg_id, topic, sent, len(recipients))
        return msg_id

    def send_to(self, client_id, msg_id, line):
        """Send a MSG line to one client if connected, recording the attempt."""
        with self._online_lock:
            session = self._online.get(client_id)
        if session is None or not session.send(line):
            return False
        store.mark_sent(msg_id, client_id)
        return True

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
