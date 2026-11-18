# eSumbong Web Frontend

A React (Vite) interface for eSumbong. Browsers cannot open raw TCP sockets, so a small
gateway (`gateway.py`, Python 3.12 standard library only) sits between the browser
and the broker:

```
Browser (React)  --HTTP + Server-Sent Events-->  gateway.py  --TCP (docs/PROTOCOL.md)-->  broker.py
```

The gateway does not change the protocol. Each browser tab gets its own TCP
connection to the broker and sends the same one-line commands the CLI clients send.

## Layout

| Path | Purpose |
| --- | --- |
| `gateway.py` | Serves the React build (`dist/`) and bridges browser sessions to the broker |
| `index.html`, `vite.config.js`, `package.json` | Vite project setup |
| `src/App.jsx` | Hash routes: `#/` role picker, `#/resident`, `#/responder` |
| `src/pages/Resident.jsx` | File reports and follow their status and barangay advisories |
| `src/pages/Responder.jsx` | Tanod / captain / city desk feed: subscribe, RESPONDING, RESOLVED |
| `src/hooks/useConnection.js` | One broker session per page, plus its protocol log |
| `src/lib/sumbong.js` | Gateway client: connect, send commands, parse broker lines, ACK messages |
| `src/components/` | App bar, sign-in, toast, protocol log, and `ui.jsx` (logo, status tracker, badges, empty states) |
| `src/lib/format.js` | Category labels and icons, place names from topics, times |
| `src/styles.css` | eSumbong design system: brand tokens, type, components (light and dark) |
| `public/logo.svg` | Rise logo, also the favicon |
| `src/**/*.test.js(x)` | Vitest tests, next to the code they test |
| `src/test/` | Test setup and `fakeGateway.js`, a simulated gateway for page tests |

Icons come from [Lucide](https://lucide.dev) (`lucide-react`).

## Requirements

- Python 3.12 (broker and gateway)
- Node.js 18 or newer (only to build or develop the web app)

## How to Run

Build the web app once, from `frontend/`:

```
npm install
npm run build
```

Then from the repository root, one command per terminal:

```
python broker.py
python frontend/gateway.py
```

Open http://127.0.0.1:8080. Residents sign in with an ID only; responders need an
account and PIN, and the city desk its password (create them with `python users.py`,
see the main README). PINs are sent once to the gateway, which passes them to the
broker in HELLO; the browser never stores them, so responders enter the PIN again
after a reload. Serve the gateway over HTTPS (e.g. behind a reverse proxy) anywhere
but your own machine, or PINs cross the network in plain text. Use `--port` to change the web port and
`--broker-host` / `--broker-port` to point at a broker other than the one in `config.py`.

## Developing

Keep the broker and gateway running, then in `frontend/`:

```
npm run dev
```

Open http://127.0.0.1:5173. Edits reload instantly, and `/api` requests are forwarded
to the gateway on port 8080. Run `npm run build` again before testing through port 8080.

## Scripts

| Command | What it does |
| --- | --- |
| `npm install` | install dependencies (once, and after `package.json` changes) |
| `npm run dev` | development server on :5173 with hot reload |
| `npm run build` | production build into `dist/`, served by `gateway.py` |
| `npm run preview` | serve `dist/` on :4173 without the gateway (UI only) |
| `npm test` | run all web app tests once |
| `npm run test:watch` | rerun tests on every save |

## Testing

`npm test` needs no broker or gateway: `src/test/fakeGateway.js` replaces `fetch` and
`EventSource`, records each line the page sends, and lets a test push broker lines
(`MSG`, `UPDATED`, `ERR`, ...) into the event stream. The tests cover:

- `lib/`: line parsing, topic matching (same cases as `tests/test_topics.py`), storage helpers, and `Connection` (connect, ACK every MSG, drop duplicate message IDs, lost connection)
- `components/` and `hooks/`: every component, `useConnection` and `useDismissed`
- `pages/`: full Resident flows (validate, report, anonymous, urgent, follow status, withdraw, hide, history, advisories) and Responder/desk flows (subscribe, presets, ERR rollback, feed order and filters, respond, resolve, escalation rules, advisories)
- `App.test.jsx`: hash routing and page titles

The gateway itself is tested in Python (`tests/test_gateway.py`). For the deployed
system, see "Testing procedure on the live server" in the main [README](../README.md#testing).
