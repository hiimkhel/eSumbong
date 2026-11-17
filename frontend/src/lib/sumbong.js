// Browser client for the eSumbong gateway (frontend/gateway.py).
// Speaks the line protocol in docs/PROTOCOL.md through the gateway.

async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export async function loadConfig() {
  const res = await fetch("/api/config");
  if (!res.ok) throw new Error("cannot load config from gateway");
  return res.json();
}

// Split on single spaces into at most n parts; the last part keeps the remainder.
function splitMax(line, n) {
  const out = [];
  let rest = line;
  while (out.length < n - 1) {
    const i = rest.indexOf(" ");
    if (i < 0) break;
    out.push(rest.slice(0, i));
    rest = rest.slice(i + 1);
  }
  out.push(rest);
  return out;
}

// Parse one broker line into a structured event.
export function parseLine(line) {
  const command = line.split(" ", 1)[0];
  if (command === "MSG") {
    const parts = splitMax(line, 5);
    let body = null;
    try { body = JSON.parse(parts[4] || ""); } catch { /* left null */ }
    return { command, msgId: parts[1], topic: parts[2], priority: parts[3], body, raw: line };
  }
  if (command === "REPORTED") return { command, reportId: splitMax(line, 2)[1], raw: line };
  if (command === "ERR") return { command, reason: splitMax(line, 2)[1] || "", raw: line };
  return { command, raw: line };
}

// Collapse user text into one protocol-safe line.
export function oneLine(text) {
  return String(text).replace(/\s+/g, " ").trim();
}

// A topic level: lowercase letters, digits, hyphen.
export function topicLevel(text) {
  return String(text).trim().toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
}

export class Connection {
  constructor({ onLine, onState }) {
    this.onLine = onLine;
    this.onState = onState || (() => {});
    this.session = null;
    this.events = null;
    this.seenMsgIds = new Set(); // duplicate filtering: the broker retries until ACKed
  }

  get connected() { return this.session !== null; }

  async connect(clientId, role) {
    await this.disconnect();
    const { session } = await postJSON("/api/connect", { client_id: clientId, role });
    this.session = session;
    this.events = new EventSource(`/api/events?session=${encodeURIComponent(session)}`);
    this.events.onmessage = (e) => this._handle(e.data);
    this.events.addEventListener("closed", () => this._lost("Broker closed the connection"));
    this.events.onerror = () => this._lost("Lost connection to the gateway");
    this.onState("online");
  }

  async disconnect() {
    if (!this.session) return;
    const session = this.session;
    this._teardown();
    this.onState("offline");
    await postJSON("/api/disconnect", { session }).catch(() => {});
  }

  async send(line) {
    if (!this.session) throw new Error("Not connected");
    await postJSON("/api/send", { session: this.session, line });
  }

  _handle(line) {
    const event = parseLine(line);
    if (event.command === "MSG") {
      // Always ACK, even duplicates, so the broker stops retrying.
      this.send(`ACK ${event.msgId}`).catch(() => {});
      if (this.seenMsgIds.has(event.msgId)) return;
      this.seenMsgIds.add(event.msgId);
    }
    this.onLine(event);
  }

  _lost(reason) {
    if (!this.session) return;
    this._teardown();
    this.onState("offline", reason);
  }

  _teardown() {
    if (this.events) this.events.close();
    this.events = null;
    this.session = null;
  }
}
