# Sumbong Web Frontend

A browser interface for Sumbong. Browsers cannot open raw TCP sockets, so a small
gateway (`gateway.py`, Python 3.12 standard library only) sits between the browser
and the broker:

```
Browser  --HTTP + Server-Sent Events-->  gateway.py  --TCP (docs/PROTOCOL.md)-->  broker.py
```

The gateway does not change the protocol. Each browser tab gets its own TCP
connection to the broker and sends the same one-line commands the CLI clients send.

## Layout

| Path | Purpose |
| --- | --- |
| `gateway.py` | Serves `static/` and bridges browser sessions to the broker |
| `static/index.html` | Role picker |
| `static/resident.html` | File reports and follow their status |
| `static/responder.html` | Tanod / captain / city desk feed: ACK, RESPONDING, RESOLVED |
| `static/css/style.css` | Shared styles (light and dark) |
| `static/js/sumbong.js` | Shared client: connect, send commands, parse broker lines |

## How to Run

From the repository root, one command per terminal:

```
python broker.py
python frontend/gateway.py
```

Then open http://127.0.0.1:8080 in a browser. Use `--port` to change the web port
and `--broker-host` / `--broker-port` to point at a broker other than the one in
`config.py`.
