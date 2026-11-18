"""status.py
Owner: Kelly
Purpose: Read-only status screen of reports and delivery history.

Run (any time, even before the first report):
    python status.py                 # print once
    python status.py --watch         # refresh every 2 seconds (Ctrl+C to stop)
    python status.py --db test.db --limit 30

It opens sumbong.db read-only (docs/DATABASE.md allows this) and never
changes anything. Anonymous reporters are shown as "(anonymous)".
"""

import argparse
import os
import sqlite3
import sys
import time

import config

CLOSED = config.CLOSED_STATUSES


def connect(path):
    """Open the database read-only, or return None if it does not exist yet."""
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table(headers, rows):
    """Plain fixed-width table."""
    widths = [max([len(str(h))] + [len(str(r[i])) for r in rows]) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(str(c).ljust(w) for c, w in zip(cells, widths)).rstrip()
    return "\n".join([line(headers), line("-" * w for w in widths), *(line(r) for r in rows)])


def short(text, width):
    text = str(text or "")
    return text if len(text) <= width else text[:width - 3] + "..."


def clock(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "-"


def render(conn, limit=20):
    """The whole screen as text. conn may be None (no database yet)."""
    out = [f"eSumbong status | {config.DISTRICT_NAME}, {config.CITY_NAME} | {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    if conn is None:
        out.append("No database yet. Start the broker (python broker.py); reports will appear here.")
        return "\n".join(out)
    try:
        reports = conn.execute("SELECT * FROM reports ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        counts = dict(conn.execute("SELECT status, COUNT(*) FROM reports GROUP BY status").fetchall())
        escalated = conn.execute("SELECT COUNT(*) FROM reports WHERE escalated = 1").fetchone()[0]
        deliveries = conn.execute(
            "SELECT d.msg_id, d.client_id, d.status, d.attempts, d.last_sent_at, m.topic, m.priority"
            " FROM deliveries d JOIN messages m ON m.msg_id = d.msg_id"
            " ORDER BY m.created_at DESC, m.rowid DESC LIMIT ?", (limit,)).fetchall()
        log = conn.execute("SELECT * FROM status_log ORDER BY time DESC, id DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.OperationalError:
        out.append("The database has no tables yet. Start the broker once to create them.")
        return "\n".join(out)

    total = sum(counts.values())
    summary = ", ".join(f"{counts.get(s, 0)} {s.lower()}" for s in config.REPORT_STATUSES)
    out.append(f"REPORTS: {total} total ({summary}; {escalated} escalated)")
    if reports:
        out.append(table(
            ["ID", "FILED", "BARANGAY", "PUROK", "CATEGORY", "PRIORITY", "STATUS", "ESC", "REPORTER", "ASSIGNED", "DESCRIPTION"],
            [[r["report_id"], clock(r["created_at"]), short(config.BARANGAYS.get(r["barangay"], r["barangay"]), 18),
              short(r["topic"].split(".")[2], 14), r["topic"].split(".")[3], r["priority"], r["status"],
              "yes" if r["escalated"] else "", "(anonymous)" if r["anonymous"] else r["reporter_id"],
              r["assigned_to"] or "", short(r["description"], 30)] for r in reports]))
    else:
        out.append("No reports yet.")

    out += ["", f"DELIVERIES (latest {limit}; PENDING = waiting for ACK)"]
    if deliveries:
        out.append(table(
            ["MSG", "TO", "TOPIC", "PRIORITY", "STATUS", "ATTEMPTS", "LAST SENT"],
            [[d["msg_id"], d["client_id"], short(d["topic"], 38), d["priority"], d["status"], d["attempts"],
              clock(d["last_sent_at"])] for d in deliveries]))
    else:
        out.append("No deliveries yet.")

    out += ["", f"STATUS LOG (latest {limit})"]
    if log:
        out.append(table(
            ["TIME", "REPORT", "STATUS", "BY", "NOTE"],
            [[clock(h["time"]), h["report_id"], h["status"], h["responder_id"] or "(system)",
              short(h["note"], 50)] for h in log]))
    else:
        out.append("No status changes yet.")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="eSumbong read-only status screen")
    parser.add_argument("--db", default=config.DB_PATH)
    parser.add_argument("--limit", type=int, default=20, help="rows per section (default 20)")
    parser.add_argument("--watch", nargs="?", type=float, const=2.0, metavar="SECONDS",
                        help="refresh every SECONDS (default 2) until Ctrl+C")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    def show():
        conn = connect(args.db)
        try:
            return render(conn, args.limit)
        finally:
            if conn is not None:
                conn.close()

    if args.watch is None:
        print(show())
        return
    try:
        while True:
            screen = show()
            os.system("cls" if os.name == "nt" else "clear")
            print(screen)
            print(f"\n(refreshing every {args.watch:g}s; Ctrl+C to stop)")
            time.sleep(args.watch)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
