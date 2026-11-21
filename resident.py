"""resident.py
Owner: Kelly
Purpose: Resident CLI to file reports and follow their status.

Run (broker first):
    python resident.py --id juan

Commands:
    report <barangay> <purok> <category> [anon] <what happened>
        e.g. report san-roque purok-3 noise anon Loud karaoke past midnight
    withdraw <report_id> [reason]    take back a report nobody has responded to
    follow <barangay>                get that barangay's advisories
    mine                             your reports and their status (HISTORY)
    barangays / categories           what you can type
Status updates on your own reports, and advisories, print as they arrive.
"""

import argparse

import client
import config
import topic_matcher


def parse_report(rest):
    """'<barangay> <purok> <category> [anon] <text>' -> REPORT line, or raise ValueError
    with a message for the resident. The broker checks everything again."""
    # maxsplit 3 keeps the free-text description in one piece, spaces included.
    parts = rest.split(" ", 3)
    if len(parts) < 4 or not parts[3].strip():
        raise ValueError("usage: report <barangay> <purok> <category> [anon] <what happened>")
    barangay, purok, category, text = parts
    # Topic levels are lowercase with dashes ("San Roque" -> san-roque), the same
    # form the responders subscribe with, so their patterns match.
    barangay, purok = topic_matcher.normalize_level(barangay), topic_matcher.normalize_level(purok)
    category = category.lower()
    if barangay not in config.BARANGAYS:
        raise ValueError(f"{barangay} is not a barangay of {config.DISTRICT_NAME}; type 'barangays'")
    if not purok:
        raise ValueError("give a purok or landmark, e.g. purok-3 or near-jaro-plaza")
    if category not in config.CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(config.CATEGORIES)}")
    # An optional leading word "anon" makes the report anonymous (anon field Y);
    # the broker then leaves the reporter out of every message it publishes.
    anon = "N"
    first, _, remainder = text.partition(" ")
    if first.lower() == "anon":
        anon, text = "Y", remainder
    text = " ".join(text.split())  # one line: the protocol ends each message at "\n"
    if not text:
        raise ValueError("say what happened after the category")
    return f"REPORT {topic_matcher.incident_topic(barangay, purok, category)} {anon} {text}"


def handle(kind, data):
    """Print one line from the broker. client.py has already ACKed each MSG and
    filtered out duplicates, so every MSG here is new."""
    if kind == "MSG":
        # Status updates on report.<id>.status (the broker subscribed us when we
        # filed) and advisories of the barangays we follow.
        client.say(client.describe(data))
    elif kind == "REPORTED":
        # The broker saved the report to the database before replying.
        client.say(f"Report {data} filed. Your barangay has been notified; updates will show here.")
    elif kind == "UPDATED":
        report_id, status = data.split(" ", 1)
        client.say(f"Report {report_id} is now {status}.")
    elif kind == "HIST":
        client.say(client.history_line(data))
    elif kind == "HISTEND":
        client.say(f"({data} report(s))")
    elif kind == "SUBS":
        # Subscriptions are stored by the broker, so they survive a restart; show
        # only the advisory ones (brgy.<barangay>.advisory).
        follows = [p.split(".")[1] for p in data.split() if p.endswith(".advisory")]
        if follows:
            client.say("Following advisories from: " + ", ".join(config.BARANGAYS.get(b, b) for b in follows))
    elif kind == "DUPLICATE":
        client.say(f"(duplicate {data} ignored)")
    elif kind == "ERR":
        client.say(f"! {data}")
    elif kind == "CLOSED":
        client.say("Disconnected from the broker. Press Enter to exit.")


def main():
    parser = argparse.ArgumentParser(description="eSumbong resident")
    parser.add_argument("--id", required=True, help="your ID, one word, e.g. juan-dc")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    args = parser.parse_args()
    client.utf8_console()

    # Residents sign in with an ID only (HELLO <id> resident). On HELLO the broker
    # sends any messages that waited while we were offline.
    c = client.Client(args.id, "resident", handle, args.host, args.port)

    def report(rest):
        try:
            c.send(parse_report(rest))
        except ValueError as exc:
            print(f"! {exc}")

    def withdraw(rest):
        report_id, _, reason = rest.partition(" ")
        if not report_id:
            return print("! usage: withdraw <report_id> [reason]")
        c.send(f"WITHDRAW {report_id} {reason}".rstrip())

    def follow(rest):
        barangay = topic_matcher.normalize_level(rest)
        if barangay not in config.BARANGAYS:
            return print(f"! usage: follow <barangay>, one of {config.DISTRICT_NAME}'s; type 'barangays'")
        # A resident may only subscribe to advisory topics; the broker refuses
        # anything else with ERR.
        c.send(f"SUB {topic_matcher.advisory_topic(barangay)}")
        print(f"Following advisories from {config.BARANGAYS[barangay]}.")

    c.send("SUBS")  # show which barangays we already follow from earlier sessions
    client.run_shell(c, {
        "report": (report, "report <barangay> <purok> <category> [anon] <text>", "file a report"),
        "withdraw": (withdraw, "withdraw <report_id> [reason]", "take back a report before anyone responds"),
        "follow": (follow, "follow <barangay>", "get that barangay's advisories"),
        "mine": (lambda rest: c.send("HISTORY"), "mine", "your reports and their status"),
        "barangays": (lambda rest: print("  " + ", ".join(config.BARANGAYS)), "barangays", "list barangay names to type"),
        "categories": (lambda rest: print("  " + ", ".join(config.CATEGORIES)
                                          + f"  (urgent: {', '.join(config.URGENT_CATEGORIES)})"),
                       "categories", "list categories"),
    }, banner=f"eSumbong resident | {args.id} | {config.DISTRICT_NAME}, {config.CITY_NAME}")


if __name__ == "__main__":
    main()
