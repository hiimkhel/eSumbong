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
| `src/components/` | Header, toast, status pills, protocol log |
| `src/styles.css` | eSumbong brand styles (light and dark) |
| `public/logo.svg` | Rise logo, also the favicon |

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

Open http://127.0.0.1:8080. Use `--port` to change the web port and
`--broker-host` / `--broker-port` to point at a broker other than the one in `config.py`.

## Developing

Keep the broker and gateway running, then in `frontend/`:

```
npm run dev
```

Open http://127.0.0.1:5173. Edits reload instantly, and `/api` requests are forwarded
to the gateway on port 8080. Run `npm run build` again before testing through port 8080.
