import { describe, expect, it } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import App from "./App.jsx";
import { ToastProvider } from "./components/Toast.jsx";
import { barangayName, setBarangays } from "./lib/format.js";
import { installFakeGateway } from "./test/fakeGateway.js";

function renderApp() {
  return render(<ToastProvider><App /></ToastProvider>);
}

function go(hash) {
  act(() => {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

describe("App routing", () => {
  it("shows Home by default and loads barangay names", async () => {
    setBarangays([]);
    installFakeGateway();
    renderApp();
    expect(screen.getAllByRole("link", { name: /report an incident/i }).length).toBeGreaterThan(0);
    expect(document.title).toBe("eSumbong");
    await waitFor(() => expect(barangayName("mh-del-pilar")).toBe("M.H. del Pilar"));
  });

  it("switches pages on hash change and sets the title", async () => {
    installFakeGateway();
    renderApp();
    go("#/resident");
    expect(await screen.findByRole("heading", { name: "Report an incident" })).toBeInTheDocument();
    expect(document.title).toBe("eSumbong · Resident");
    go("#/responder");
    expect(await screen.findByRole("heading", { name: "Responder desk" })).toBeInTheDocument();
    expect(document.title).toBe("eSumbong · Responder");
    go("#/nowhere");
    expect(document.title).toBe("eSumbong");
  });

  it("still renders when the gateway config can't load", () => {
    installFakeGateway();
    globalThis.fetch.mockImplementation(async () => { throw new Error("offline"); });
    renderApp();
    expect(screen.getAllByRole("link", { name: /report an incident/i }).length).toBeGreaterThan(0);
  });
});
