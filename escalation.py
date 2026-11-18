"""escalation.py
Owner: Jan Dennis
Purpose: Status updates, escalation of unresolved reports, anonymity.

Status updates (STATUS <report_id> <RESPONDING/RESOLVED> <note>):
  * only responders and the city desk may send them (checked in broker.py);
  * a report only moves forward: RECEIVED -> RESPONDING -> RESOLVED, or
    straight from RECEIVED to RESOLVED for something settled on the spot;
  * once a report is escalated, only the city desk may resolve it; tanods
    can still respond, since they are usually closest;
  * the first responder to send RESPONDING is saved as assigned_to;
  * the resident who filed a report may WITHDRAW it (a mistake or a
    duplicate) while it is still RECEIVED; it becomes WITHDRAWN, is kept in
    the database like every report, never escalates, and responders and (if
    it was escalated) the city desk are told, without saying who withdrew it;
  * every change is written to status_log with who made it and the note;
  * the update is published on report.<id>.status, which the resident who
    filed it follows, and on the report's incident topic, so every responder
    covering that place sees it is being handled; for an escalated report
    also on city.iloilo.escalated.<barangay>, so the city desk is told.

Escalation to the city desk (topic city.iloilo.escalated.<barangay>):
  * URGENT reports (fire, fight, flood) are escalated the moment they are
    filed; the barangay's tanods still get them as usual;
  * a report nobody responded to within config.ESCALATE_SECONDS;
  * a report still not resolved config.UNRESOLVED_ESCALATE_SECONDS after it
    was filed;
  * each report is escalated exactly once (store.mark_escalated), and a
    resolved report never is. A background thread checks every
    config.ESCALATION_CHECK_SECONDS; the broker publishes the result on the
    escalation topic, the resident's status topic and the incident topic.

Anonymity: MSG bodies are built by broker.message_body(), which leaves out
the reporter of an anonymous report, so status updates and escalations
never reveal them.

Who may subscribe to what (scope: the barangays of Jaro, config.BARANGAYS):
  * the city desk only to escalations: city.iloilo.escalated.<barangay>;
  * responders only to barangay topics: brgy.<barangay>.<purok>.<category>
    and brgy.<barangay>.advisory;
  * residents only to their barangay's advisories: brgy.<barangay>.advisory.
    Residents follow their own reports through report.<id>.status, which
    the broker adds itself when they REPORT; they cannot SUB to it, so no
    one can read another resident's reports or learn who filed them.
  Saved subscriptions that break these rules are dropped on HELLO.

Like store.py, this module never touches sockets: it decides and records,
and the broker publishes.
"""

import logging
import threading
import time

import config
import store
import topic_matcher

log = logging.getLogger("escalation")

UPDATE_STATUSES = ("RESPONDING", "RESOLVED")

# Where a report may go from each status. Nothing moves backwards, and a
# RESOLVED report is closed.
ALLOWED_MOVES = {
    "RECEIVED": ("RESPONDING", "RESOLVED"),
    "RESPONDING": ("RESOLVED",),
    "RESOLVED": (),
    "WITHDRAWN": (),
}

MAX_NOTE = 200

# Status changes and escalations each check a report and then change it.
# Doing both steps under one lock means two responders pressing "Respond"
# at once, or a responder and the escalation thread, can never both win.
_lock = threading.Lock()


class StatusError(Exception):
    """A STATUS update that is refused. The message is sent back as ERR."""


# ---------------------------------------------------------------- status updates

def clean_note(note):
    """Trim a responder's note and cap its length."""
    return (note or "").strip()[:MAX_NOTE]


def apply_status(report_id, status, responder_id, role, note):
    """Check and save one status update; return the updated report.

    Raises StatusError if the status is not RESPONDING/RESOLVED, the report
    does not exist, the report cannot move to that status, or a tanod tries
    to resolve a report that was escalated to the city.
    """
    if status not in UPDATE_STATUSES:
        raise StatusError("status must be RESPONDING or RESOLVED")
    with _lock:
        report = store.get_report(report_id)
        if report is None:
            raise StatusError(f"unknown report {report_id[:16]}")
        if status not in ALLOWED_MOVES[report["status"]]:
            raise StatusError(f"report {report_id} is already {report['status']}")
        if status == "RESOLVED" and report["escalated"] and role != "desk":
            raise StatusError(f"report {report_id} was escalated; only the city desk can resolve it")
        report = store.update_report_status(report_id, status, responder_id)
        store.log_status(report_id, status, responder_id, note)
    return report


def withdraw(report_id, client_id, note):
    """The resident who filed a report takes it back; return the updated
    report. Raises StatusError if they did not file it or someone already
    responded. Unknown and other people's reports get the same answer, so
    no one can probe which report ids exist."""
    with _lock:
        report = store.get_report(report_id)
        if report is None or report["reporter_id"] != client_id:
            raise StatusError(f"you did not file report {report_id[:16]}")
        if report["status"] != "RECEIVED":
            raise StatusError(f"report {report_id} is already {report['status']}; "
                              "it can only be withdrawn before anyone responds")
        report = store.update_report_status(report_id, "WITHDRAWN", client_id)
        store.log_status(report_id, "WITHDRAWN", client_id, note)
    return report


def resolved_long_ago(report, history, now=None):
    """True for a report closed (resolved or withdrawn) more than
    config.RESOLVED_HIDE_SECONDS ago. HISTORY leaves these out so screens do
    not fill up with closed cases; the report itself is never deleted
    (status_log is the audit trail)."""
    if report["status"] not in config.CLOSED_STATUSES:
        return False
    closed = [h["time"] for h in history if h["status"] == report["status"]]
    if not closed:
        return False
    now = time.time() if now is None else now
    return now - closed[-1] > config.RESOLVED_HIDE_SECONDS


def status_topics(report):
    """Topics a status update is published on: the resident's status topic,
    the incident topic the responders subscribe to, and, once the report is
    escalated, the city desk's escalation topic, so the desk sees a tanod
    respond and everyone sees the desk resolve."""
    topics = [topic_matcher.status_topic(report["report_id"]), report["topic"]]
    if report["escalated"]:
        topics.append(topic_matcher.escalation_topic(report["barangay"]))
    return topics


# ---------------------------------------------------------------- subscriptions

def _barangay_ok(level):
    return level in (topic_matcher.SINGLE, topic_matcher.MULTI) or level in config.BARANGAYS


def subscription_error(role, pattern):
    """Why `role` may not subscribe to `pattern`, or None if it may.
    `pattern` is already a valid, normalized pattern."""
    levels = topic_matcher.split(pattern)
    if role == "desk":
        if levels[0] != "city":
            return "the city desk can only subscribe to city.iloilo.escalated.<barangay>"
        if len(levels) == 4 and not _barangay_ok(levels[3]):
            return f"{levels[3]} is not a barangay of {config.DISTRICT_NAME}"
        return None
    if role == "responder":
        if levels[0] != "brgy":
            return "responders can only subscribe to brgy.<barangay>... topics"
        if len(levels) > 1 and not _barangay_ok(levels[1]):
            return f"{levels[1]} is not a barangay of {config.DISTRICT_NAME}"
        return None
    if role == "resident":
        if len(levels) != 3 or levels[0] != "brgy" or levels[2] != "advisory" or levels[1] not in config.BARANGAYS:
            return "residents can only subscribe to brgy.<barangay>.advisory"
        return None
    return f"unknown role {role}"


def may_keep(role, pattern):
    """Whether a saved subscription survives HELLO in this role: anything the
    role could SUB to, plus report.<id>.status, which only the broker adds
    (for the resident who filed the report)."""
    parsed = topic_matcher.parse_topic(pattern)
    if parsed is not None and parsed["kind"] == "status":
        return True
    return subscription_error(role, pattern) is None


# ---------------------------------------------------------------- escalation

def escalate(report_id, reason):
    """Escalate one report and log why. Returns the updated report, or None
    if it was already escalated or is resolved (so it fires exactly once)."""
    with _lock:
        if not store.mark_escalated(report_id):
            return None
        store.log_status(report_id, "ESCALATED", None, reason)
        report = store.get_report(report_id)
    log.info("report %s escalated: %s", report_id, reason)
    return report


def escalate_if_urgent(report_id):
    """Called as a report is filed. Escalates fire, fight and flood at once.
    Returns (report, reason) if it was escalated, else (None, None)."""
    report = store.get_report(report_id)
    if report is None or report["priority"] != "URGENT":
        return None, None
    category = topic_matcher.parse_topic(report["topic"])["category"]
    reason = f"Urgent {category} report, sent to the city desk at once"
    escalated = escalate(report_id, reason)
    return (escalated, reason) if escalated else (None, None)


def _duration(seconds):
    if seconds % 3600 == 0:
        n, unit = seconds // 3600, "hour"
    elif seconds % 60 == 0:
        n, unit = seconds // 60, "minute"
    else:
        n, unit = seconds, "second"
    return f"{n:g} {unit}{'' if n == 1 else 's'}"


def due_for_escalation(now=None):
    """Reports whose time is up, each with the reason it is escalated."""
    no_response = f"No response within {_duration(config.ESCALATE_SECONDS)}"
    unresolved = f"Not resolved within {_duration(config.UNRESOLVED_ESCALATE_SECONDS)}"
    return ([(r, no_response) for r in store.reports_to_escalate(config.ESCALATE_SECONDS, now)]
            + [(r, unresolved) for r in store.reports_unresolved(config.UNRESOLVED_ESCALATE_SECONDS, now)])


def check_once(on_escalated, now=None):
    """Escalate every report whose time is up. on_escalated(report, reason)
    is called for each one actually escalated, so the broker can publish it.
    Returns how many were escalated."""
    count = 0
    for report, reason in due_for_escalation(now):
        escalated = escalate(report["report_id"], reason)
        if escalated is not None:
            on_escalated(escalated, reason)
            count += 1
    return count


def escalation_topics(report):
    """Topics an escalation is published on: the city desk's escalation
    topic, the resident's status topic, and the incident topic."""
    return [topic_matcher.escalation_topic(report["barangay"]),
            topic_matcher.status_topic(report["report_id"]),
            report["topic"]]


def start_escalation_thread(on_escalated, stop_event, check_every=None):
    """Start the background escalation check and return its thread. It runs
    check_once() every `check_every` seconds (default
    config.ESCALATION_CHECK_SECONDS) until stop_event is set."""
    check_every = config.ESCALATION_CHECK_SECONDS if check_every is None else check_every

    def loop():
        while not stop_event.wait(check_every):
            try:
                check_once(on_escalated)
            except Exception:  # keep checking even if one pass fails
                if not stop_event.is_set():
                    log.exception("escalation check failed")

    thread = threading.Thread(target=loop, name="escalation", daemon=True)
    thread.start()
    return thread
