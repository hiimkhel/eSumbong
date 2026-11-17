import { LogOut, Megaphone, ShieldCheck } from "lucide-react";
import { LogoMark, Wordmark } from "./ui.jsx";

// active: "resident" | "responder" | undefined. conn: the useConnection() result.
export default function AppBar({ active, conn, identity }) {
  return (
    <header className="appbar">
      <div className="container appbar-inner">
        <a href="#/" className="brand" aria-label="eSumbong home">
          <LogoMark size={32} variant="light" />
          <Wordmark />
        </a>
        <nav className="appnav" aria-label="Main">
          <a href="#/resident" className={active === "resident" ? "active" : ""} aria-current={active === "resident" ? "page" : undefined}>
            <Megaphone size={16} /> <span>Report</span>
          </a>
          <a href="#/responder" className={active === "responder" ? "active" : ""} aria-current={active === "responder" ? "page" : undefined}>
            <ShieldCheck size={16} /> <span>Responder desk</span>
          </a>
        </nav>
        {conn && (
          <div className="appbar-end">
            <span className={`live ${conn.status}`} title={conn.reason || undefined}>
              <span className="live-text">{conn.online ? `Live · ${identity}` : "Offline"}</span>
            </span>
            {conn.online && (
              <button type="button" className="btn btn-on-dark btn-sm" onClick={conn.disconnect}>
                <LogOut size={15} /> <span className="sr-only">Sign out</span>
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
