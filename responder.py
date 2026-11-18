"""responder.py
Owner: Kelly
Purpose: Responder CLI for tanods, captain, and city desk; ACK, STATUS, duplicate filtering.

Run (broker first), one terminal per person. Each asks for the account's PIN,
or for the desk the desk password (accounts: python users.py, see README):
    python responder.py --id SR-T01 --sub brgy.san-roque.purok-3.#
    python responder.py --id SR-CAPT --sub brgy.san-roque.#
    python responder.py --role desk --sub city.iloilo.escalated.#

Commands:
    sub <pattern> / unsub <pattern> / subs     what you receive
    history                                    current state of reports you cover
    respond <report_id> [note]                 STATUS ... RESPONDING
    resolve <report_id> [note]                 STATUS ... RESOLVED
    advisory <barangay> [urgent] <text>        post to brgy.<barangay>.advisory
Every MSG is ACKed; a message seen before prints "duplicate ... ignored".
"""

import argparse
import getpass
import sys

import client
import config
import topic_matcher


def handle(kind, data):
    if kind == "MSG":
        client.say(client.describe(data))
    elif kind == "UPDATED":
        report_id, status = data.split(" ", 1)
        client.say(f"OK: report {report_id} is now {status}.")
    elif kind == "POSTED":
        client.say(f"OK: advisory {data} posted.")
    elif kind == "SUBS":
        client.say("Subscribed to: " + (", ".join(data.split()) or "nothing yet (use sub <pattern>)"))
    elif kind == "HIST":
        client.say(client.history_line(data))
    elif kind == "HISTEND":
        client.say(f"({data} report(s))")
    elif kind == "DUPLICATE":
        client.say(f"duplicate {data} ignored (already shown; ACKed again so the broker stops resending)")
    elif kind == "ME":
        _, _, barangay = data.split(" ")
        where = config.BARANGAYS.get(barangay, barangay) if barangay != "-" else f"all of {config.DISTRICT_NAME}"
        client.say(f"Signed in. This account covers {where}.")
    elif kind == "ERR":
        client.say(f"! {data}")
        if data.startswith("sign-in failed") or data.endswith("must sign in with their PIN") \
                or data.endswith("must sign in with the desk password"):
            client.say("Check the ID and PIN (accounts are made with users.py).")
    elif kind == "CLOSED":
        client.say("Disconnected from the broker. Press Enter to exit.")


def advisory_line(rest):
    """'<barangay> [urgent] <text>' -> ADVISORY line, or raise ValueError."""
    barangay, _, text = rest.partition(" ")
    barangay = topic_matcher.normalize_level(barangay)
    if barangay not in config.BARANGAYS:
        raise ValueError(f"usage: advisory <barangay> [urgent] <text>; {barangay or '?'} is not a barangay of "
                         f"{config.DISTRICT_NAME}")
    priority = "NORMAL"
    first, _, remainder = text.partition(" ")
    if first.lower() == "urgent":
        priority, text = "URGENT", remainder
    text = " ".join(text.split())
    if not text:
        raise ValueError("usage: advisory <barangay> [urgent] <text>")
    return f"ADVISORY {barangay} {priority} {text}"


def main():
    parser = argparse.ArgumentParser(description="eSumbong responder (tanod, captain, city desk)")
    parser.add_argument("--id", help=f"your ID, one word, e.g. SR-T01 (the desk is always {config.DESK_ID})")
    parser.add_argument("--role", choices=("responder", "desk"), default="responder")
    parser.add_argument("--sub", action="append", default=[], metavar="PATTERN",
                        help="subscribe on start (repeatable), e.g. brgy.san-roque.#")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    args = parser.parse_args()
    if args.role == "desk":
        args.id = config.DESK_ID  # one city desk, password only
    elif not args.id:
        parser.error("--id is required for responders")
    client.utf8_console()
    try:
        secret = getpass.getpass("City desk password: " if args.role == "desk" else f"PIN for {args.id}: ")
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nbye")
    if not secret or " " in secret:
        sys.exit("! a PIN or password is one word with no spaces")

    c = client.Client(args.id, args.role, handle, args.host, args.port, secret=secret)
    c.send("WHOAMI")
    for pattern in args.sub:
        c.send(f"SUB {pattern}")
    c.send("SUBS")

    def status(new_status):
        def run(rest):
            report_id, _, note = rest.partition(" ")
            if not report_id:
                return print(f"! usage: {new_status.lower()} <report_id> [note]")
            c.send(f"STATUS {report_id} {new_status} {note}".rstrip())
        return run

    def one_pattern(command):
        def run(rest):
            if not rest or " " in rest:
                return print(f"! usage: {command.lower()} <pattern>, e.g. brgy.san-roque.#")
            c.send(f"{command} {rest}")
            if command == "SUB":
                c.send("HISTORY")  # reports filed before this subscription
        return run

    def advisory(rest):
        try:
            c.send(advisory_line(rest))
        except ValueError as exc:
            print(f"! {exc}")

    role = "city desk" if args.role == "desk" else "responder"
    client.run_shell(c, {
        "sub": (one_pattern("SUB"), "sub <pattern>", "receive reports on a topic, e.g. brgy.san-roque.#"),
        "unsub": (one_pattern("UNSUB"), "unsub <pattern>", "stop receiving a topic"),
        "subs": (lambda rest: c.send("SUBS"), "subs", "list your subscriptions"),
        "history": (lambda rest: c.send("HISTORY"), "history", "current state of reports you cover"),
        "respond": (status("RESPONDING"), "respond <report_id> [note]", "mark a report RESPONDING"),
        "resolve": (status("RESOLVED"), "resolve <report_id> [note]", "mark a report RESOLVED"),
        "advisory": (advisory, "advisory <barangay> [urgent] <text>", "post an announcement to residents"),
    }, banner=f"eSumbong {role} | {args.id} | {config.DISTRICT_NAME}, {config.CITY_NAME}")


if __name__ == "__main__":
    main()
