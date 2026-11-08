# Sumbong Protocol

- Every message is one line of UTF-8 plain text over TCP, ending with "\n". Commands are uppercase. Fields are separated by single spaces; the free-text field is always last and is read using a maxsplit (REPORT and STATUS: 4 parts; MSG: 5 parts).
- The MSG body is a single-line JSON object with fields: report_id, topic, category, priority, description, status, escalated, and reporter (omitted when the report is anonymous).

| Direction | Command | Meaning |
| --- | --- | --- |
| Client → Broker | HELLO <client_id> <role> | Identify as resident, responder, or desk |
| Subscriber → Broker | SUB <pattern> / UNSUB <pattern> | Register or remove a subscription |
| Resident → Broker | REPORT <topic> <anon:Y/N> <description> | File an incident |
| Broker → Resident | REPORTED <report_id> | Report stored; resident auto-subscribed to report.<report_id>.status |
| Broker → Subscriber | MSG <msg_id> <topic> <priority> <body> | Deliver one report, status update, or escalation |
| Subscriber → Broker | ACK <msg_id> | Mark message delivered |
| Responder → Broker | STATUS <report_id> <RESPONDING/RESOLVED> <note> | Publish a status update |
| Either way | PING / PONG | Heartbeat |
| Broker → Client | ERR <reason> | Malformed command or unknown report |

## Topics

- Incident topics: brgy.<barangay>.<purok>.<category>
- Advisory topic: brgy.<barangay>.advisory
- Status topic: report.<report_id>.status
- Escalation topic: city.iloilo.escalated.<barangay>
- * matches exactly one level; # matches zero or more levels and must be the last level.
- Fire, fight, and flood are URGENT; all other categories are NORMAL.

Any change to this protocol requires a pull request reviewed by the whole team.
