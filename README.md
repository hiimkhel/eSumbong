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

Run the backend tests (139 tests, about 15 seconds). See [Testing](#testing) for the web app tests and the live-server check:

```
python -m unittest discover -s tests
```

*Optional web app:* install and build it once from `frontend/` (see [Web App Scripts](#web-app-scripts-react)):

```
cd frontend
npm install
npm run build
```

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

Settings such as the port, timers and the barangay list are in [config.py](config.py).

## Web App Scripts (React)

The web app needs the broker running (terminal 1 above). Run the Python commands from the repository folder and the `npm` commands from `frontend/`.

| Terminal | Folder | Command | What it does |
| --- | --- | --- | --- |
| 1 | repo | `python broker.py` | the broker (always first) |
| 2 | repo | `python frontend/gateway.py` | serves the built app and bridges browsers to the broker on http://127.0.0.1:8080 (`--port`, `--broker-host`, `--broker-port`, `--host 0.0.0.0` to allow other devices on the network, `--verbose`) |
| 3 | `frontend/` | `npm run dev` | *(while developing)* hot-reloading app on http://127.0.0.1:5173; `/api` is forwarded to the gateway on 8080 |

All `npm` scripts, run in `frontend/`:

| Command | When |
| --- | --- |
| `npm install` | once, and whenever `package.json` changes |
| `npm run build` | before using the app through the gateway (port 8080); writes `frontend/dist/` |
| `npm run dev` | live development server on port 5173 |
| `npm run preview` | serve the last build on port 4173, without the gateway (UI only; `/api` calls fail) |
| `npm test` | run the web app's tests once (about 15 seconds, no broker needed) |
| `npm run test:watch` | rerun the tests on every save |

Open http://127.0.0.1:8080 (or :5173 with `npm run dev`). The resident page is `#/resident` and the responder/desk page is `#/responder`. More in [frontend/README.md](frontend/README.md).

## Testing

There are three layers. The first two run on any machine with no server; the third checks a running deployment.

| Layer | Command | Covers |
| --- | --- | --- |
| Backend unit + integration (Python) | `python -m unittest discover -s tests` | topics, store, broker, escalation, CLI clients, fault/reliability tests, and the web gateway (`tests/test_gateway.py`: HTTP API, SSE bridge, command filter, static files) |
| Web app (React, Vitest) | `cd frontend` then `npm test` | protocol parsing, topic matching, the gateway client and its ACK/duplicate handling, every component, both hooks, and full Resident and Responder flows against a simulated gateway |
| Live server smoke test | `python tests/live_smoke.py --url <gateway URL>` | a real gateway + broker + database, end to end |

Run one Python file with `python -m unittest tests.test_gateway -v`, or one web test file with `npx vitest run src/pages/Responder.test.jsx`.

### Testing procedure on the live server

Do this after every deploy, or before a demo. Replace `<URL>` with the server, e.g. `http://127.0.0.1:8080`.

**1. Start the server** (skip if it is already running), one per terminal:

```
python broker.py
cd frontend && npm run build && cd ..
python frontend/gateway.py
```

**2. Automated smoke test** (about 5 seconds, from any machine that can reach the server):

```
python tests/live_smoke.py --url <URL>
python tests/live_smoke.py --url <URL> --full
```

Every step should print `PASS` and the last line should be `10/10 steps passed` (`12/12` with `--full`); the exit code is 1 on any failure. It checks that the app is served, connects a resident, two responders and the desk, and covers the gateway command filter, role rules, a NORMAL report, anonymity, RESPONDING/RESOLVED, HISTORY, WITHDRAW and topic isolation. `--full` adds an URGENT fire escalation to the city desk and an advisory.

The test writes to the live database. Its IDs (`smoke-res-<tag>` and so on) and purok (`smoke-<tag>`) are unique per run, every description starts with `[SMOKE TEST]`, every report ends RESOLVED or WITHDRAWN, and its subscriptions are removed at the end. Anyone subscribed to the whole barangay still sees the test reports, and `--full` notifies the city desk and the barangay's residents, so tell the group chat before running it on a server people are using. Use `--barangay <id>` to choose a quieter barangay.

**3. Manual browser check** (about 5 minutes). Use two browser windows, one of them private so the sign-ins don't mix, or a phone on the same network if the gateway runs with `--host 0.0.0.0`:

| # | Window | Action | Expected |
| --- | --- | --- | --- |
| 1 | A | Open `<URL>` | Home page loads; the bar shows Report and Responder desk |
| 2 | A | Responder desk, sign in as `tanod-test` (Responder), click the **All of Jaro** preset | Coverage shows `brgy.#`; the feed says "Listening for reports" |
| 3 | B | Report, sign in as `resident-test`, pick San Roque, `Purok 3`, Noise, type a description, **Send report** | Toast "Report sent"; the report appears under Your reports as Received |
| 4 | A | Watch the feed | The report appears with `resident-test` as reporter; the Open count goes up |
| 5 | A | Type a note, click **Respond** | Badge turns Responding; toast confirms |
| 6 | B | Watch the report | The tracker moves to Responding and shows the note |
| 7 | A | Click **Resolve** (within 3 minutes of step 3, see note below) | The card dims; the Resolved count goes up |
| 8 | B | Watch the report | Resolved; the hide (✕) button appears |
| 9 | B | Send an anonymous **Fire** report | Urgent warning before sending; "Escalated to city" badge after |
| 10 | A | Watch the feed | The fire report is at the top, marked Urgent, reporter "Anonymous" |
| 11 | B | Send another report, then **Withdraw report** and confirm | It shows "Withdrawn by the resident" in both windows |
| 12 | A | Post an advisory to San Roque; in B, click **Follow San Roque** first | B lists the advisory under Barangay advisories |
| 13 | B | Reload the page | Still signed in; earlier reports are restored |
| 14 | — | Stop the broker (Ctrl+C), wait a moment | Both windows return to sign-in with "Broker closed the connection" |
| 15 | — | Start the broker again and sign in with the same IDs | Reports and subscriptions are back |

**Timing:** with the demo timers in `config.py`, a report escalates to the city if nobody responds within 2 minutes, or if it is not resolved 3 minutes after filing. Once escalated, a tanod's card shows "Only the city desk can resolve it" instead of **Resolve**. Do steps 3–7 within 3 minutes, or resolve the report as the City desk (subscribe to `city.iloilo.escalated.#`).

Resolve or withdraw anything you created by hand. If a step fails, note the step number and open **Protocol log** at the bottom of the page: it shows every line sent and received.

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

Tests are in `tests/`, one file per module, plus `test_clients.py` and `test_reliability.py` for the fault tests, `test_gateway.py` for the web gateway and `live_smoke.py` for the live-server check. The web app's tests sit next to the code as `frontend/src/**/*.test.js(x)`, with a simulated gateway in `frontend/src/test/fakeGateway.js`.

## Contribution Rules

- Never push directly to main
- One branch per module (feature/broker, feature/topics, feature/store, feature/escalation, feature/clients)
- Every pull request needs one reviewer
- Announce changes to config.py or docs/PROTOCOL.md in the group chat first
- Cite any borrowed code under References.

## References

Coulouris, G., Dollimore, J., Kindberg, T., & Blair, G. (2012). Distributed Systems: Concepts and Design (5th ed.). Addison-Wesley.

Barangays of Jaro district: Jaro, Iloilo City. (n.d.). In *Wikipedia*. https://en.wikipedia.org/wiki/Jaro,_Iloilo_City

Web app libraries (frontend only): React, Vite and Lucide icons, MIT/ISC licenses, installed with npm. Web app test tools (development only): Vitest, jsdom and Testing Library, MIT licenses.

Borrowed code: none.
