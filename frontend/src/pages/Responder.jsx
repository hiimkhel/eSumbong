import { useMemo, useRef, useState } from "react";
import Header from "../components/Header.jsx";
import ProtocolLog from "../components/ProtocolLog.jsx";
import StatusPills from "../components/StatusPills.jsx";
import { useToast } from "../components/Toast.jsx";
import { useConnection } from "../hooks/useConnection.js";
import { oneLine } from "../lib/sumbong.js";

const urgentFirst = (r) => (r.priority === "URGENT" ? 0 : 1);

// Responder / desk: subscribe to topics, receive reports, publish STATUS updates.
export default function Responder() {
  const toast = useToast();
  const [clientId, setClientId] = useState("");
  const [role, setRole] = useState("responder");
  const [pattern, setPattern] = useState("");
  const [subs, setSubs] = useState([]);
  const [reports, setReports] = useState(() => new Map()); // report_id -> latest body + extras
  const [urgentOnly, setUrgentOnly] = useState(false);
  const [hideResolved, setHideResolved] = useState(false);
  const seen = useRef(new Set());     // report ids already announced
  const lastSub = useRef(null);       // so an ERR right after SUB can roll it back

  const conn = useConnection({
    onState: (status, reason) => {
      if (status === "online") return;
      setSubs([]);
      if (reason) toast(reason, true);
    },
    onEvent: (event) => {
      if (event.command === "MSG") {
        const body = event.body;
        if (!body || !body.report_id) return;
        const priority = body.priority || event.priority;
        const now = Date.now();
        setReports((prev) => {
          const existing = prev.get(body.report_id);
          return new Map(prev).set(body.report_id, {
            ...existing,
            ...body,
            priority,
            lastTopic: event.topic,
            receivedAt: existing?.receivedAt || now,
          });
        });
        if (!seen.current.has(body.report_id)) {
          seen.current.add(body.report_id);
          if (priority === "URGENT") toast(`URGENT: ${body.category} at ${body.topic}`, true);
        }
      } else if (event.command === "ERR") {
        toast(`Broker error: ${event.reason}`, true);
        if (conn.lastCommand.current === "SUB" && lastSub.current) {
          const failed = lastSub.current;
          lastSub.current = null;
          setSubs((prev) => prev.filter((p) => p !== failed));
        }
      }
    },
  });

  async function onConnect(e) {
    e.preventDefault();
    try {
      await conn.connect(clientId.trim(), role);
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function onSubscribe(e) {
    e.preventDefault();
    const p = pattern.trim().toLowerCase();
    if (!p || /\s/.test(p)) return toast("Pattern must be one word, e.g. brgy.jaro.#", true);
    if (subs.includes(p)) return toast(`Already subscribed to ${p}`);
    // Add first: the broker's ERR can arrive before the send request returns.
    lastSub.current = p;
    setSubs((prev) => [...prev, p]);
    try {
      await conn.send(`SUB ${p}`);
      setPattern("");
    } catch (err) {
      setSubs((prev) => prev.filter((x) => x !== p));
      toast(err.message, true);
    }
  }

  async function onUnsubscribe(p) {
    try {
      await conn.send(`UNSUB ${p}`);
      setSubs((prev) => prev.filter((x) => x !== p));
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function updateStatus(reportId, status, noteText) {
    const note = oneLine(noteText) || (status === "RESPONDING" ? "On the way" : "Resolved");
    try {
      await conn.send(`STATUS ${reportId} ${status} ${note}`);
      setReports((prev) => {
        const r = prev.get(reportId);
        return r ? new Map(prev).set(reportId, { ...r, status, note }) : prev;
      });
    } catch (err) {
      toast(err.message, true);
    }
  }

  const feed = useMemo(() => [...reports.entries()]
    .filter(([, r]) => !urgentOnly || r.priority === "URGENT")
    .filter(([, r]) => !hideResolved || r.status !== "RESOLVED")
    .sort(([, a], [, b]) => urgentFirst(a) - urgentFirst(b) || b.receivedAt - a.receivedAt),
  [reports, urgentOnly, hideResolved]);

  return (
    <>
      <Header section="Responder / Desk" conn={conn} />
      <main>
        <div className="grid">
          <section className="card">
            <h2>Connect</h2>
            <form onSubmit={onConnect}>
              <div className="row">
                <div>
                  <label htmlFor="client-id">Your ID (no spaces)</label>
                  <input id="client-id" required maxLength={64} pattern="\S+" placeholder="e.g. tanod-jaro-1"
                    value={clientId} onChange={(e) => setClientId(e.target.value)} disabled={conn.online} />
                </div>
                <div>
                  <label htmlFor="role">Role</label>
                  <select id="role" value={role} onChange={(e) => setRole(e.target.value)} disabled={conn.online}>
                    <option value="responder">Responder (tanod / captain)</option>
                    <option value="desk">City desk</option>
                  </select>
                </div>
              </div>
              <div className="row actions">
                <button type="submit" disabled={conn.online}>Connect</button>
                <button type="button" className="secondary" disabled={!conn.online} onClick={conn.disconnect}>Disconnect</button>
              </div>
            </form>
          </section>

          <section className="card">
            <h2>Subscriptions</h2>
            <form className="row" onSubmit={onSubscribe}>
              <div>
                <label htmlFor="pattern">Topic pattern</label>
                <input id="pattern" required placeholder="brgy.jaro.#" value={pattern} onChange={(e) => setPattern(e.target.value)} />
              </div>
              <div className="fit">
                <button type="submit" disabled={!conn.online}>Subscribe</button>
              </div>
            </form>
            <p className="meta">* matches one level, # matches the rest. Desk example: city.iloilo.escalated.#</p>
            <ul className="list">
              {subs.map((p) => (
                <li key={p} className="item-head spread">
                  <code>{p}</code>
                  <button type="button" className="small secondary" onClick={() => onUnsubscribe(p)}>Unsubscribe</button>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <section className="card stack">
          <div className="item-head spread">
            <h2 className="flush">Incoming reports</h2>
            <div className="item-head">
              <label className="check">
                <input type="checkbox" checked={urgentOnly} onChange={(e) => setUrgentOnly(e.target.checked)} /> Urgent only
              </label>
              <label className="check">
                <input type="checkbox" checked={hideResolved} onChange={(e) => setHideResolved(e.target.checked)} /> Hide resolved
              </label>
            </div>
          </div>
          {feed.length === 0
            ? <p className="empty">No reports yet. Subscribe to a topic to start receiving them.</p>
            : (
              <ul className="list stack-sm">
                {feed.map(([id, r]) => (
                  <ReportCard key={id} id={id} report={r} online={conn.online} onStatus={updateStatus} />
                ))}
              </ul>
            )}
        </section>

        <div className="stack">
          <ProtocolLog entries={conn.log} />
        </div>
      </main>
    </>
  );
}

function ReportCard({ id, report: r, online, onStatus }) {
  const [note, setNote] = useState("");
  const status = r.status || "RECEIVED";
  const urgent = r.priority === "URGENT";

  return (
    <li className={urgent ? "urgent" : ""}>
      <div className="item-head">
        <strong>{r.category || "report"}</strong>
        <StatusPills status={status} urgent={urgent} escalated={r.escalated} />
      </div>
      <p className="item-body">{r.description}</p>
      <p className="meta">
        #{id} · {r.topic || r.lastTopic} · {r.reporter ? `reported by ${r.reporter}` : "anonymous"} ·{" "}
        {new Date(r.receivedAt).toLocaleTimeString()}
      </p>
      {r.note && <p className="meta">Last note: {r.note}</p>}
      {status !== "RESOLVED" && (
        <div className="row actions">
          <input placeholder="Note (optional)" maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="fit">
            <button type="button" className="small" disabled={!online || status !== "RECEIVED"}
              onClick={() => onStatus(id, "RESPONDING", note)}>Responding</button>
          </div>
          <div className="fit">
            <button type="button" className="small secondary" disabled={!online}
              onClick={() => onStatus(id, "RESOLVED", note)}>Resolved</button>
          </div>
        </div>
      )}
    </li>
  );
}
