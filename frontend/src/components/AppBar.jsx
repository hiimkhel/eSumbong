import { Home, LogOut, Megaphone, ShieldCheck } from "lucide-react";
import { LogoMark, Wordmark } from "./ui.jsx";

const NAV = [
  { id: "home", href: "#/", label: "Home", short: "Home", icon: Home },
  { id: "resident", href: "#/resident", label: "Report", short: "Report", icon: Megaphone },
  { id: "responder", href: "#/responder", label: "Responder desk", short: "Desk", icon: ShieldCheck },
];

// active: "home" | "resident" | "responder". conn: the useConnection() result.
// Desktop shows links in the top bar; phones get a bottom tab bar instead.
export default function AppBar({ active = "home", conn, identity }) {
  return (
    <>
      <header className="appbar">
        <div className="container appbar-inner">
          <a href="#/" className="brand" aria-label="eSumbong home">
            <LogoMark size={32} variant="light" />
            <Wordmark />
          </a>
          <nav className="appnav" aria-label="Main">
            {NAV.slice(1).map(({ id, href, label, icon: Icon }) => (
              <a key={id} href={href} className={active === id ? "active" : ""} aria-current={active === id ? "page" : undefined}>
                <Icon size={16} /> {label}
              </a>
            ))}
          </nav>
          {conn && (
            <div className="appbar-end">
              <span className={`live ${conn.status}`} title={conn.reason || undefined}
                aria-label={conn.online ? `Connected as ${identity}` : "Offline"}>
                <span className="live-text">{conn.online ? `Live · ${identity}` : "Offline"}</span>
              </span>
              {conn.online && (
                <button type="button" className="btn btn-on-dark btn-sm" onClick={conn.disconnect} aria-label="Sign out">
                  <LogOut size={15} />
                </button>
              )}
            </div>
          )}
        </div>
      </header>

      <nav className="tabbar" aria-label="Main">
        {NAV.map(({ id, href, short, icon: Icon }) => (
          <a key={id} href={href} className={active === id ? "active" : ""} aria-current={active === id ? "page" : undefined}>
            <Icon size={22} strokeWidth={active === id ? 2.4 : 2} />
            <span>{short}</span>
          </a>
        ))}
      </nav>
    </>
  );
}
