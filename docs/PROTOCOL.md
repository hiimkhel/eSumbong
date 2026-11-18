# Sumbong Protocol

- Every message is one line of UTF-8 plain text over TCP, ending with "\n". Commands are uppercase. Fields are separated by single spaces; the free-text field is always last and is read using a maxsplit (REPORT, STATUS and HIST: 4 parts; MSG: 5 parts).
- The MSG body is a single-line JSON object with fields: report_id, topic, category, priority, description, status, escalated, and reporter (omitted when the report is anonymous).

| Direction | Command | Meaning |
| --- | --- | --- |
| Client → Broker | HELLO <client_id> <role> [<secret>] | Identify as resident, responder, or desk. Responders add their PIN and the desk (client_id `city`) its password; residents send none. Silent on success; a refused sign-in gets `ERR sign-in failed: ...` (or `ERR too many failed sign-ins ...`) about 1 s later and the broker ends the connection |
| Subscriber → Broker | SUB <pattern> / UNSUB <pattern> | Register or remove a subscription |
| Resident → Broker | REPORT <topic> <anon:Y/N> <description> | File an incident |
| Broker → Resident | REPORTED <report_id> | Report stored; resident auto-subscribed to report.<report_id>.status |
| Broker → Subscriber | MSG <msg_id> <topic> <priority> <body> | Deliver one report, status update, or escalation |
| Subscriber → Broker | ACK <msg_id> | Mark message delivered |
| Responder → Broker | STATUS <report_id> <RESPONDING/RESOLVED> <note> | Publish a status update (responder or desk; note may be empty) |
| Resident → Broker | WITHDRAW <report_id> <reason> | Take back one's own report while it is still RECEIVED (reason optional); it becomes WITHDRAWN and is published like a status update, without updated_by |
| Broker → Responder | UPDATED <report_id> <status> | Status saved; the update is published as MSG on report.<report_id>.status and on the incident topic, with note and updated_by added to the body |
| Responder/Desk → Broker | ADVISORY <barangay> <URGENT/NORMAL> <text> | Post an announcement on brgy.<barangay>.advisory |
| Broker → Responder/Desk | POSTED <advisory_id> | Advisory stored and published; its MSG body has advisory_id, topic, barangay, priority, description, from (client_id) and from_role (responder/desk) |
| Client → Broker | SUBS | Ask for this client's saved subscriptions |
| Broker → Client | SUBS <pattern> <pattern> ... | Reply to SUBS; just "SUBS" when there are none |
| Client → Broker | HISTORY | Ask for the current state of reports this client's subscriptions cover (latest 50) |
| Broker → Client | HIST <topic> <priority> <body> | One report, oldest first; same body as MSG plus created_at (and anonymous for the reporter, note if any). Not ACKed |
| Broker → Client | HISTEND <count> | End of the HISTORY reply |
| Either way | PING / PONG | Heartbeat |
| Broker → Client | ERR <reason> | Malformed command or unknown report |

## Topics

- Scope: Jaro district, Iloilo City. <barangay> is one of the 42 levels in config.BARANGAYS (e.g. san-roque, mh-del-pilar); REPORT from anywhere else gets ERR. <purok> may be a purok or a landmark (e.g. purok-3, near-jaro-plaza).
- Sign-in (auth.py): responder and desk accounts live in the `users` table, made with `python users.py`. A responder account tied to a barangay may only SUB to `brgy.<that barangay>...`, send STATUS for that barangay's reports and post ADVISORY there. After 5 refused sign-ins an ID is locked for 5 minutes (config.MAX_FAILED_LOGINS, LOCKOUT_SECONDS).
- Who may SUB (escalation.py): the desk only city.iloilo.escalated.<barangay|*|#>; responders only brgy.…; residents only brgy.<barangay>.advisory. Residents get report.<report_id>.status added by the broker when they REPORT and cannot SUB to it. Saved subscriptions a role may not hold are dropped on HELLO.
- Incident topics: brgy.<barangay>.<purok>.<category>
- Advisory topic: brgy.<barangay>.advisory
- Status topic: report.<report_id>.status
- Escalation topic: city.iloilo.escalated.<barangay>
- * matches exactly one level; # matches zero or more levels and must be the last level.
- Fire, fight, and flood are URGENT; all other categories are NORMAL. Advisories are URGENT or NORMAL as posted.
- Catch-up on HELLO sends a client's waiting messages URGENT first, then NORMAL, each oldest first.

## Escalation (escalation.py)

- URGENT reports are escalated to the city desk the moment they are filed; the barangay's subscribers still receive them (with escalated true).
- Any report still RECEIVED after config.ESCALATE_SECONDS, or still RESPONDING config.UNRESOLVED_ESCALATE_SECONDS after it was filed, is escalated. Each report is escalated at most once, and never once RESOLVED.
- An escalation is published as MSG on city.iloilo.escalated.<barangay>, report.<report_id>.status and the incident topic, with escalated true and the reason in note. (An URGENT report filed just now goes only to the escalation topic as an extra message; its first MSG on the incident topic already says escalated.)
- Once escalated, a responder may still send RESPONDING, but only the desk may send RESOLVED.

Any change to this protocol requires a pull request reviewed by the whole team.
