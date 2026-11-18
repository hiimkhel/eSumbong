import { AlertTriangle, Construction, Eye, Flame, PawPrint, Swords, Volume2, Waves, Wine } from "lucide-react";

const CATEGORIES = {
  noise: { label: "Noise", icon: Volume2 },
  drinking: { label: "Public drinking", icon: Wine },
  fight: { label: "Fight", icon: Swords },
  suspicious: { label: "Suspicious activity", icon: Eye },
  animals: { label: "Stray animals", icon: PawPrint },
  fire: { label: "Fire", icon: Flame },
  flood: { label: "Flood", icon: Waves },
  road: { label: "Road hazard", icon: Construction },
};

// Resolved and withdrawn reports are finished: no more actions, may be hidden.
export const isClosed = (status) => status === "RESOLVED" || status === "WITHDRAWN";

export function titleCase(text) {
  return String(text || "").replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Display label and icon for a config.CATEGORIES name.
export function categoryMeta(name) {
  return CATEGORIES[name] || { label: titleCase(name) || "Report", icon: AlertTriangle };
}

// Official barangay names by topic level, from /api/config (config.BARANGAYS).
let barangayNames = {};

export function setBarangays(list) {
  barangayNames = Object.fromEntries((list || []).map((b) => [b.id, b.name]));
}

// [{ id, name }] in config order; empty until /api/config has loaded.
export function barangayList() {
  return Object.entries(barangayNames).map(([id, name]) => ({ id, name }));
}

// "mh-del-pilar" -> "M.H. del Pilar"; falls back to title case.
export function barangayName(id) {
  return barangayNames[id] || titleCase(id);
}

// "brgy.san-roque.purok-3.fire" -> "San Roque · Purok 3"
export function placeFromTopic(topic) {
  const parts = String(topic || "").split(".");
  if (parts[0] === "brgy" && parts.length >= 3) return `${barangayName(parts[1])} · ${titleCase(parts[2])}`;
  return topic || "";
}

// Time of day, with the date too when it isn't today (reports restored by HISTORY).
export function clockTime(ms) {
  const d = new Date(ms);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (d.toDateString() === new Date().toDateString()) return time;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })}, ${time}`;
}
