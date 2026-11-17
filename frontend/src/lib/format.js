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

export function titleCase(text) {
  return String(text || "").replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Display label and icon for a config.CATEGORIES name.
export function categoryMeta(name) {
  return CATEGORIES[name] || { label: titleCase(name) || "Report", icon: AlertTriangle };
}

// "brgy.jaro.purok-3.fire" -> "Jaro · Purok 3"
export function placeFromTopic(topic) {
  const parts = String(topic || "").split(".");
  if (parts[0] === "brgy" && parts.length >= 3) return `${titleCase(parts[1])} · ${titleCase(parts[2])}`;
  return topic || "";
}

export function clockTime(ms) {
  return new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
