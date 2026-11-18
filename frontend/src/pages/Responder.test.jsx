import { beforeEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../components/Toast.jsx";
import { setBarangays } from "../lib/format.js";
import { CONFIG, hist, installFakeGateway, msg } from "../test/fakeGateway.js";
import Responder from "./Responder.jsx";

let gw;
let user;

beforeEach(() => {
  gw = installFakeGateway();
  user = userEvent.setup({ delay: null });
  setBarangays(CONFIG.barangays); // App.jsx does this from /api/config
});

const PIN = "1234";
const DESK_PASSWORD = "city-pass-1";

function renderPage() {
  return render(<ToastProvider><Responder /></ToastProvider>);
}

// Responders type an ID and PIN; the desk only its password.
async function fillSignIn(id, role, secret) {
  if (role === "desk") {
    await user.click(screen.getByRole("radio", { name: /city desk/i }));
    await user.type(screen.getByLabelText(/Desk password/), secret ?? DESK_PASSWORD);
  } else {
    await user.type(screen.getByRole("textbox"), id);
    await user.type(screen.getByLabelText(/^PIN/), secret ?? PIN);
  }
  await user.click(screen.getByRole("button", { name: /continue/i }));
}

async function signIn(id = "tanod-a", role = "responder") {
  renderPage();
  await fillSignIn(id, role);
  await screen.findByRole("heading", { name: "Incoming reports" });
  await waitFor(() => expect(gw.sent).toEqual(["WHOAMI", "SUBS", "HISTORY"]));
}

const report = (id, over = {}) => ({
  report_id: id, topic: "brgy.san-roque.purok-3.noise", category: "noise", priority: "NORMAL",
  description: `Report ${id}`, status: "RECEIVED", escalated: false, reporter: "juan", ...over,
});

function deliver(msgId, body, topic = body.topic) {
  gw.emit(msg(msgId, topic, body.priority, body));
}

const feed = () => within(screen.getByRole("region", { name: "Report feed" }));
const card = (id) => screen.getByText(`#${id}`).closest("li");
const stat = (label) => screen.getByText(label, { selector: ".stat-label" }).parentElement.querySelector(".stat-value").textContent;

describe("Responder sign-in", () => {
  it("a responder signs in with an ID and PIN", async () => {
    await signIn("tanod-a");
    expect(gw.connects).toEqual([{ client_id: "tanod-a", role: "responder", secret: PIN }]);
  });

  it("the city desk signs in with a password only", async () => {
    renderPage();
    await user.click(screen.getByRole("radio", { name: /city desk/i }));
    expect(screen.queryByRole("textbox")).toBeNull(); // no ID field
    await user.type(screen.getByLabelText(/Desk password/), DESK_PASSWORD);
    await user.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByRole("heading", { name: "Incoming reports" });
    expect(gw.connects).toEqual([{ client_id: "city", role: "desk", secret: DESK_PASSWORD }]);
    expect(screen.getByText("City desk", { selector: ".eyebrow" })).toBeInTheDocument();
    expect(screen.getByText("No coverage yet")).toBeInTheDocument();
  });

  it("requires the PIN before connecting", async () => {
    renderPage();
    await user.type(screen.getByRole("textbox"), "tanod-a");
    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByText("Enter your PIN.")).toBeInTheDocument();
    expect(gw.connects).toEqual([]);
  });

  it("shows a refused sign-in on the form and clears the PIN", async () => {
    gw = installFakeGateway({ accounts: { "tanod-a": PIN, city: DESK_PASSWORD } });
    renderPage();
    await fillSignIn("tanod-a", "responder", "9999");
    expect(await screen.findByText(/Couldn't sign in: sign-in failed: wrong ID, PIN or password/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^PIN/)).toHaveValue("");
    expect(screen.queryByRole("heading", { name: "Incoming reports" })).toBeNull();

    await user.type(screen.getByLabelText(/^PIN/), PIN);
    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByRole("heading", { name: "Incoming reports" })).toBeInTheDocument();
  });

  it("never stores the PIN and asks for it again after a reload", async () => {
    await signIn("tanod-a");
    const stored = JSON.stringify({ ...sessionStorage }) + JSON.stringify({ ...localStorage });
    expect(stored).not.toContain(PIN);
    expect(sessionStorage.getItem("esumbong.signin.responder")).toBeNull();
    // The protocol log shows HELLO without the PIN.
    expect(screen.getByText(/HELLO tanod-a responder ••••/)).toBeInTheDocument();

    cleanup();
    renderPage(); // "reload": the ID is remembered, the PIN is not
    expect(screen.getByRole("textbox")).toHaveValue("tanod-a");
    expect(screen.getByLabelText(/^PIN/)).toHaveValue("");
    expect(gw.connects).toHaveLength(1); // no automatic sign-in
  });
});

describe("Coverage (subscriptions)", () => {
  it("subscribes to a typed pattern, then pulls history", async () => {
    await signIn();
    await user.type(screen.getByLabelText("Topic pattern"), "brgy.San-Roque.#");
    await user.click(screen.getByRole("button", { name: "Subscribe" }));
    await waitFor(() => expect(gw.sent.slice(-2)).toEqual(["SUB brgy.san-roque.#", "HISTORY"]));
    expect(within(screen.getByRole("list", { name: "Subscriptions" })).getByText("brgy.san-roque.#")).toBeInTheDocument();
    expect(screen.getByText("Listening for reports")).toBeInTheDocument();
  });

  it("subscribes with a preset and disables it once held", async () => {
    await signIn();
    await user.click(screen.getByRole("button", { name: /all of jaro/i }));
    await waitFor(() => expect(gw.lastSent("SUB")).toBe("SUB brgy.#"));
    expect(screen.getByRole("button", { name: /all of jaro/i })).toBeDisabled();
  });

  it("a barangay account is offered only its own barangay", async () => {
    await signIn();
    expect(screen.getByRole("button", { name: /all of jaro/i })).toBeInTheDocument(); // until ME arrives
    gw.emit("ME tanod-a responder san-roque");
    expect(screen.queryByRole("button", { name: /all of jaro/i })).toBeNull();
    await user.click(screen.getByRole("button", { name: /all of san roque/i }));
    await waitFor(() => expect(gw.lastSent("SUB")).toBe("SUB brgy.san-roque.#"));
    await user.click(screen.getByLabelText("Topic pattern"));
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["San Roquebrgy.san-roque.#"]);
  });

  it("a barangay account's refused SUB explains why", async () => {
    await signIn();
    await user.click(screen.getByRole("button", { name: /all of jaro/i }));
    gw.emit("ERR your account is for San Roque; subscribe to brgy.san-roque.# or topics under it");
    expect(await screen.findByText("Broker error: your account is for San Roque; subscribe to brgy.san-roque.# or topics under it")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Subscriptions" })).toBeNull();
  });

  it("the desk's preset is the city escalation topic", async () => {
    await signIn("city", "desk");
    await user.click(screen.getByRole("button", { name: /escalated to the city/i }));
    await waitFor(() => expect(gw.lastSent("SUB")).toBe("SUB city.iloilo.escalated.#"));
  });

  it("rejects patterns with spaces and duplicates", async () => {
    await signIn();
    gw.emit("SUBS brgy.tacas.#");
    await user.type(screen.getByLabelText("Topic pattern"), "brgy tacas");
    await user.click(screen.getByRole("button", { name: "Subscribe" }));
    expect(await screen.findByText(/A topic pattern is one word/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Topic pattern"));
    await user.type(screen.getByLabelText("Topic pattern"), "brgy.tacas.#");
    await user.click(screen.getByRole("button", { name: "Subscribe" }));
    expect(await screen.findByText("Already subscribed to brgy.tacas.#")).toBeInTheDocument();
    expect(gw.sentMatching("SUB ")).toEqual([]);
  });

  it("rolls the chip back when the broker refuses the SUB", async () => {
    await signIn();
    await user.type(screen.getByLabelText("Topic pattern"), "city.iloilo.escalated.#");
    await user.click(screen.getByRole("button", { name: "Subscribe" }));
    await waitFor(() => expect(gw.lastSent("SUB")).toBe("SUB city.iloilo.escalated.#"));
    gw.emit("ERR responders may only subscribe to brgy topics");
    expect(await screen.findByText("Broker error: responders may only subscribe to brgy topics")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Subscriptions" })).toBeNull();
  });

  it("unsubscribing drops reports only that subscription covered", async () => {
    await signIn();
    gw.emit("SUBS brgy.san-roque.# brgy.tacas.#");
    deliver("m1", report("r1"));
    deliver("m2", report("r2", { topic: "brgy.tacas.purok-1.noise" }));
    await feed().findByText("#r2");
    await user.click(screen.getByRole("button", { name: "Unsubscribe from brgy.tacas.#" }));
    await waitFor(() => expect(gw.lastSent("UNSUB")).toBe("UNSUB brgy.tacas.#"));
    expect(feed().queryByText("#r2")).toBeNull();
    expect(feed().getByText("#r1")).toBeInTheDocument();
  });

  it("a SUBS reply drops reports no longer covered", async () => {
    await signIn();
    gw.emit("SUBS brgy.san-roque.#");
    deliver("m1", report("r1"));
    await feed().findByText("#r1");
    gw.emit("SUBS");
    await waitFor(() => expect(feed().queryByText("#r1")).toBeNull());
  });
});

describe("The report feed", () => {
  beforeEach(async () => {
    await signIn();
    gw.emit("SUBS brgy.#");
  });

  it("shows an incoming report, ACKs it and ignores the retry", async () => {
    deliver("m1", report("r1"));
    deliver("m1", report("r1"));
    const li = await feed().findByText("#r1");
    expect(within(li.closest("li")).getByText("juan")).toBeInTheDocument();
    expect(within(li.closest("li")).getByText("San Roque · Purok 3")).toBeInTheDocument();
    await waitFor(() => expect(gw.sentMatching("ACK")).toEqual(["ACK m1", "ACK m1"]));
    expect(feed().getAllByText("#r1")).toHaveLength(1);
  });

  it("shows anonymous reports without a reporter", async () => {
    deliver("m1", report("r1", { reporter: undefined }));
    expect(within(await feed().findByText("#r1").then((e) => e.closest("li"))).getByText("Anonymous")).toBeInTheDocument();
  });

  it("puts urgent reports first and announces them", async () => {
    deliver("m1", report("r1"));
    deliver("m2", report("r2", { category: "fire", priority: "URGENT", topic: "brgy.san-roque.purok-5.fire", escalated: true }));
    expect(await screen.findByText("Urgent: Fire at San Roque · Purok 5")).toBeInTheDocument();
    const ids = feed().getAllByText(/^#r\d$/).map((e) => e.textContent);
    expect(ids).toEqual(["#r2", "#r1"]);
    expect(stat("Urgent")).toBe("1");
    expect(stat("Open")).toBe("2");
  });

  it("sends RESPONDING with a note and updates the card on UPDATED", async () => {
    deliver("m1", report("r1"));
    await feed().findByText("#r1");
    await user.type(screen.getByLabelText("Note for report r1"), "on the way");
    await user.click(within(card("r1")).getByRole("button", { name: /respond/i }));
    await waitFor(() => expect(gw.lastSent("STATUS")).toBe("STATUS r1 RESPONDING on the way"));
    expect(within(card("r1")).getByText("Received", { selector: ".badge" })).toBeInTheDocument(); // not yet confirmed
    gw.emit("UPDATED r1 RESPONDING");
    expect(await screen.findByText("Marked as responding. The resident has been notified.")).toBeInTheDocument();
    expect(within(card("r1")).getByText("Responding", { selector: ".badge" })).toBeInTheDocument();
    expect(within(card("r1")).getByText("on the way")).toBeInTheDocument();
    expect(within(card("r1")).queryByRole("button", { name: /respond/i })).toBeNull();
    expect(stat("Responding")).toBe("1");
  });

  it("resolves with a default note and keeps the card in Open until dismissed", async () => {
    deliver("m1", report("r1"));
    await feed().findByText("#r1");
    await user.click(within(card("r1")).getByRole("button", { name: /resolve/i }));
    await waitFor(() => expect(gw.lastSent("STATUS")).toBe("STATUS r1 RESOLVED Resolved"));
    gw.emit("UPDATED r1 RESOLVED");
    expect(await screen.findByText("Report resolved.")).toBeInTheDocument();
    expect(card("r1")).toHaveClass("is-resolved");
    expect(stat("Resolved")).toBe("1");
    expect(stat("Open")).toBe("0");

    // Hide it from this desk; it stays counted and reachable from the Resolved tab.
    await user.click(screen.getByRole("button", { name: "Hide report r1" }));
    await user.click(within(screen.getByRole("dialog", { name: "Hide this report?" })).getByRole("button", { name: /hide report/i }));
    expect(feed().queryByText("#r1")).toBeNull();
    expect(stat("Resolved")).toBe("1");
    await user.click(within(screen.getByRole("group", { name: "Filter reports" })).getByRole("button", { name: /^Resolved/ }));
    await user.click(screen.getByRole("button", { name: "Show 1 hidden report" }));
    await user.click(screen.getByRole("button", { name: "Unhide report r1" }));
    expect(feed().getByText("#r1")).toBeInTheDocument();
  });

  it("filters by Urgent, Open, Escalated and Resolved", async () => {
    deliver("m1", report("r1"));
    deliver("m2", report("r2", { category: "fire", priority: "URGENT" }));
    deliver("m3", report("r3", { escalated: true }));
    deliver("m4", report("r4", { status: "RESOLVED" }));
    await feed().findByText("#r3"); // r4 arrived resolved, so the default Open tab leaves it out
    expect(feed().queryByText("#r4")).toBeNull();
    const shown = () => feed().queryAllByText(/^#r\d$/).map((e) => e.textContent).sort();
    const filters = within(screen.getByRole("group", { name: "Filter reports" }));
    const tab = (name) => user.click(filters.getByRole("button", { name: new RegExp(`^${name}`) }));
    await tab("Urgent"); expect(shown()).toEqual(["#r2"]);
    await tab("Escalated"); expect(shown()).toEqual(["#r3"]);
    await tab("Resolved"); expect(shown()).toEqual(["#r4"]);
    await tab("Open"); expect(shown()).toEqual(["#r1", "#r2", "#r3"]);
    await tab("All"); expect(shown()).toEqual(["#r1", "#r2", "#r3", "#r4"]);
  });

  it("an escalated report can't be resolved by a responder", async () => {
    deliver("m1", report("r1", { escalated: true }));
    await feed().findByText("#r1");
    expect(within(card("r1")).getByRole("button", { name: /respond/i })).toBeInTheDocument();
    expect(within(card("r1")).queryByRole("button", { name: /resolve/i })).toBeNull();
    deliver("m2", report("r1", { escalated: true, status: "RESPONDING" }));
    expect(await within(card("r1")).findByText(/Only the city desk can resolve it/)).toBeInTheDocument();
  });

  it("announces a later escalation and a withdrawal", async () => {
    deliver("m1", report("r1"));
    await feed().findByText("#r1");
    deliver("m2", report("r1", { escalated: true, note: "No response within 2 minutes" }));
    expect(await screen.findByText("Escalated to the city: Noise at San Roque · Purok 3")).toBeInTheDocument();
    deliver("m3", report("r1", { status: "WITHDRAWN", escalated: true }));
    expect(await screen.findByText("Withdrawn by the resident: Noise at San Roque · Purok 3")).toBeInTheDocument();
    expect(within(card("r1")).getByText("Withdrawn", { selector: ".badge" })).toBeInTheDocument();
  });

  it("a stale STATUS refusal updates the card to the real status", async () => {
    deliver("m1", report("r1"));
    await feed().findByText("#r1");
    await user.click(within(card("r1")).getByRole("button", { name: /respond/i }));
    gw.emit("ERR report r1 is already RESOLVED");
    expect(await screen.findByText("Broker error: report r1 is already RESOLVED")).toBeInTheDocument();
    expect(within(card("r1")).getByText("Resolved", { selector: ".badge" })).toBeInTheDocument();
  });

  it("restores reports from HISTORY without a toast", async () => {
    gw.emit(hist("brgy.tacas.purok-1.flood", "URGENT", report("h1", { topic: "brgy.tacas.purok-1.flood", category: "flood", priority: undefined, created_at: 1700000000 })));
    gw.emit("HISTEND 1");
    expect(await feed().findByText("#h1")).toBeInTheDocument();
    expect(within(card("h1")).getByText("Urgent", { selector: ".badge" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(gw.sentMatching("ACK")).toEqual([]);
  });
});

describe("The city desk", () => {
  it("can resolve an escalated report", async () => {
    await signIn("city", "desk");
    gw.emit("SUBS city.iloilo.escalated.#");
    deliver("m1", report("r1", { escalated: true }), "city.iloilo.escalated.san-roque");
    expect(await screen.findByText("Escalated to the city: Noise at San Roque · Purok 3")).toBeInTheDocument();
    await user.click(within(card("r1")).getByRole("button", { name: /resolve/i }));
    await waitFor(() => expect(gw.lastSent("STATUS")).toBe("STATUS r1 RESOLVED Resolved"));
  });
});

describe("Advisories", () => {
  const advisoryForm = () => within(screen.getByRole("region", { name: "Post an advisory" }));

  it("validates, posts and lists an advisory", async () => {
    await signIn("captain");
    await user.click(advisoryForm().getByRole("button", { name: /send advisory/i }));
    expect(advisoryForm().getByText("Pick the barangay this is for.")).toBeInTheDocument();
    expect(advisoryForm().getByText("Write the announcement.")).toBeInTheDocument();

    await user.type(advisoryForm().getByRole("combobox"), "Molo");
    await user.click(advisoryForm().getByRole("button", { name: /send advisory/i }));
    expect(advisoryForm().getByText("Not a barangay of Jaro. Pick one from the list.")).toBeInTheDocument();

    await user.clear(advisoryForm().getByRole("combobox"));
    await user.type(advisoryForm().getByRole("combobox"), "M.H. del Pilar");
    await user.type(advisoryForm().getByPlaceholderText(/Water interruption/), "Clean-up drive Saturday");
    await user.click(advisoryForm().getByRole("checkbox", { name: /urgent/i }));
    await user.click(advisoryForm().getByRole("button", { name: /send advisory/i }));
    await waitFor(() => expect(gw.lastSent("ADVISORY")).toBe("ADVISORY mh-del-pilar URGENT Clean-up drive Saturday"));

    gw.emit("POSTED adv1");
    expect(await screen.findByText("Advisory sent to M.H. del Pilar.")).toBeInTheDocument();
    const recent = within(screen.getByRole("list", { name: "Recent advisories" }));
    expect(recent.getByText("Clean-up drive Saturday")).toBeInTheDocument();
    expect(advisoryForm().getByPlaceholderText(/Water interruption/)).toHaveValue("");

    // Our own advisory echoed back on a subscribed topic is not listed twice.
    gw.emit(msg("m9", "brgy.mh-del-pilar.advisory", "URGENT", {
      advisory_id: "adv1", barangay: "mh-del-pilar", description: "Clean-up drive Saturday", from: "captain", from_role: "responder", priority: "URGENT",
    }));
    await waitFor(() => expect(gw.sent).toContain("ACK m9"));
    expect(recent.getAllByText("Clean-up drive Saturday")).toHaveLength(1);
  });

  it("announces advisories posted by others", async () => {
    await signIn("tanod-b");
    gw.emit(msg("m1", "brgy.san-roque.advisory", "NORMAL", {
      advisory_id: "adv2", barangay: "san-roque", description: "Water interruption", from: "captain", from_role: "responder", priority: "NORMAL",
    }));
    expect(await screen.findByText("Advisory for San Roque: Water interruption")).toBeInTheDocument();
  });
});
