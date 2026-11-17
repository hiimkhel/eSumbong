import { Check } from "lucide-react";
import { categoryMeta } from "../lib/format.js";

// The Rise logo: amber signal dot over a white and a Signal Sky chevron.
// variant "light" is the white tile used on navy backgrounds, as on the brand board.
export function LogoMark({ size = 32, variant = "dark" }) {
  const light = variant === "light";
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden="true">
      <rect width="100" height="100" rx="24" fill={light ? "#fff" : "#0B1B3F"} />
      <circle cx="50" cy="23" r="7" fill="#F2B33D" />
      <polyline points="27,54 50,35 73,54" fill="none" stroke={light ? "#0B1B3F" : "#fff"} strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="27,73 50,54 73,73" fill="none" stroke={light ? "#1F4FB3" : "#5B8DEF"} strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Wordmark() {
  return <span className="wordmark"><span className="e">e</span>Sumbong</span>;
}

export function CategoryTile({ category, urgent, size = 20 }) {
  const { icon: Icon } = categoryMeta(category);
  return (
    <span className={`tile${urgent ? " is-urgent" : ""}`}>
      <Icon size={size} strokeWidth={2} />
    </span>
  );
}

const STATUS_LABEL = { RECEIVED: "Received", RESPONDING: "Responding", RESOLVED: "Resolved" };

export function StatusBadge({ status = "RECEIVED" }) {
  return <span className={`badge badge-${status.toLowerCase()}`}>{STATUS_LABEL[status] || status}</span>;
}

const STEPS = ["RECEIVED", "RESPONDING", "RESOLVED"];

// Received -> Responding -> Resolved, with the current step highlighted.
export function StatusStepper({ status = "RECEIVED" }) {
  const index = Math.max(0, STEPS.indexOf(status));
  const finished = status === "RESOLVED";
  return (
    <ol className="stepper" aria-label={`Status: ${STATUS_LABEL[status] || status}`}>
      {STEPS.map((step, i) => {
        const done = i < index || finished;
        const state = done ? "done" : i === index ? "current" : "";
        return (
          <li key={step} className={state} aria-current={i === index ? "step" : undefined}>
            <span className="dot">{done && <Check size={12} strokeWidth={3} />}</span>
            {STATUS_LABEL[step]}
          </li>
        );
      })}
    </ol>
  );
}

export function EmptyState({ icon: Icon, title, children }) {
  return (
    <div className="empty">
      <span className="empty-icon"><Icon size={24} /></span>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  );
}
