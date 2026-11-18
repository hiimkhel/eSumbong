import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { installFakeGateway } from "../test/fakeGateway.js";
import { useConnection } from "./useConnection.js";
import { useDismissed } from "./useDismissed.js";

describe("useConnection", () => {
  it("connects, logs both directions and remembers the sign-in", async () => {
    const gw = installFakeGateway();
    const onEvent = vi.fn();
    const { result } = renderHook(() => useConnection({ page: "resident", onEvent }));
    expect(result.current.online).toBe(false);

    await act(() => result.current.connect("juan", "resident"));
    expect(result.current.online).toBe(true);
    expect(JSON.parse(sessionStorage.getItem("esumbong.signin.resident"))).toEqual({ id: "juan", role: "resident" });
    expect(JSON.parse(localStorage.getItem("esumbong.lastId.resident"))).toEqual({ id: "juan", role: "resident" });

    await act(() => result.current.send("SUBS"));
    expect(result.current.lastCommand.current).toBe("SUBS");
    gw.emit("SUBS brgy.san-roque.advisory");
    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ command: "SUBS" }));
    expect(result.current.log.map((e) => `${e.direction} ${e.line}`)).toEqual([
      "→ HELLO juan resident", "→ SUBS", "← SUBS brgy.san-roque.advisory",
    ]);
  });

  it("a sign-in with a PIN is not remembered, and the PIN is never stored or logged", async () => {
    installFakeGateway();
    const { result } = renderHook(() => useConnection({ page: "responder" }));
    await act(() => result.current.connect("tanod-a", "responder", "1234"));
    expect(sessionStorage.getItem("esumbong.signin.responder")).toBeNull();
    expect(JSON.parse(localStorage.getItem("esumbong.lastId.responder"))).toEqual({ id: "tanod-a", role: "responder" });
    expect(result.current.log[0].line).toBe("HELLO tanod-a responder ••••");
    expect(JSON.stringify(result.current.log)).not.toContain("1234");
  });

  it("restores the saved sign-in values on mount", () => {
    installFakeGateway();
    sessionStorage.setItem("esumbong.signin.responder", JSON.stringify({ id: "t1", role: "desk" }));
    localStorage.setItem("esumbong.lastId.responder", JSON.stringify({ id: "t0", role: "responder" }));
    const { result } = renderHook(() => useConnection({ page: "responder" }));
    expect(result.current.saved).toEqual({ id: "t1", role: "desk" });
    expect(result.current.lastId).toEqual({ id: "t0", role: "responder" });
  });

  it("signing out forgets this tab's sign-in but keeps the last ID", async () => {
    const gw = installFakeGateway();
    const { result } = renderHook(() => useConnection({ page: "resident" }));
    await act(() => result.current.connect("juan", "resident"));
    await act(() => result.current.disconnect());
    expect(result.current.online).toBe(false);
    expect(sessionStorage.getItem("esumbong.signin.resident")).toBeNull();
    expect(localStorage.getItem("esumbong.lastId.resident")).not.toBeNull();
    expect(gw.disconnects).toEqual(["s1"]);
  });

  it("reports a lost connection with its reason", async () => {
    const gw = installFakeGateway();
    const onState = vi.fn();
    const { result } = renderHook(() => useConnection({ page: "resident", onState }));
    await act(() => result.current.connect("juan", "resident"));
    gw.error();
    expect(result.current.status).toBe("offline");
    expect(result.current.reason).toBe("Lost connection to the gateway");
    expect(onState).toHaveBeenLastCalledWith("offline", "Lost connection to the gateway");
  });

  it("closes the session on unmount", async () => {
    const gw = installFakeGateway();
    const { result, unmount } = renderHook(() => useConnection({ page: "resident" }));
    await act(() => result.current.connect("juan", "resident"));
    unmount();
    await waitFor(() => expect(gw.disconnects).toEqual(["s1"]));
  });
});

describe("useDismissed", () => {
  it("hides and restores ids per page and client, saved in localStorage", () => {
    const { result, rerender } = renderHook(({ id }) => useDismissed("resident", id), { initialProps: { id: "juan" } });
    act(() => result.current[1]("r1"));
    act(() => result.current[1]("r2"));
    expect([...result.current[0]]).toEqual(["r1", "r2"]);
    expect(JSON.parse(localStorage.getItem("esumbong.dismissed.resident.juan"))).toEqual(["r1", "r2"]);

    act(() => result.current[2]("r1"));
    expect([...result.current[0]]).toEqual(["r2"]);

    rerender({ id: "maria" }); // another person on this browser has their own list
    expect(result.current[0].size).toBe(0);
    rerender({ id: "juan" });
    expect([...result.current[0]]).toEqual(["r2"]);
  });

  it("is empty before anyone signs in", () => {
    const { result } = renderHook(() => useDismissed("responder", ""));
    expect(result.current[0].size).toBe(0);
  });
});
