import { useMemo, useRef, useState } from "react";
import {
  Building2, CheckCircle2, ChevronDown, Clock, Inbox, MapPin, MessageSquare, Plus, Radio, ShieldCheck, Siren, Truck, User, X,
} from "lucide-react";
import AppBar from "../components/AppBar.jsx";
import ProtocolLog from "../components/ProtocolLog.jsx";
import SignIn from "../components/SignIn.jsx";
import { useToast } from "../components/Toast.jsx";
import { CategoryTile, EmptyState, StatusBadge, StatusStepper } from "../components/ui.jsx";
import { useConnection } from "../hooks/useConnection.js";
import { categoryMeta, clockTime, placeFromTopic } from "../lib/format.js";
import { oneLine } from "../lib/sumbong.js";

const ROLES = [
  { value: "responder", label: "Responder", hint: "Tanod or captain", icon: ShieldCheck },
  { value: "desk", label: "City desk", hint: "Handles escalations", icon: Building2 },
];

const PRESETS = [
  { pattern: "brgy.#", label: "All barangays" },
  { pattern: "city.iloilo.escalated.#", label: "Escalated to the city" },
];

const FILTERS = [
  { id: "all", label: "All", test: () => true },
  { id: "urgent", label: "Urgent", test: (r) => r.priority === "URGENT" && r.status !== "RESOLVED" },
  { id: "open", label: "Open", test: (r) => r.status !== "RESOLVED" },
  { id: "resolved", label: "Resolved", test: (r) => r.status === "RESOLVED" },
];

const urgentFirst = (r) => (r.priority === "URGENT" ? 0 : 1);
const openFirst = (r) => (r.status === "RESOLVED" ? 1 : 0);

// Responder / desk: subscribe to topics, receive reports, publish STATUS updates.
export default function Responder() {
  const toast = useToast();
  const [identity, setIdentity] = useState({ id: "", role: "responder" });
  const [pattern, setPattern] = useState("");
  const [subs, setSubs] = useState([]);
  const [reports, setReports] = useState(() => new Map()); // report_id -> latest body + extras
  const [filter, setFilter] = useState("all");
  const [coverageOpen, setCoverageOpen] = useState(true);  // collapsible on phones only
  const seen = useRef(new Set());     // report ids already announced
  const lastSub = useRef(null);       // so an ERR right after SUB can roll it back

  const conn = useConnection({
    onState: (status) => {
      if (status !== "online") setSubs([]);
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
          if (priority === "URGENT") toast(`Urgent: ${categoryMeta(body.category).label} at ${placeFromTopic(body.topic)}`, true);
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

  const counts = useMemo(() => {
    const all = [...reports.values()];
    return Object.fromEntries(FILTERS.map((f) => [f.id, all.filter(f.test).length]));
  }, [reports]);

  const feed = useMemo(() => {
    const { test } = FILTERS.find((f) => f.id === filter);
    return [...reports.entries()]
      .filter(([, r]) => test(r))
      .sort(([, a], [, b]) => openFirst(a) - openFirst(b) || urgentFirst(a) - urgentFirst(b) || b.receivedAt - a.receivedAt);
  }, [reports, filter]);

  async function connect(id, role) {
    try {
      await conn.connect(id, role);
      setIdentity({ id, role });
    } catch (err) {
      toast(err.message, true);
    }
  }

  if (!conn.online) {
    return (
      <>
        <AppBar active="responder" conn={conn} />
        <SignIn
          title="Responder desk"
          lead="Sign in to receive reports from the barangays you cover and update their status."
          foot="Residents see each status update you send."
          placeholder="e.g. tanod-jaro-1"
          roles={ROLES}
          defaultRole={identity.role}
          reason={conn.reason}
          onConnect={connect}
        />
      </>
    );
  }

  async function subscribe(raw) {
    const p = raw.trim().toLowerCase();
    if (!p || /\s/.test(p)) return toast("A topic pattern is one word, e.g. brgy.jaro.#", true);
    if (subs.includes(p)) return toast(`Already subscribed to ${p}`);
    // Add first: the broker's ERR can arrive before the send request returns.
    lastSub.current = p;
    setSubs((prev) => [...prev, p]);
    try {
      await conn.send(`SUB ${p}`);
      setPattern("");
      setCoverageOpen(false); // on phones, get the coverage panel out of the way of the feed
    } catch (err) {
      setSubs((prev) => prev.filter((x) => x !== p));
      toast(err.message, true);
    }
  }

  async function unsubscribe(p) {
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
      toast(status === "RESPONDING" ? "Marked as responding. The resident has been notified." : "Report resolved.");
    } catch (err) {
      toast(err.message, true);
    }
  }

  const role = ROLES.find((r) => r.value === identity.role) || ROLES[0];
  const responding = [...reports.values()].filter((r) => r.status === "RESPONDING").length;

  return (
    <>
      <AppBar active="responder" conn={conn} identity={identity.id} />
      <main className="page">
        <div className="container">
          <div className="page-head">
            <div>
              <span className="eyebrow">{role.value === "desk" ? "City desk" : "Responder desk"}</span>
              <h1>Incoming reports</h1>
              <p>Urgent and open reports stay at the top until they're resolved.</p>
            </div>
          </div>

          <div className="desk">
            <aside className="desk-aside">
              <section className="card card-pad">
                <div className="identity">
                  <span className="avatar">{identity.id.slice(0, 2)}</span>
                  <div>
                    <strong>{identity.id}</strong>
                    <span>{role.label} · {role.hint}</span>
                  </div>
                </div>
              </section>

              <section className={`card card-pad coverage${coverageOpen ? " open" : ""}`} aria-labelledby="subs-title">
                <button type="button" className="card-head collapse-head" aria-expanded={coverageOpen}
                  aria-controls="coverage-body" onClick={() => setCoverageOpen((o) => !o)}>
                  <div>
                    <h2 className="card-title" id="subs-title">Coverage</h2>
                    <p className="card-sub">
                      {subs.length ? `Listening to ${subs.length} topic${subs.length > 1 ? "s" : ""}` : "Choose what you receive"}
                    </p>
                  </div>
                  <Radio size={18} className="muted collapse-icon" />
                  <ChevronDown size={20} className="collapse-chev" />
                </button>
                <div className="collapse-body" id="coverage-body">
                <p className="card-sub coverage-help"><code>*</code> matches one level, <code>#</code> the rest.</p>
                <form className="sub-form" onSubmit={(e) => { e.preventDefault(); subscribe(pattern); }}>
                  <label className="sr-only" htmlFor="pattern">Topic pattern</label>
                  <input id="pattern" className="input" placeholder="brgy.jaro.#" value={pattern} onChange={(e) => setPattern(e.target.value)} />
                  <button type="submit" className="btn btn-primary" aria-label="Subscribe"><Plus size={18} /></button>
                </form>
                {subs.length > 0 ? (
                  <ul className="subs" aria-label="Subscriptions">
                    {subs.map((p) => (
                      <li key={p} className="sub-chip">
                        {p}
                        <button type="button" className="icon-btn" aria-label={`Unsubscribe from ${p}`} onClick={() => unsubscribe(p)}>
                          <X size={14} />
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="card-sub coverage-help">Not subscribed to anything yet.</p>
                )}
                <div className="presets">
                  {PRESETS.map(({ pattern: p, label }) => (
                    <button key={p} type="button" className="preset" disabled={subs.includes(p)} onClick={() => subscribe(p)}>
                      <span>{label}</span>
                      <code>{p}</code>
                    </button>
                  ))}
                </div>
                </div>
              </section>
            </aside>

            <section aria-label="Report feed">
              <div className="stats">
                <div className="stat urgent">
                  <span className="stat-label"><Siren size={15} /> Urgent</span>
                  <div className="stat-value">{counts.urgent}</div>
                </div>
                <div className="stat">
                  <span className="stat-label"><Inbox size={15} /> Open</span>
                  <div className="stat-value">{counts.open}</div>
                </div>
                <div className="stat">
                  <span className="stat-label"><Truck size={15} /> Responding</span>
                  <div className="stat-value">{responding}</div>
                </div>
                <div className="stat">
                  <span className="stat-label"><CheckCircle2 size={15} /> Resolved</span>
                  <div className="stat-value">{counts.resolved}</div>
                </div>
              </div>

              <div className="toolbar">
                <div className="segmented" role="group" aria-label="Filter reports">
                  {FILTERS.map((f) => (
                    <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
                      {f.label} <span className="count">{counts[f.id]}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="card card-pad feed-card">
                {feed.length === 0 ? (
                  reports.size === 0 ? (
                    <EmptyState icon={Radio} title={subs.length ? "Listening for reports" : "No coverage yet"}>
                      {subs.length
                        ? "New reports for your topics will appear here as soon as residents send them."
                        : "Subscribe to a barangay on the left, e.g. brgy.jaro.#, to start receiving reports."}
                    </EmptyState>
                  ) : (
                    <EmptyState icon={Inbox} title="Nothing here">No reports match this filter.</EmptyState>
                  )
                ) : (
                  <ul className="reports">
                    {feed.map(([id, r]) => (
                      <IncidentCard key={id} id={id} report={r} onStatus={updateStatus} />
                    ))}
                  </ul>
                )}
              </div>
            </section>
          </div>

          <ProtocolLog entries={conn.log} />
        </div>
      </main>
    </>
  );
}

function IncidentCard({ id, report: r, onStatus }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const status = r.status || "RECEIVED";
  const urgent = r.priority === "URGENT";
  const resolved = status === "RESOLVED";

  async function act(next) {
    setBusy(true);
    await onStatus(id, next, note);
    setBusy(false);
    setNote("");
  }

  return (
    <li className={`report${urgent && !resolved ? " is-urgent" : ""}${resolved ? " is-resolved" : ""}`}>
      <div className="report-head">
        <CategoryTile category={r.category} urgent={urgent} />
        <div className="report-title">
          <strong>{categoryMeta(r.category).label}</strong>
          <span><MapPin size={13} /> {placeFromTopic(r.topic || r.lastTopic)}</span>
        </div>
        <div className="report-badges">
          {urgent && <span className="badge badge-urgent">Urgent</span>}
          {r.escalated && <span className="badge badge-escalated">Escalated to city</span>}
          <StatusBadge status={status} />
        </div>
      </div>
      {r.description && <p className="report-desc">{r.description}</p>}
      <StatusStepper status={status} />
      {r.note && <p className="report-note"><MessageSquare size={15} /> <span><strong>Last note:</strong> {r.note}</span></p>}
      <div className="report-meta">
        <span>#{id}</span>
        <span><User size={12} /> {r.reporter ? r.reporter : "Anonymous"}</span>
        <span><Clock size={12} /> {clockTime(r.receivedAt)}</span>
      </div>
      {!resolved && (
        <div className="report-actions">
          <input className="input" placeholder="Add a note for the resident (optional)" maxLength={200}
            value={note} onChange={(e) => setNote(e.target.value)} aria-label={`Note for report ${id}`} />
          {status === "RECEIVED" && (
            <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => act("RESPONDING")}>
              <Truck size={15} /> Respond
            </button>
          )}
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => act("RESOLVED")}>
            <CheckCircle2 size={15} /> Resolve
          </button>
        </div>
      )}
    </li>
  );
}
