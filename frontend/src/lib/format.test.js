import { afterEach, describe, expect, it } from "vitest";
import { AlertTriangle, Flame } from "lucide-react";
import {
  advisorySender, barangayList, barangayName, categoryMeta, clockTime, isClosed, placeFromTopic, setBarangays, titleCase,
} from "./format.js";
import { CONFIG } from "../test/fakeGateway.js";

afterEach(() => setBarangays([]));

describe("format helpers", () => {
  it("isClosed is true only for RESOLVED and WITHDRAWN", () => {
    expect(isClosed("RESOLVED")).toBe(true);
    expect(isClosed("WITHDRAWN")).toBe(true);
    expect(isClosed("RECEIVED")).toBe(false);
    expect(isClosed("RESPONDING")).toBe(false);
    expect(isClosed(undefined)).toBe(false);
  });

  it("titleCase handles hyphens, underscores and empty input", () => {
    expect(titleCase("purok-3")).toBe("Purok 3");
    expect(titleCase("near_jaro-plaza")).toBe("Near Jaro Plaza");
    expect(titleCase(null)).toBe("");
  });

  it("categoryMeta knows every config category and falls back for others", () => {
    for (const c of CONFIG.categories) expect(categoryMeta(c).label).toBeTruthy();
    expect(categoryMeta("fire")).toEqual({ label: "Fire", icon: Flame });
    expect(categoryMeta("power-outage")).toEqual({ label: "Power Outage", icon: AlertTriangle });
    expect(categoryMeta("").label).toBe("Report");
  });

  it("uses official barangay names once loaded, title case before", () => {
    expect(barangayName("mh-del-pilar")).toBe("Mh Del Pilar");
    expect(barangayList()).toEqual([]);
    setBarangays(CONFIG.barangays);
    expect(barangayName("mh-del-pilar")).toBe("M.H. del Pilar");
    expect(barangayList()).toEqual(CONFIG.barangays);
    setBarangays(undefined);
    expect(barangayList()).toEqual([]);
  });

  it("placeFromTopic names barangay and purok, passes other topics through", () => {
    setBarangays(CONFIG.barangays);
    expect(placeFromTopic("brgy.mh-del-pilar.purok-3.fire")).toBe("M.H. del Pilar · Purok 3");
    expect(placeFromTopic("city.iloilo.escalated.tacas")).toBe("city.iloilo.escalated.tacas");
    expect(placeFromTopic(undefined)).toBe("");
  });

  it("advisorySender names the office and the sender", () => {
    setBarangays(CONFIG.barangays);
    expect(advisorySender({ from: "tanod-b", from_role: "responder", barangay: "san-roque" })).toBe("Barangay San Roque · tanod-b");
    expect(advisorySender({ from: "city", from_role: "desk", barangay: "tacas" })).toBe("Iloilo City desk · city");
    expect(advisorySender({})).toBe("");
    expect(advisorySender(null)).toBe("");
  });

  it("clockTime shows only the time today and adds the date otherwise", () => {
    const today = clockTime(Date.now());
    const older = clockTime(new Date(2024, 0, 15, 9, 30).getTime());
    expect(today).not.toContain(",");
    expect(older).toContain(",");
    expect(older).toMatch(/Jan/);
  });
});
