import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ToastProvider } from "../components/Toast.jsx";
import { setBarangays } from "../lib/format.js";
import { CONFIG, hist, installFakeGateway, msg } from "../test/fakeGateway.js";
import Resident from "./Resident.jsx";

let gw;
let user;

beforeEach(() => {
  gw = installFakeGateway();
  user = userEvent.setup({ delay: null });
  setBarangays(CONFIG.barangays);
});

function renderPage() {
  return render(<ToastProvider><Resident /></ToastProvider>);
}

async function signIn(id = "juan") {
  renderPage();
  await user.type(screen.getByRole("textbox"), id);
  await user.click(screen.getByRole("button", { name: /continue/i }));
  await screen.findByRole("heading", { name: "May sumbong ka?" });
  await screen.findByRole("radio", { name: /noise/i }); // config loaded
  await waitFor(() => expect(gw.sent).toEqual(["SUBS", "HISTORY"]));
}

async function fillReport({ barangay = "San Roque", purok = "Purok 3", category, text = "Loud karaoke past midnight", anon = false } = {}) {
  if (barangay) await user.type(screen.getByRole("combobox"), barangay);
  if (purok) await user.type(screen.getByPlaceholderText(/Purok 3 or near/), purok);
  if (category) await user.click(screen.getByRole("radio", { name: new RegExp(category, "i") }));
  if (text) await user.type(screen.getByPlaceholderText(/Describe what's happening/), text);
  if (anon) await user.click(screen.getByRole("checkbox", { name: /anonymously/i }));
}

async function sendReport(opts) {
  await fillReport(opts);
  await user.click(screen.getByRole("button", { name: /send report/i }));
  await waitFor(() => expect(gw.lastSent("REPORT")).toBeTruthy());
  return gw.lastSent("REPORT");
}

const reportsCard = () => screen.getByRole("region", { name: "Your reports" });

describe("Resident sign-in", () => {
  it("signs in as a resident, then asks for subscriptions and history", async () => {
    await signIn("juan");
    expect(gw.connects).toEqual([{ client_id: "juan", role: "resident" }]);
    expect(screen.getByLabelText("Connected as juan")).toBeInTheDocument();
  });

  it("shows the gateway error if the broker is down", async () => {
    gw = installFakeGateway({ connectError: "cannot reach broker at 127.0.0.1:5050" });
    renderPage();
    await user.type(screen.getByRole("textbox"), "juan");
    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByText(/cannot reach broker/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Report an incident" })).toBeInTheDocument();
  });

  it("signs the tab back in after a reload", async () => {
    sessionStorage.setItem("esumbong.signin.resident", JSON.stringify({ id: "maria", role: "resident" }));
    renderPage();
    await screen.findByRole("heading", { name: "May sumbong ka?" });
    expect(gw.connects).toEqual([{ client_id: "maria", role: "resident" }]);
  });

  it("returns to the sign-in screen with a reason when the connection drops", async () => {
    await signIn();
    gw.closeFromBroker();
    expect(await screen.findByText(/Broker closed the connection. Sign in again/)).toBeInTheDocument();
  });

  it("signs out", async () => {
    await signIn();
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Report an incident" })).toBeInTheDocument();
    expect(gw.disconnects).toEqual(["s1"]);
  });
});

describe("Filing a report", () => {
  it("validates every field before sending", async () => {
    await signIn();
    await user.click(screen.getByRole("button", { name: /send report/i }));
    expect(screen.getByText("Pick your barangay in Jaro.")).toBeInTheDocument();
    expect(screen.getByText("Add your purok or a nearby landmark.")).toBeInTheDocument();
    expect(screen.getByText("Tell your barangay what's happening.")).toBeInTheDocument();
    expect(gw.lastSent("REPORT")).toBeUndefined();
  });

  it("rejects a barangay outside Jaro and a purok with no letters or digits", async () => {
    await signIn();
    await fillReport({ barangay: "Molo", purok: "!!!" });
    expect(screen.getByText(/Not a barangay of Jaro/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /send report/i }));
    expect(screen.getByText("Use letters or numbers, e.g. Purok 3.")).toBeInTheDocument();
    expect(gw.lastSent("REPORT")).toBeUndefined();
  });

  it("publishes on brgy.<barangay>.<purok>.<category> and tracks the report", async () => {
    await signIn();
    await fillReport();
    expect(screen.getByText("brgy.san-roque.purok-3.noise")).toBeInTheDocument(); // topic preview
    await user.click(screen.getByRole("button", { name: /send report/i }));
    await waitFor(() => expect(gw.lastSent("REPORT")).toBe("REPORT brgy.san-roque.purok-3.noise N Loud karaoke past midnight"));
    expect(screen.getByPlaceholderText(/Describe what's happening/)).toHaveValue(""); // cleared

    gw.emit("REPORTED r1");
    expect(await screen.findByText("Report sent. Your barangay has been notified.")).toBeInTheDocument();
    const card = within(reportsCard());
    expect(card.getByText("#r1")).toBeInTheDocument();
    expect(card.getByText("San Roque · Purok 3")).toBeInTheDocument();
    expect(card.getByRole("list", { name: "Status: Received" })).toBeInTheDocument();
  });

  it("sends anonymous reports with Y and shows them as anonymous", async () => {
    await signIn();
    expect(await sendReport({ anon: true })).toMatch(/^REPORT brgy\.san-roque\.purok-3\.noise Y /);
    gw.emit("REPORTED r1");
    expect(await within(reportsCard()).findByText("Anonymous")).toBeInTheDocument();
  });

  it("flags urgent categories and marks them escalated once filed", async () => {
    await signIn();
    await user.click(screen.getByRole("radio", { name: /fire/i }));
    expect(screen.getByText(/reports are marked urgent/)).toBeInTheDocument();
    expect(await sendReport({ text: "Smoke near the chapel" })).toBe("REPORT brgy.san-roque.purok-3.fire N Smoke near the chapel");
    gw.emit("REPORTED r2");
    expect(await screen.findByText("Report sent to your barangay and the city desk.")).toBeInTheDocument();
    expect(within(reportsCard()).getByText("Escalated to city")).toBeInTheDocument();
  });

  it("collapses multi-line descriptions into one line", async () => {
    await signIn();
    expect(await sendReport({ text: "line one{enter}line   two" })).toMatch(/ line one line two$/);
  });

  it("drops the pending report when the broker refuses it", async () => {
    await signIn();
    await sendReport();
    gw.emit("ERR unknown barangay");
    expect(await screen.findByText("Couldn't complete that: unknown barangay")).toBeInTheDocument();
    gw.emit("REPORTED stray"); // nothing was pending any more
    expect(within(reportsCard()).queryByText("#stray")).toBeNull();
  });
});

describe("Following a report", () => {
  async function filed() {
    await signIn();
    await sendReport();
    gw.emit("REPORTED r1");
    await within(reportsCard()).findByText("#r1");
  }

  it("updates status and note from report.<id>.status messages", async () => {
    await filed();
    gw.emit(msg("m1", "report.r1.status", "NORMAL", { report_id: "r1", category: "noise", status: "RESPONDING", note: "on the way", escalated: false }));
    expect(await screen.findByText("Noise report is now Responding")).toBeInTheDocument();
    expect(within(reportsCard()).getByRole("list", { name: "Status: Responding" })).toBeInTheDocument();
    expect(within(reportsCard()).getByText("on the way")).toBeInTheDocument();
    await waitFor(() => expect(gw.sent).toContain("ACK m1"));
    // Responding reports can no longer be withdrawn.
    expect(screen.queryByRole("button", { name: /withdraw report/i })).toBeNull();
  });

  it("announces an escalation to the city", async () => {
    await filed();
    gw.emit(msg("m2", "report.r1.status", "NORMAL", { report_id: "r1", category: "noise", status: "RECEIVED", escalated: true, note: "No response within 2 minutes" }));
    expect(await screen.findByText("Your noise report was escalated to the city desk.")).toBeInTheDocument();
    expect(within(reportsCard()).getByText("Escalated to city")).toBeInTheDocument();
  });

  it("withdraws a report after confirming", async () => {
    await filed();
    await user.click(screen.getByRole("button", { name: /withdraw report/i }));
    const dialog = screen.getByRole("dialog", { name: "Withdraw this report?" });
    await user.click(within(dialog).getByRole("button", { name: /withdraw report/i }));
    await waitFor(() => expect(gw.lastSent("WITHDRAW")).toBe("WITHDRAW r1"));
    gw.emit("UPDATED r1 WITHDRAWN");
    expect(await screen.findByText("Report withdrawn. Your barangay has been told.")).toBeInTheDocument();
    expect(within(reportsCard()).getByText(/Withdrawn by the resident/)).toBeInTheDocument();
  });

  it("cancelling the withdraw dialog sends nothing", async () => {
    await filed();
    await user.click(screen.getByRole("button", { name: /withdraw report/i }));
    await user.click(within(screen.getByRole("dialog", { name: "Withdraw this report?" })).getByRole("button", { name: "Cancel" }));
    expect(gw.lastSent("WITHDRAW")).toBeUndefined();
  });

  it("hides a resolved report on this device and can unhide it", async () => {
    await filed();
    gw.emit(msg("m3", "report.r1.status", "NORMAL", { report_id: "r1", category: "noise", status: "RESOLVED", escalated: false }));
    await user.click(await screen.findByRole("button", { name: "Hide report r1" }));
    await user.click(within(screen.getByRole("dialog", { name: "Hide this report?" })).getByRole("button", { name: /hide report/i }));
    expect(screen.getByText("All your reports are hidden")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show 1 hidden report" }));
    await user.click(screen.getByRole("button", { name: "Unhide report r1" }));
    expect(screen.queryByText("All your reports are hidden")).toBeNull();
    expect(screen.getByRole("button", { name: "Hide report r1" })).toBeInTheDocument();
  });

  it("restores earlier reports from HISTORY", async () => {
    await signIn();
    gw.emit(hist("brgy.tacas.purok-1.flood", "URGENT", {
      report_id: "old1", topic: "brgy.tacas.purok-1.flood", category: "flood", description: "Knee-deep water",
      status: "RESPONDING", escalated: true, anonymous: true, created_at: 1700000000,
    }));
    gw.emit("HISTEND 1");
    const card = within(reportsCard());
    expect(await card.findByText("Knee-deep water")).toBeInTheDocument();
    expect(card.getByText("Tacas · Purok 1")).toBeInTheDocument();
    expect(card.getByRole("list", { name: "Status: Responding" })).toBeInTheDocument();
    expect(card.getByText("Anonymous")).toBeInTheDocument();
    expect(gw.sentMatching("ACK")).toEqual([]); // HIST is not ACKed
  });
});

describe("Advisories", () => {
  it("follows the barangay typed in the form and lists its advisories", async () => {
    await signIn();
    const region = () => screen.getByRole("region", { name: "Barangay advisories" });
    expect(within(region()).getByRole("button", { name: /follow/i })).toBeDisabled();
    await user.type(screen.getByRole("combobox"), "San Roque");
    await user.click(within(region()).getByRole("button", { name: "Follow San Roque" }));
    await waitFor(() => expect(gw.lastSent("SUB")).toBe("SUB brgy.san-roque.advisory"));
    expect(within(region()).getByRole("button", { name: /following/i })).toBeDisabled();

    gw.emit(msg("a1", "brgy.san-roque.advisory", "URGENT", {
      advisory_id: "adv1", barangay: "san-roque", description: "Flood warning tonight", from: "captain", from_role: "responder",
    }));
    expect(await within(region()).findByText("Flood warning tonight")).toBeInTheDocument();
    expect(within(region()).getByText(/Barangay San Roque · captain/)).toBeInTheDocument();
  });

  it("switching barangay unsubscribes from the old one", async () => {
    await signIn();
    gw.emit("SUBS brgy.tacas.advisory");
    await screen.findByText("Following Tacas");
    await user.type(screen.getByRole("combobox"), "San Jose");
    await user.click(screen.getByRole("button", { name: "Follow San Jose" }));
    await waitFor(() => expect(gw.sent.slice(-2)).toEqual(["UNSUB brgy.tacas.advisory", "SUB brgy.san-jose.advisory"]));
  });
});
