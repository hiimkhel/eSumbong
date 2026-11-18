# Sumbong: A Publish-Subscribe Barangay Incident Reporting System

## Overview

Sumbong lets residents of **Jaro district, Iloilo City** (its 42 barangays) report incidents such as noise, fights, fires and floods. A central **broker** delivers each report, by topic, only to the responders who subscribed to that place, tracks its status until it is resolved, and **escalates** it to the Iloilo City desk when the barangay does not act in time.

- **Publish-subscribe by topic**: reports are published on `brgy.<barangay>.<purok>.<category>`. Responders subscribe with wildcards: `*` matches one level and `#` matches the rest (`brgy.san-roque.#`, `brgy.*.*.fire`).
- **Priorities**: fire, fight and flood are URGENT. They go to the top of the feed, are sent to the city desk at once, and are delivered first when an offline responder reconnects.
- **Reliable delivery (at-least-once)**: every report is saved to SQLite before it is confirmed, resent until the subscriber ACKs it, and kept for subscribers who are offline. Clients drop duplicates by message ID.
- **Status and escalation**: responders mark reports RESPONDING and RESOLVED, and the resident follows their own report. A report with no response within 2 minutes, or not resolved within 3 minutes of filing (demo timings), goes to the city desk, exactly once. A resident may withdraw a mistaken report before anyone responds.
- **Anonymity and access**: anonymous reports never reveal the reporter, not even in status updates. Each role may only subscribe to its own topics (desk: escalations, responders: barangay topics, residents: advisories).
- **Advisories**: captains, tanods and the city desk post announcements to a barangay's residents.

The protocol is in [docs/PROTOCOL.md](docs/PROTOCOL.md) and the database in [docs/DATABASE.md](docs/DATABASE.md).

## Requirements

- **Python 3.12 or newer**, standard library only. Tested on Python 3.13 on Windows 11.
- *Optional, web app only:* Node.js 18 or newer, to build the React interface in `frontend/`. The whole system, demo included, also runs without it from the command line.

## Setup

```
git clone https://github.com/hiimkhel/eSumbong.git
cd eSumbong
```

There is nothing to install for the command-line system. The database `sumbong.db` is created when the broker first starts. To start over, stop the broker and delete `sumbong.db*`.

Run the tests (117 tests, about 10 seconds):

```
python -m unittest discover -s tests
```

*Optional web app:* build it once with `cd frontend`, `npm install`, `npm run build`.

## How to Run (one command per terminal)

Start the broker first, then any number of clients, each in its own terminal, from the repository folder:

| Terminal | Command | Who |
| --- | --- | --- |
| 1 | `python broker.py` | the broker on 127.0.0.1:5050 (`--verbose` logs every line) |
| 2 | `python status.py --watch` | read-only status screen, refreshes every 2 s |
| 3 | `python responder.py --id tanod-a --sub brgy.san-roque.purok-3.#` | a tanod |
| 4 | `python responder.py --id city --role desk --sub city.iloilo.escalated.#` | the city desk |
| 5 | `python resident.py --id resident1` | a resident |

Type `help` in a client for its commands. The main ones:

- **Resident**: `report <barangay> <purok> <category> [anon] <what happened>`, `withdraw <report_id>`, `follow <barangay>`, `mine`.
- **Responder or desk**: `respond <report_id> [note]`, `resolve <report_id> [note]`, `advisory <barangay> [urgent] <text>`, `sub` / `unsub <pattern>`, `history`.

*Optional web app:* with the broker running, start `python frontend/gateway.py` and open http://127.0.0.1:8080. See [frontend/README.md](frontend/README.md).

Settings such as the port, timers and the barangay list are in [config.py](config.py).

## Demo Script

Delete `sumbong.db*` first for a clean start. Each step names the terminal to type in.

1. **Empty status screen.** Run `python broker.py`, then `python status.py --watch`. It shows "No reports yet."
2. **Connect Tanod A, Tanod B, Captain and the city desk**, plus one resident:
   ```
   python responder.py --id tanod-a --sub brgy.san-roque.purok-3.#
   python responder.py --id tanod-b --sub brgy.san-roque.purok-5.# --sub brgy.san-roque.advisory
   python responder.py --id captain --sub brgy.san-roque.purok-3.#
   python responder.py --id city --role desk --sub city.iloilo.escalated.#
   python resident.py --id resident1
   ```
3. **The anonymous noise report in Purok 3 reaches Tanod A and the Captain only.** As Resident 1: `report san-roque purok-3 noise anon Loud karaoke past midnight`. Tanod A and the Captain print it "from anonymous". Tanod B (Purok 5) and the city desk get nothing (noise is NORMAL).
4. **Tanod A sends RESPONDING and Resident 1 sees it.** As Tanod A: `respond <report_id> on the way`. Resident 1 prints "is now RESPONDING by tanod-a - on the way".
5. **Tanod A sends RESOLVED and Resident 1 sees it.** As Tanod A: `resolve <report_id> settled`. Resident 1 prints "is now RESOLVED".
6. **Close Tanod B, then send a fire report and an advisory.** Tanod B: `quit`. Captain: `advisory san-roque Clean-up drive on Saturday`. Then Resident 1: `report san-roque purok-5 fire Smoke near the chapel`. The city desk gets the fire report at once (URGENT).
7. **Reconnect Tanod B: the fire report arrives first.** Run `python responder.py --id tanod-b --drop-ack 1` (its subscriptions are remembered). The fire report prints before the older advisory (URGENT first).
8. **(Bonus) Dropped ACK shows a retry and "duplicate ignored".** Because of `--drop-ack 1`, Tanod B skipped its ACK for the fire report. About 5 seconds later the broker resends the same message and Tanod B prints "duplicate ... ignored". The status screen shows that delivery with ATTEMPTS 2.
9. **A noise report escalates to the city desk after 2 minutes.** As Resident 1: `report san-roque purok-3 noise Barking dogs all night`. Nobody responds. About 2 minutes later (checked every 10 s) the city desk prints "ESCALATED to the city ... No response within 2 minutes". Only the desk can resolve it now: as `city`, `resolve <report_id> handled by the city`.

## Team and Responsibilities

| Member | Module | Files |
| --- | --- | --- |
| Arvin | Broker | broker.py |
| Dominique | Topics & Subscriptions | topic_matcher.py |
| Allanah | Delivery & Storage | store.py |
| Jan Dennis | Status & Escalation | escalation.py |
| Kelly | Clients | resident.py, responder.py, status.py, client.py |
| Arvin | Web app (extra) | frontend/ (React interface and gateway.py) |

Tests are in `tests/`, one file per module, plus `test_clients.py` and `test_reliability.py` for the fault tests.

## Contribution Rules

- Never push directly to main
- One branch per module (feature/broker, feature/topics, feature/store, feature/escalation, feature/clients)
- Every pull request needs one reviewer
- Announce changes to config.py or docs/PROTOCOL.md in the group chat first
- Cite any borrowed code under References.

## References

Coulouris, G., Dollimore, J., Kindberg, T., & Blair, G. (2012). Distributed Systems: Concepts and Design (5th ed.). Addison-Wesley.

Barangays of Jaro district: Jaro, Iloilo City. (n.d.). In *Wikipedia*. https://en.wikipedia.org/wiki/Jaro,_Iloilo_City

Web app libraries (frontend only): React, Vite and Lucide icons, MIT/ISC licenses, installed with npm.

Borrowed code: none.
