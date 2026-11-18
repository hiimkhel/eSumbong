import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { ShieldCheck, Building2 } from "lucide-react";
import AppBar from "./AppBar.jsx";
import Combobox from "./Combobox.jsx";
import ConfirmDialog from "./ConfirmDialog.jsx";
import ProtocolLog from "./ProtocolLog.jsx";
import SignIn from "./SignIn.jsx";
import { ToastProvider, useToast } from "./Toast.jsx";
import { EmptyState, FieldError, HiddenToggle, StatusBadge, StatusStepper } from "./ui.jsx";

describe("StatusStepper", () => {
  it("marks the current step and finished steps", () => {
    render(<StatusStepper status="RESPONDING" />);
    const steps = screen.getAllByRole("listitem");
    expect(steps.map((s) => s.className)).toEqual(["done", "current", ""]);
    expect(steps[1]).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("list")).toHaveAccessibleName("Status: Responding");
  });

  it("marks every step done when resolved", () => {
    render(<StatusStepper status="RESOLVED" />);
    expect(screen.getAllByRole("listitem").map((s) => s.className)).toEqual(["done", "done", "done"]);
  });

  it("defaults to Received and shows a note when withdrawn", () => {
    const { rerender } = render(<StatusStepper />);
    expect(screen.getAllByRole("listitem")[0]).toHaveClass("current");
    rerender(<StatusStepper status="WITHDRAWN" />);
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.getByText(/Withdrawn by the resident/)).toBeInTheDocument();
  });
});

describe("small UI pieces", () => {
  it("StatusBadge labels known statuses and passes others through", () => {
    const { rerender } = render(<StatusBadge status="RESOLVED" />);
    expect(screen.getByText("Resolved")).toHaveClass("badge-resolved");
    rerender(<StatusBadge status="ODD" />);
    expect(screen.getByText("ODD")).toBeInTheDocument();
  });

  it("HiddenToggle renders nothing at zero and pluralizes", async () => {
    const onToggle = vi.fn();
    const { container, rerender } = render(<HiddenToggle count={0} open={false} onToggle={onToggle} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<HiddenToggle count={1} open={false} onToggle={onToggle} />);
    expect(screen.getByRole("button")).toHaveTextContent("Show 1 hidden report");
    rerender(<HiddenToggle count={2} open={false} onToggle={onToggle} />);
    expect(screen.getByRole("button")).toHaveTextContent("Show 2 hidden reports");
    rerender(<HiddenToggle count={2} open onToggle={onToggle} />);
    await userEvent.click(screen.getByRole("button", { expanded: true }));
    expect(onToggle).toHaveBeenCalled();
  });

  it("FieldError is an alert and EmptyState shows its text", () => {
    render(<><FieldError>Bad</FieldError><EmptyState icon={ShieldCheck} title="Nothing">Body</EmptyState></>);
    expect(screen.getByRole("alert")).toHaveTextContent("Bad");
    expect(screen.getByRole("heading", { name: "Nothing" })).toBeInTheDocument();
  });
});

describe("Combobox", () => {
  const options = [
    { value: "san-roque", label: "San Roque" },
    { value: "san-jose", label: "San Jose" },
    { value: "tacas", label: "Tacas" },
    { value: "lopez-jaena", label: "Lopez Jaena" },
  ];

  function Harness({ onPick = () => {} }) {
    const [value, setValue] = useState("");
    return <Combobox value={value} onChange={(v) => { setValue(v); onPick(v); }} options={options} placeholder="Barangay" />;
  }

  it("filters options: starts-with first, then contains", async () => {
    render(<Harness />);
    await userEvent.type(screen.getByRole("combobox"), "san");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["San Roque", "San Jose"]);
    await userEvent.clear(screen.getByRole("combobox"));
    await userEvent.type(screen.getByRole("combobox"), "na");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Lopez Jaena"]);
  });

  it("shows No match when nothing fits", async () => {
    render(<Harness />);
    await userEvent.type(screen.getByRole("combobox"), "zzz");
    expect(screen.getByText("No match")).toBeInTheDocument();
  });

  it("picks with arrow keys and Enter, and closes on Escape", async () => {
    const onPick = vi.fn();
    render(<Harness onPick={onPick} />);
    const input = screen.getByRole("combobox");
    await userEvent.type(input, "san");
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(input).toHaveValue("San Jose");
    expect(screen.queryByRole("listbox")).toBeNull();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("picks with the mouse", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "Tacas" }));
    expect(screen.getByRole("combobox")).toHaveValue("Tacas");
  });

  it("puts an option's text (not its label) in the field when given", async () => {
    const onChange = vi.fn();
    render(<Combobox value="" onChange={onChange} options={[{ value: "a", label: "Arguelles", text: "brgy.arguelles.#", hint: "brgy.arguelles.#" }]} />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option"));
    expect(onChange).toHaveBeenLastCalledWith("brgy.arguelles.#");
  });
});

describe("ConfirmDialog", () => {
  it("opens, confirms and cancels", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const { rerender } = render(
      <ConfirmDialog open={false} title="Hide?" confirmLabel="Hide" onConfirm={onConfirm} onCancel={onCancel}>body</ConfirmDialog>,
    );
    const dialog = document.querySelector("dialog");
    expect(dialog.open).toBe(false);
    rerender(<ConfirmDialog open title="Hide?" confirmLabel="Hide" onConfirm={onConfirm} onCancel={onCancel}>body</ConfirmDialog>);
    expect(dialog.open).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    rerender(<ConfirmDialog open={false} title="Hide?" onConfirm={onConfirm} onCancel={onCancel}>body</ConfirmDialog>);
    expect(dialog.open).toBe(false);
  });

  it("a click on the backdrop cancels", async () => {
    const onCancel = vi.fn();
    render(<ConfirmDialog open title="Hide?" onConfirm={() => {}} onCancel={onCancel}>body</ConfirmDialog>);
    await userEvent.click(document.querySelector("dialog"));
    expect(onCancel).toHaveBeenCalled();
  });
});

describe("Toast", () => {
  function Trigger() {
    const toast = useToast();
    return (
      <>
        <button onClick={() => toast("Saved")}>ok</button>
        <button onClick={() => toast("Failed", true)}>bad</button>
      </>
    );
  }

  it("shows status and error toasts and hides them after 4 seconds", async () => {
    vi.useFakeTimers();
    try {
      render(<ToastProvider><Trigger /></ToastProvider>);
      act(() => screen.getByText("ok").click());
      expect(screen.getByRole("status")).toHaveTextContent("Saved");
      act(() => screen.getByText("bad").click());
      expect(screen.getByRole("alert")).toHaveTextContent("Failed");
      expect(screen.queryByRole("status")).toBeNull(); // replaced, not stacked
      act(() => vi.advanceTimersByTime(4000));
      expect(screen.queryByRole("alert")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("SignIn", () => {
  const roles = [
    { value: "responder", label: "Responder", hint: "Tanod", icon: ShieldCheck },
    { value: "desk", label: "City desk", hint: "Escalations", icon: Building2 },
  ];

  it("validates the ID before connecting", async () => {
    const onConnect = vi.fn();
    render(<SignIn title="Sign in" onConnect={onConnect} />);
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an ID");
    await userEvent.type(screen.getByRole("textbox"), "two words");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByRole("alert")).toHaveTextContent("no spaces");
    expect(onConnect).not.toHaveBeenCalled();
  });

  it("connects with the trimmed ID and chosen role", async () => {
    const onConnect = vi.fn(async () => {});
    render(<SignIn title="Desk" roles={roles} defaultId="  tanod-a " onConnect={onConnect} />);
    await userEvent.click(screen.getByRole("radio", { name: /city desk/i }));
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(onConnect).toHaveBeenCalledWith("tanod-a", "desk");
  });

  it("shows why the last session ended", () => {
    render(<SignIn title="x" reason="Broker closed the connection" onConnect={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Broker closed the connection. Sign in again");
  });
});

describe("AppBar and ProtocolLog", () => {
  it("shows the connection state and signs out", async () => {
    const disconnect = vi.fn();
    const { rerender } = render(<AppBar active="resident" conn={{ online: false, status: "offline", disconnect }} />);
    expect(screen.getByLabelText("Offline")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
    rerender(<AppBar active="resident" conn={{ online: true, status: "online", disconnect }} identity="juan" />);
    expect(screen.getByLabelText("Connected as juan")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(disconnect).toHaveBeenCalled();
    expect(screen.getAllByRole("link", { current: "page" })[0]).toHaveAttribute("href", "#/resident");
  });

  it("ProtocolLog lists sent and received lines", () => {
    const { rerender } = render(<ProtocolLog entries={[]} />);
    expect(screen.getByText("Nothing sent yet.")).toBeInTheDocument();
    rerender(<ProtocolLog entries={[{ time: "1:00", direction: "→", line: "SUBS" }, { time: "1:00", direction: "←", line: "SUBS a.#" }]} />);
    expect(screen.getByText("SUBS a.#", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
