export function Brand() {
  return (
    <span className="brand">
      <img src="/logo.svg" alt="" />
      <span><span className="e">e</span>Sumbong</span>
    </span>
  );
}

// section: page name after the wordmark. conn: { status, reason } to show the link state.
export default function Header({ section, conn }) {
  return (
    <header className="top">
      <h1>
        <a href="#/"><Brand /></a>
        {section && <span className="section">· {section}</span>}
      </h1>
      {conn && (
        <span className={`conn ${conn.status}`}>
          {conn.status === "online" ? "Connected" : conn.reason || "Not connected"}
        </span>
      )}
    </header>
  );
}
