"""store.py
Owner: Allanah
Purpose: SQLite storage for reports, messages, subscriptions, deliveries, and status log; retry thread.

Schema: docs/DATABASE.md. Only this module runs SQL against sumbong.db.

Thread safety: the broker, the retry thread and the escalation daemon all
share one connection, guarded by a re-entrant lock. Every public function
takes the lock and runs in its own transaction, so callers never need to
lock anything themselves.

Usage:
    import store
    store.init_db()                 # or store.init_db(":memory:") in tests
    store.save_report(...)
"""

import logging
import sqlite3
import threading
import time

import config
import topic_matcher

log = logging.getLogger("store")

_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    report_id   TEXT PRIMARY KEY,
    topic       TEXT NOT NULL,
    barangay    TEXT NOT NULL,
    priority    TEXT NOT NULL,
    description TEXT NOT NULL,
    reporter_id TEXT,
    anonymous   INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'RECEIVED',
    assigned_to TEXT,
    escalated   INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    msg_id     TEXT PRIMARY KEY,
    report_id  TEXT,
    topic      TEXT NOT NULL,
    priority   TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    client_id TEXT NOT NULL,
    pattern   TEXT NOT NULL,
    UNIQUE (client_id, pattern)
);

CREATE TABLE IF NOT EXISTS deliveries (
    msg_id       TEXT NOT NULL,
    client_id    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'PENDING',
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_sent_at REAL,
    PRIMARY KEY (msg_id, client_id)
);

CREATE TABLE IF NOT EXISTS status_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id    TEXT NOT NULL,
    status       TEXT NOT NULL,
    responder_id TEXT,
    note         TEXT,
    time         REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deliveries_client_status ON deliveries (client_id, status);
CREATE INDEX IF NOT EXISTS idx_reports_status_escalated ON reports (status, escalated);
"""


# ---------------------------------------------------------------- lifecycle

def init_db(path=None):
    """Open (or create) the database and make sure every table exists.

    Safe to call on every broker start: existing data is kept, which is what
    lets the broker restart without losing reports or pending deliveries.
    Calling it again closes the previous connection first.
    """
    global _conn
    path = config.DB_PATH if path is None else path
    with _lock:
        if _conn is not None:
            _conn.close()
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        if path != ":memory:":
            # WAL lets status.py read while the broker writes.
            conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.commit()
        _conn = conn


def close_db():
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _db():
    if _conn is None:
        raise RuntimeError("store.init_db() has not been called")
    return _conn


def _now(ts):
    return time.time() if ts is None else ts


def _dict(row):
    return dict(row) if row is not None else None


# ---------------------------------------------------------------- reports

def save_report(report_id, topic, barangay, priority, description,
                reporter_id, anonymous, created_at=None):
    """Insert a new report with status RECEIVED. Raises sqlite3.IntegrityError
    if report_id already exists."""
    if priority not in ("URGENT", "NORMAL"):
        raise ValueError(f"bad priority: {priority}")
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO reports (report_id, topic, barangay, priority, description,"
            " reporter_id, anonymous, status, escalated, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'RECEIVED', 0, ?)",
            (report_id, topic, barangay, priority, description,
             reporter_id, 1 if anonymous else 0, _now(created_at)),
        )


def get_report(report_id):
    """Return the report as a dict, or None if it does not exist."""
    with _lock:
        row = _db().execute(
            "SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
    return _dict(row)


def list_reports():
    """Every report as a dict, oldest first. Used by HISTORY."""
    with _lock:
        rows = _db().execute(
            "SELECT * FROM reports ORDER BY created_at, rowid").fetchall()
    return [dict(r) for r in rows]


def update_report_status(report_id, status, responder_id=None):
    """Set a report's status and return the updated report (None if unknown).

    The first responder to send RESPONDING becomes assigned_to; later ones
    do not overwrite it.
    """
    if status not in config.REPORT_STATUSES:
        raise ValueError(f"bad report status: {status}")
    with _lock, _db() as conn:
        cur = conn.execute(
            "UPDATE reports SET status = ?,"
            " assigned_to = CASE WHEN assigned_to IS NULL AND ? = 'RESPONDING'"
            "                    THEN ? ELSE assigned_to END"
            " WHERE report_id = ?",
            (status, status, responder_id, report_id),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
    return _dict(row)


def reports_to_escalate(older_than=None, now=None):
    """Reports still RECEIVED, not yet escalated, and older than
    `older_than` seconds (default config.ESCALATE_SECONDS)."""
    older_than = config.ESCALATE_SECONDS if older_than is None else older_than
    cutoff = _now(now) - older_than
    with _lock:
        rows = _db().execute(
            "SELECT * FROM reports WHERE status = 'RECEIVED' AND escalated = 0"
            " AND created_at <= ? ORDER BY created_at",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def reports_unresolved(older_than=None, now=None):
    """Reports a responder took (RESPONDING) but has not RESOLVED, not yet
    escalated, filed at least `older_than` seconds ago (default
    config.UNRESOLVED_ESCALATE_SECONDS)."""
    older_than = config.UNRESOLVED_ESCALATE_SECONDS if older_than is None else older_than
    cutoff = _now(now) - older_than
    with _lock:
        rows = _db().execute(
            "SELECT * FROM reports WHERE status = 'RESPONDING' AND escalated = 0"
            " AND created_at <= ? ORDER BY created_at",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_escalated(report_id):
    """Flag a report as escalated. Returns True only for the call that
    actually flipped the flag, so escalation fires exactly once even if two
    threads race or the daemon re-checks the same report. Resolved and
    withdrawn reports are never escalated."""
    with _lock, _db() as conn:
        cur = conn.execute(
            "UPDATE reports SET escalated = 1"
            " WHERE report_id = ? AND escalated = 0 AND status NOT IN ('RESOLVED', 'WITHDRAWN')",
            (report_id,),
        )
    return cur.rowcount == 1


# ---------------------------------------------------------------- messages

def save_message(msg_id, report_id, topic, priority, body,
                 recipients=(), created_at=None):
    """Store a message and a PENDING delivery row for each recipient, in one
    transaction, so a crash can never leave a message without its deliveries.
    """
    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO messages (msg_id, report_id, topic, priority, body, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, report_id, topic, priority, body, _now(created_at)),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO deliveries (msg_id, client_id, status, attempts)"
            " VALUES (?, ?, 'PENDING', 0)",
            [(msg_id, cid) for cid in recipients],
        )


def get_message(msg_id):
    with _lock:
        row = _db().execute(
            "SELECT * FROM messages WHERE msg_id = ?", (msg_id,)).fetchone()
    return _dict(row)


# ---------------------------------------------------------------- subscriptions

def add_subscription(client_id, pattern):
    """Returns True if newly added, False if the client already had it."""
    with _lock, _db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO subscriptions (client_id, pattern) VALUES (?, ?)",
            (client_id, pattern),
        )
    return cur.rowcount == 1


def remove_subscription(client_id, pattern):
    """Returns True if a subscription was removed."""
    with _lock, _db() as conn:
        cur = conn.execute(
            "DELETE FROM subscriptions WHERE client_id = ? AND pattern = ?",
            (client_id, pattern),
        )
    return cur.rowcount == 1


def subscriptions_for(client_id):
    """Patterns a client is subscribed to, in the order they were added."""
    with _lock:
        rows = _db().execute(
            "SELECT pattern FROM subscriptions WHERE client_id = ? ORDER BY rowid",
            (client_id,),
        ).fetchall()
    return [r["pattern"] for r in rows]


def subscribers_for(topic):
    """Sorted client_ids with at least one pattern matching topic.

    Includes offline clients: subscriptions persist, so their deliveries
    stay PENDING until they reconnect.
    """
    with _lock:
        rows = _db().execute("SELECT client_id, pattern FROM subscriptions").fetchall()
    return sorted({r["client_id"] for r in rows
                   if topic_matcher.matches(r["pattern"], topic)})


# ---------------------------------------------------------------- deliveries

def add_delivery(msg_id, client_id):
    """Create a PENDING delivery. Returns False if it already existed."""
    with _lock, _db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO deliveries (msg_id, client_id, status, attempts)"
            " VALUES (?, ?, 'PENDING', 0)",
            (msg_id, client_id),
        )
    return cur.rowcount == 1


def mark_sent(msg_id, client_id, now=None):
    """Record one send attempt: attempts += 1, last_sent_at = now.
    Already DELIVERED rows are left untouched."""
    with _lock, _db() as conn:
        cur = conn.execute(
            "UPDATE deliveries SET attempts = attempts + 1, last_sent_at = ?"
            " WHERE msg_id = ? AND client_id = ? AND status = 'PENDING'",
            (_now(now), msg_id, client_id),
        )
    return cur.rowcount == 1


def mark_delivered(msg_id, client_id):
    """Handle ACK. Returns True if a PENDING delivery became DELIVERED;
    False for an unknown or repeated ACK (safe to ignore)."""
    with _lock, _db() as conn:
        cur = conn.execute(
            "UPDATE deliveries SET status = 'DELIVERED'"
            " WHERE msg_id = ? AND client_id = ? AND status = 'PENDING'",
            (msg_id, client_id),
        )
    return cur.rowcount == 1


def get_delivery(msg_id, client_id):
    with _lock:
        row = _db().execute(
            "SELECT * FROM deliveries WHERE msg_id = ? AND client_id = ?",
            (msg_id, client_id),
        ).fetchone()
    return _dict(row)


_PENDING_SELECT = (
    "SELECT d.msg_id, d.client_id, d.attempts, d.last_sent_at,"
    " m.report_id, m.topic, m.priority, m.body, m.created_at"
    " FROM deliveries d JOIN messages m ON m.msg_id = d.msg_id"
    " WHERE d.status = 'PENDING'"
)


def pending_for(client_id):
    """Every PENDING message for a client, oldest first. Used for offline
    catch-up when the client sends HELLO."""
    with _lock:
        rows = _db().execute(
            _PENDING_SELECT + " AND d.client_id = ? ORDER BY m.created_at, m.rowid",
            (client_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def due_for_retry(retry_seconds=None, now=None):
    """PENDING deliveries that were sent at least `retry_seconds` ago
    (default config.RETRY_SECONDS) and never ACKed, oldest first.

    Rows never sent (last_sent_at IS NULL) are excluded: those belong to
    clients that were offline, and are sent by catch-up on HELLO instead.
    The caller should skip clients that are not currently connected.
    """
    retry_seconds = config.RETRY_SECONDS if retry_seconds is None else retry_seconds
    cutoff = _now(now) - retry_seconds
    with _lock:
        rows = _db().execute(
            _PENDING_SELECT + " AND d.last_sent_at IS NOT NULL AND d.last_sent_at <= ?"
            " ORDER BY m.created_at, m.rowid",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def start_retry_thread(resend, stop_event, retry_seconds=None, check_every=1.0):
    """Start the background retry loop and return its thread.

    Every `check_every` seconds it looks up deliveries sent more than
    `retry_seconds` ago (default config.RETRY_SECONDS) without an ACK, and
    calls resend(row) for each. `row` is a dict from due_for_retry(). The
    broker's resend decides whether the client is online; this module never
    touches sockets. The loop ends once stop_event is set.
    """
    def loop():
        while not stop_event.wait(check_every):
            try:
                for row in due_for_retry(retry_seconds):
                    if stop_event.is_set():
                        break
                    resend(row)
            except Exception:  # keep retrying even if one pass fails
                if not stop_event.is_set():
                    log.exception("retry pass failed")

    thread = threading.Thread(target=loop, name="retry", daemon=True)
    thread.start()
    return thread


# ---------------------------------------------------------------- status log

def log_status(report_id, status, responder_id, note, at=None):
    """Append one row to status_log. Returns the new row id."""
    with _lock, _db() as conn:
        cur = conn.execute(
            "INSERT INTO status_log (report_id, status, responder_id, note, time)"
            " VALUES (?, ?, ?, ?, ?)",
            (report_id, status, responder_id, note, _now(at)),
        )
    return cur.lastrowid


def status_history(report_id):
    """All status changes for a report, oldest first."""
    with _lock:
        rows = _db().execute(
            "SELECT * FROM status_log WHERE report_id = ? ORDER BY time, id",
            (report_id,),
        ).fetchall()
    return [dict(r) for r in rows]
