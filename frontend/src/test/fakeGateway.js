// A stand-in for frontend/gateway.py: replaces fetch and EventSource so pages can
// be tested without a broker. Tests read what the browser sent (`sent`) and push
// broker lines into the open event stream (`emit`).
import { act } from "@testing-library/react";
import { vi } from "vitest";

export const CONFIG = {
  categories: ["noise", "drinking", "fight", "suspicious", "animals", "fire", "flood", "road"],
  urgent_categories: ["fire", "fight", "flood"],
  roles: ["resident", "responder", "desk"],
  report_statuses: ["RECEIVED", "RESPONDING", "RESOLVED", "WITHDRAWN"],
  city_name: "Iloilo City",
  district_name: "Jaro",
  barangays: [
    { id: "san-roque", name: "San Roque" },
    { id: "san-jose", name: "San Jose" },
    { id: "mh-del-pilar", name: "M.H. del Pilar" },
    { id: "tacas", name: "Tacas" },
  ],
};

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

export function installFakeGateway({ connectError = null } = {}) {
  const gw = {
    sent: [],          // lines POSTed to /api/send
    connects: [],      // bodies POSTed to /api/connect
    disconnects: [],
    streams: [],       // FakeEventSource instances
    sessionCount: 0,
    get stream() { return this.streams[this.streams.length - 1]; },
    /** Deliver one broker line to the newest stream, inside act(). */
    emit(line) { act(() => { this.stream.onmessage?.({ data: line }); }); },
    /** The broker closed the TCP link. */
    closeFromBroker() { act(() => { this.stream.listeners.closed?.forEach((fn) => fn({})); }); },
    /** The gateway went away. */
    error() { act(() => { this.stream.onerror?.({}); }); },
    lastSent(prefix = "") { return [...this.sent].reverse().find((l) => l.startsWith(prefix)); },
    sentMatching(prefix) { return this.sent.filter((l) => l.startsWith(prefix)); },
  };

  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.closed = false;
      this.listeners = {};
      this.onmessage = null;
      this.onerror = null;
      gw.streams.push(this);
    }
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
    close() { this.closed = true; }
  }

  const fetchMock = vi.fn(async (path, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : {};
    if (path === "/api/config") return jsonResponse(200, CONFIG);
    if (path === "/api/connect") {
      gw.connects.push(body);
      if (connectError) return jsonResponse(502, { error: connectError });
      gw.sessionCount += 1;
      return jsonResponse(200, { session: `s${gw.sessionCount}` });
    }
    if (path === "/api/send") {
      gw.sent.push(body.line);
      return jsonResponse(200, { ok: true });
    }
    if (path === "/api/disconnect") {
      gw.disconnects.push(body.session);
      return jsonResponse(200, { ok: true });
    }
    return jsonResponse(404, { error: "unknown endpoint" });
  });

  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", FakeEventSource);
  gw.fetch = fetchMock;
  return gw;
}

/** A MSG line as the broker sends it. */
export function msg(msgId, topic, priority, body) {
  return `MSG ${msgId} ${topic} ${priority} ${JSON.stringify(body)}`;
}

/** A HIST line as the broker sends it. */
export function hist(topic, priority, body) {
  return `HIST ${topic} ${priority} ${JSON.stringify(body)}`;
}
