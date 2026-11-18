"""client.py
Owner: Kelly
Purpose: Shared line client for resident.py and responder.py.

Connects to the broker, sends HELLO (with the PIN or desk password for
responders and the desk, see auth.py), answers PING, ACKs every MSG and drops
duplicates: the broker resends a message until it is ACKed (at-least-once
delivery), so the same msg_id can arrive twice.

Every broker line is handed to handler(kind, data):
    "MSG"        {"msg_id", "topic", "priority", "body"}  (new messages only)
    "DUPLICATE"  msg_id of a message already seen
    "CLOSED"     None, when the connection ends
    anything else: the command word (REPORTED, ERR, SUBS, ...) and the rest of the line
"""

import json
import socket
import sys
import threading
import time

import config


class Client:

    def __init__(self, client_id, role, handler, host=config.HOST, port=config.PORT, secret=None):
        self.client_id = client_id
        self.role = role
        self.handler = handler
        self.seen = set()  # msg_ids already shown
        self.closed = threading.Event()
        self._send_lock = threading.Lock()
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(None)
        self.send(f"HELLO {client_id} {role} {secret}" if secret else f"HELLO {client_id} {role}")
        threading.Thread(target=self._read, name="reader", daemon=True).start()

    def send(self, line):
        with self._send_lock:
            self.sock.sendall((line + "\n").encode(config.ENCODING))

    def close(self):
        if self.closed.is_set():
            return
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

    def _read(self):
        try:
            with self.sock.makefile("r", encoding=config.ENCODING, newline="\n") as stream:
                for raw in stream:
                    line = raw.rstrip("\r\n")
                    if line:
                        self._dispatch(line)
        except OSError:
            pass  # broker gone or we closed the socket
        finally:
            self.closed.set()
            self.handler("CLOSED", None)

    def _dispatch(self, line):
        command, _, rest = line.partition(" ")
        if command == "PING":
            self.send("PONG")
            return
        if command != "MSG":
            self.handler(command, rest)
            return
        msg_id, topic, priority, body = rest.split(" ", 3)
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"description": body}
        # ACK first, duplicates included, so the broker stops resending.
        self.send(f"ACK {msg_id}")
        if msg_id in self.seen:
            self.handler("DUPLICATE", msg_id)
            return
        self.seen.add(msg_id)
        self.handler("MSG", {"msg_id": msg_id, "topic": topic, "priority": priority, "body": body})


# ---------------------------------------------------------------- console helpers

PROMPT = "> "


def say(text):
    """Print a line from the reader thread without mangling the prompt."""
    sys.stdout.write(f"\r{time.strftime('%H:%M:%S')}  {text}\n{PROMPT}")
    sys.stdout.flush()


def place(topic):
    """brgy.san-roque.purok-3.fire -> 'San Roque, purok-3'."""
    levels = topic.split(".")
    if levels[0] == "brgy" and len(levels) >= 3:
        name = config.BARANGAYS.get(levels[1], levels[1])
        return name if levels[2] == "advisory" else f"{name}, {levels[2]}"
    return topic


def describe(msg):
    """One readable line for a MSG: a report, a status change, an escalation or an advisory."""
    body, topic = msg["body"], msg["topic"]
    flag = "[URGENT] " if msg["priority"] == "URGENT" else ""
    if "advisory_id" in body:
        office = "Iloilo City desk" if body.get("from_role") == "desk" else f"Barangay {place(topic)}"
        return f"{flag}ADVISORY for {place(topic)} from {office} ({body.get('from', '?')}): {body.get('description', '')}"
    rid = body.get("report_id", "?")
    who = body.get("reporter", "anonymous")
    what = f"{body.get('category', '?')} at {place(body.get('topic', topic))}"
    note = f" - {body['note']}" if body.get("note") else ""
    by = f" by {body['updated_by']}" if body.get("updated_by") else ""
    if topic.startswith("city."):
        return f"{flag}ESCALATED to the city: report {rid}, {what}, {body.get('status')}{by}{note}"
    if body.get("status", "RECEIVED") != "RECEIVED" or body.get("note"):
        return f"{flag}report {rid} ({what}) is now {body.get('status')}{by}{note}"
    escalated = ", also sent to the city" if body.get("escalated") else ""
    return f"{flag}NEW REPORT {rid}: {what}, from {who}{escalated}: \"{body.get('description', '')}\""


def history_line(rest):
    """HIST <topic> <priority> <body> -> one readable line."""
    topic, priority, body = rest.split(" ", 2)
    body = json.loads(body)
    flag = "[URGENT] " if priority == "URGENT" else ""
    esc = ", escalated" if body.get("escalated") else ""
    note = f" - {body['note']}" if body.get("note") else ""
    return (f"  {flag}{body['report_id']}  {body.get('category')} at {place(topic)}: "
            f"{body.get('status')}{esc}{note}  \"{body.get('description', '')}\"")


def run_shell(client, commands, banner):
    """Read commands until 'quit' or Ctrl+C.
    commands: name -> (function(rest), usage, explanation)."""
    commands = dict(commands)
    commands["help"] = (lambda rest: print_help(commands), "help", "show this list")
    commands["quit"] = (None, "quit", "disconnect (Ctrl+C works too)")
    print(banner)
    print_help(commands)
    try:
        while not client.closed.is_set():
            try:
                line = input(PROMPT).strip()
            except EOFError:
                break
            if not line:
                continue
            name, _, rest = line.partition(" ")
            if name in ("quit", "exit"):
                break
            entry = commands.get(name.lower())
            if entry is None:
                print(f"unknown command {name!r}; type 'help'")
                continue
            try:
                entry[0](rest.strip())
            except OSError as exc:
                print(f"! connection lost: {exc}")
                break
    except KeyboardInterrupt:
        print()
    finally:
        client.close()
        print("bye")


def print_help(commands):
    width = max(len(usage) for _, usage, _ in commands.values())
    for _, usage, explain in commands.values():
        print(f"  {usage.ljust(width)}  {explain}")


def utf8_console():
    """Barangay names and notes may contain non-ASCII text; Windows consoles
    default to a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
