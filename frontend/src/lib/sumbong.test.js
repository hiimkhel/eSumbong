import { describe, expect, it, vi } from "vitest";
import { installFakeGateway, msg } from "../test/fakeGateway.js";
import {
  Connection, loadConfig, oneLine, parseLine, reportCovered, storageGet, storageSet, topicLevel, topicMatches,
} from "./sumbong.js";

describe("parseLine", () => {
  it("parses MSG with a JSON body that may contain spaces", () => {
    const e = parseLine(msg("m1", "brgy.san-roque.purok-3.noise", "NORMAL", { report_id: "r1", description: "loud music here" }));
    expect(e).toMatchObject({
      command: "MSG", msgId: "m1", topic: "brgy.san-roque.purok-3.noise", priority: "NORMAL",
      body: { report_id: "r1", description: "loud music here" },
    });
  });

  it("leaves body null when MSG JSON is broken", () => {
    expect(parseLine("MSG m1 t NORMAL {oops").body).toBeNull();
  });

  it("parses HIST and HISTEND", () => {
    expect(parseLine('HIST brgy.a.b.fire URGENT {"report_id":"r9"}')).toMatchObject({
      command: "HIST", topic: "brgy.a.b.fire", priority: "URGENT", body: { report_id: "r9" },
    });
    expect(parseLine("HISTEND 3").count).toBe(3);
    expect(parseLine("HISTEND").count).toBe(0);
  });

  it("parses SUBS with and without patterns", () => {
    expect(parseLine("SUBS brgy.a.# brgy.b.advisory").patterns).toEqual(["brgy.a.#", "brgy.b.advisory"]);
    expect(parseLine("SUBS").patterns).toEqual([]);
  });

  it("parses REPORTED, POSTED, UPDATED and ERR", () => {
    expect(parseLine("REPORTED abc").reportId).toBe("abc");
    expect(parseLine("POSTED adv1").advisoryId).toBe("adv1");
    expect(parseLine("UPDATED abc RESOLVED")).toMatchObject({ reportId: "abc", status: "RESOLVED" });
    expect(parseLine("ERR report abc is already RESOLVED").reason).toBe("report abc is already RESOLVED");
    expect(parseLine("ERR").reason).toBe("");
  });

  it("keeps the raw line and passes unknown commands through", () => {
    expect(parseLine("PONG")).toEqual({ command: "PONG", raw: "PONG" });
  });
});

describe("oneLine and topicLevel", () => {
  it("collapses whitespace and newlines into one protocol-safe line", () => {
    expect(oneLine("  smoke\n near \t the  chapel ")).toBe("smoke near the chapel");
  });

  it("turns free text into one topic level", () => {
    expect(topicLevel("Purok 3")).toBe("purok-3");
    expect(topicLevel("  Near Jaro Plaza! ")).toBe("near-jaro-plaza");
    expect(topicLevel("a.b#c*")).toBe("abc"); // no level separators or wildcards
  });
});

describe("topicMatches (mirrors topic_matcher.matches)", () => {
  it.each([
    ["brgy.jaro.purok-1.fire", "brgy.jaro.purok-1.fire", true],
    ["brgy.jaro.purok-1.fire", "brgy.jaro.purok-1.flood", false],
    ["brgy.jaro.purok-1", "brgy.jaro.purok-1.fire", false],
    ["brgy.jaro.*.fire", "brgy.jaro.purok-1.fire", true],
    ["brgy.jaro.*", "brgy.jaro.purok-1.fire", false],
    ["brgy.jaro.*.fire", "brgy.jaro.fire", false],
    ["report.*.status", "report.ab12.status", true],
    ["brgy.jaro.#", "brgy.jaro.purok-1.fire", true],
    ["brgy.jaro.#", "brgy.jaro", true],
    ["#", "city.iloilo.escalated.jaro", true],
    ["brgy.jaro.#", "brgy.molo.purok-1.fire", false],
    ["brgy.*.#", "brgy.jaro", true],
    ["brgy.*.#", "brgy", false],
    ["brgy.#.fire", "brgy.jaro.purok-1.fire", false],
    ["brgy.ja*.purok-1.fire", "brgy.jaro.purok-1.fire", false],
  ])("%s vs %s -> %s", (pattern, topic, expected) => {
    expect(topicMatches(pattern, topic)).toBe(expected);
  });
});

describe("reportCovered", () => {
  const report = { topic: "brgy.san-roque.purok-3.noise", escalated: false };

  it("is covered by the incident topic or the status topic", () => {
    expect(reportCovered(["brgy.san-roque.#"], "r1", report)).toBe(true);
    expect(reportCovered(["report.r1.status"], "r1", report)).toBe(true);
    expect(reportCovered(["brgy.tacas.#"], "r1", report)).toBe(false);
    expect(reportCovered([], "r1", report)).toBe(false);
  });

  it("is covered by the city escalation topic only once escalated", () => {
    const pats = ["city.iloilo.escalated.#"];
    expect(reportCovered(pats, "r1", report)).toBe(false);
    expect(reportCovered(pats, "r1", { ...report, escalated: true })).toBe(true);
    expect(reportCovered(["city.iloilo.escalated.san-roque"], "r1", { ...report, escalated: true })).toBe(true);
  });
});

describe("storage helpers", () => {
  it("round-trips JSON and removes on null", () => {
    storageSet("localStorage", "k", { id: "a" });
    expect(storageGet("localStorage", "k")).toEqual({ id: "a" });
    storageSet("localStorage", "k", null);
    expect(storageGet("localStorage", "k")).toBeNull();
  });

  it("never throws when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(storageGet("sessionStorage", "k")).toBeNull();
    expect(() => storageSet("sessionStorage", "k", 1)).not.toThrow();
  });

  it("returns null for corrupt values", () => {
    localStorage.setItem("bad", "{not json");
    expect(storageGet("localStorage", "bad")).toBeNull();
  });
});

describe("loadConfig", () => {
  it("returns the gateway config", async () => {
    installFakeGateway();
    expect((await loadConfig()).district_name).toBe("Jaro");
  });

  it("throws when the gateway is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 502, json: async () => ({}) })));
    await expect(loadConfig()).rejects.toThrow("cannot load config");
  });
});

describe("Connection", () => {
  function setup() {
    const gw = installFakeGateway();
    const onLine = vi.fn();
    const onState = vi.fn();
    const conn = new Connection({ onLine, onState });
    return { gw, conn, onLine, onState };
  }

  it("connects, opens the event stream and reports online", async () => {
    const { gw, conn, onState } = setup();
    await conn.connect("tanod-a", "responder");
    expect(gw.connects).toEqual([{ client_id: "tanod-a", role: "responder" }]);
    expect(gw.stream.url).toBe("/api/events?session=s1");
    expect(conn.connected).toBe(true);
    expect(onState).toHaveBeenLastCalledWith("online");
  });

  it("sends the PIN only when there is one", async () => {
    const { gw, conn } = setup();
    await conn.connect("tanod-a", "responder", "1234");
    await conn.connect("juan", "resident");
    expect(gw.connects).toEqual([
      { client_id: "tanod-a", role: "responder", secret: "1234" },
      { client_id: "juan", role: "resident" },
    ]);
  });

  it("surfaces a refused sign-in", async () => {
    installFakeGateway({ accounts: { "tanod-a": "1234" } });
    const conn = new Connection({ onLine: () => {} });
    await expect(conn.connect("tanod-a", "responder", "0000")).rejects.toThrow("sign-in failed");
    expect(conn.connected).toBe(false);
  });

  it("surfaces the gateway's error message when connect fails", async () => {
    installFakeGateway({ connectError: "cannot reach broker at 127.0.0.1:5050" });
    const conn = new Connection({ onLine: () => {} });
    await expect(conn.connect("x", "resident")).rejects.toThrow("cannot reach broker");
    expect(conn.connected).toBe(false);
  });

  it("ACKs every MSG and drops duplicates by message id", async () => {
    const { gw, conn, onLine } = setup();
    await conn.connect("tanod-a", "responder");
    const line = msg("m1", "brgy.a.b.noise", "NORMAL", { report_id: "r1" });
    gw.stream.onmessage({ data: line });
    gw.stream.onmessage({ data: line }); // broker retry
    await vi.waitFor(() => expect(gw.sentMatching("ACK")).toEqual(["ACK m1", "ACK m1"]));
    expect(onLine).toHaveBeenCalledTimes(1);
    expect(onLine.mock.calls[0][0]).toMatchObject({ command: "MSG", msgId: "m1" });
  });

  it("does not ACK non-MSG lines", async () => {
    const { gw, conn, onLine } = setup();
    await conn.connect("r", "resident");
    gw.stream.onmessage({ data: "REPORTED abc" });
    expect(onLine).toHaveBeenCalledWith(expect.objectContaining({ command: "REPORTED", reportId: "abc" }));
    expect(gw.sentMatching("ACK")).toEqual([]);
  });

  it("send() posts the line, and refuses when not connected", async () => {
    const { gw, conn } = setup();
    await expect(conn.send("SUBS")).rejects.toThrow("Not connected");
    await conn.connect("r", "resident");
    await conn.send("SUBS");
    expect(gw.sent).toEqual(["SUBS"]);
  });

  it("goes offline with a reason when the broker or gateway is lost", async () => {
    const { gw, conn, onState } = setup();
    await conn.connect("r", "resident");
    const stream = gw.stream;
    stream.listeners.closed[0]({});
    expect(onState).toHaveBeenLastCalledWith("offline", "Broker closed the connection");
    expect(stream.closed).toBe(true);
    expect(conn.connected).toBe(false);

    await conn.connect("r", "resident");
    gw.stream.onerror({});
    expect(onState).toHaveBeenLastCalledWith("offline", "Lost connection to the gateway");
  });

  it("disconnect() closes the stream and tells the gateway", async () => {
    const { gw, conn, onState } = setup();
    await conn.connect("r", "resident");
    await conn.disconnect();
    expect(gw.disconnects).toEqual(["s1"]);
    expect(gw.stream.closed).toBe(true);
    expect(onState).toHaveBeenLastCalledWith("offline");
    await conn.disconnect(); // second call is a no-op
    expect(gw.disconnects).toEqual(["s1"]);
  });

  it("reconnecting closes the previous session first", async () => {
    const { gw, conn } = setup();
    await conn.connect("a", "resident");
    await conn.connect("b", "resident");
    expect(gw.disconnects).toEqual(["s1"]);
    expect(gw.streams[0].closed).toBe(true);
    expect(gw.stream.url).toContain("s2");
  });
});
