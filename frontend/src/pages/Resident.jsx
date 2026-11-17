import { useEffect, useRef, useState } from "react";
import Header from "../components/Header.jsx";
import ProtocolLog from "../components/ProtocolLog.jsx";
import StatusPills from "../components/StatusPills.jsx";
import { useToast } from "../components/Toast.jsx";
import { useConnection } from "../hooks/useConnection.js";
import { loadConfig, oneLine, topicLevel } from "../lib/sumbong.js";

const STATUS_TOPIC = /^report\.[^.]+\.status$/;

// Resident: file reports and follow their status (report.<id>.status).
export default function Resident() {
  const toast = useToast();
  const [cfg, setCfg] = useState({ categories: [], urgent_categories: [] });
  const [clientId, setClientId] = useState("");
  const [form, setForm] = useState({ barangay: "", purok: "", category: "", description: "", anonymous: false });
  const [reports, setReports] = useState(() => new Map()); // report_id -> report
  const [advisories, setAdvisories] = useState([]);
  const pending = useRef([]);     // reports sent, waiting for REPORTED (broker answers in order)
  const followed = useRef(null);  // advisory topic currently subscribed

  const conn = useConnection({
    onState: (status, reason) => {
      if (status === "online") return;
      followed.current = null;
      if (reason) toast(reason, true);
    },
    onEvent: (event) => {
      if (event.command === "REPORTED") {
        const report = pending.current.shift();
        if (!report) return;
        setReports((prev) => new Map(prev).set(event.reportId, { ...report, status: "RECEIVED", escalated: false }));
        toast(`Report ${event.reportId} received`);
      } else if (event.command === "MSG") {
        const body = event.body || {};
        if (STATUS_TOPIC.test(event.topic) && body.report_id) {
          setReports((prev) => {
            const existing = prev.get(body.report_id) || {};
            return new Map(prev).set(body.report_id, {
              ...existing,
              topic: existing.topic || body.topic,
              category: existing.category || body.category,
              description: existing.description || body.description,
              status: body.status || existing.status,
              escalated: Boolean(body.escalated),
              note: body.note || existing.note,
            });
          });
          toast(`Report ${body.report_id}: ${body.status}`);
        } else {
          const advisory = { topic: event.topic, priority: event.priority, body, time: new Date() };
          setAdvisories((prev) => [advisory, ...prev]);
        }
      } else if (event.command === "ERR") {
        if (conn.lastCommand.current === "REPORT") pending.current.shift();
        toast(`Broker error: ${event.reason}`, true);
      }
    },
  });

  useEffect(() => {
    loadConfig()
      .then((c) => {
        setCfg(c);
        setForm((f) => ({ ...f, category: f.category || c.categories[0] || "" }));
      })
      .catch((err) => toast(err.message, true));
  }, [toast]);

  const set = (field) => (e) => {
    const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [field]: value }));
  };

  const levels = [form.barangay, form.purok, form.category].map(topicLevel);
  const topic = levels.every(Boolean) ? `brgy.${levels.join(".")}` : null;

  async function onConnect(e) {
    e.preventDefault();
    try {
      await conn.connect(clientId.trim(), "resident");
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function onReport(e) {
    e.preventDefault();
    const description = oneLine(form.description);
    if (!topic || !description) return toast("Fill in barangay, purok, category, and description", true);
    pending.current.push({ topic, category: form.category, description, anonymous: form.anonymous });
    try {
      await conn.send(`REPORT ${topic} ${form.anonymous ? "Y" : "N"} ${description}`);
      setForm((f) => ({ ...f, description: "" }));
    } catch (err) {
      pending.current.pop();
      toast(err.message, true);
    }
  }

  async function onFollowAdvisories() {
    const barangay = topicLevel(form.barangay);
    if (!barangay) return toast("Enter your barangay first", true);
    const advisoryTopic = `brgy.${barangay}.advisory`;
    if (followed.current === advisoryTopic) return toast(`Already following ${advisoryTopic}`);
    try {
      if (followed.current) await conn.send(`UNSUB ${followed.current}`);
      await conn.send(`SUB ${advisoryTopic}`);
      followed.current = advisoryTopic;
      toast(`Following ${advisoryTopic}`);
    } catch (err) {
      toast(err.message, true);
    }
  }

  const reportList = [...reports.entries()].reverse();

  return (
    <>
      <Header section="Resident" conn={conn} />
      <main className="grid">
        <section className="card">
          <h2>1. Connect</h2>
          <form onSubmit={onConnect}>
            <label htmlFor="client-id">Your ID (no spaces)</label>
            <input id="client-id" required maxLength={64} pattern="\S+" placeholder="e.g. juan-dc"
              value={clientId} onChange={(e) => setClientId(e.target.value)} disabled={conn.online} />
            <div className="row actions">
              <button type="submit" disabled={conn.online}>Connect</button>
              <button type="button" className="secondary" disabled={!conn.online} onClick={conn.disconnect}>Disconnect</button>
            </div>
          </form>
        </section>

        <section className="card">
          <h2>2. Report an incident</h2>
          <form onSubmit={onReport}>
            <div className="row">
              <div>
                <label htmlFor="barangay">Barangay</label>
                <input id="barangay" required placeholder="e.g. jaro" value={form.barangay} onChange={set("barangay")} />
              </div>
              <div>
                <label htmlFor="purok">Purok</label>
                <input id="purok" required placeholder="e.g. purok-3" value={form.purok} onChange={set("purok")} />
              </div>
            </div>
            <label htmlFor="category">Category</label>
            <select id="category" required value={form.category} onChange={set("category")}>
              {cfg.categories.map((name) => (
                <option key={name} value={name}>
                  {cfg.urgent_categories.includes(name) ? `${name} (urgent)` : name}
                </option>
              ))}
            </select>
            <label htmlFor="description">What happened?</label>
            <textarea id="description" required maxLength={500} placeholder="Short description and exact location"
              value={form.description} onChange={set("description")} />
            <label className="check">
              <input type="checkbox" checked={form.anonymous} onChange={set("anonymous")} /> Report anonymously
            </label>
            <p className="meta">Topic: {topic || "—"}</p>
            <div className="row">
              <button type="submit" disabled={!conn.online}>Send report</button>
              <button type="button" className="secondary" disabled={!conn.online} onClick={onFollowAdvisories}>
                Follow barangay advisories
              </button>
            </div>
          </form>
        </section>

        <section className="card">
          <h2>My reports</h2>
          {reportList.length === 0 ? <p className="empty">No reports yet.</p> : (
            <ul className="list">
              {reportList.map(([id, r]) => {
                const urgent = cfg.urgent_categories.includes(r.category);
                return (
                  <li key={id} className={urgent ? "urgent" : ""}>
                    <div className="item-head">
                      <strong>{r.category || "report"}</strong>
                      <StatusPills status={r.status} urgent={urgent} escalated={r.escalated} />
                    </div>
                    <p className="item-body">{r.description}</p>
                    {r.note && <p className="meta">Responder note: {r.note}</p>}
                    <p className="meta">#{id} · {r.topic}{r.anonymous ? " · anonymous" : ""}</p>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="card">
          <h2>Advisories</h2>
          {advisories.length === 0 ? <p className="empty">Nothing yet.</p> : (
            <ul className="list">
              {advisories.map((a, i) => (
                <li key={advisories.length - i} className={a.priority === "URGENT" ? "urgent" : ""}>
                  <p className="item-body">{a.body?.description || JSON.stringify(a.body)}</p>
                  <p className="meta">{a.topic} · {a.time.toLocaleTimeString()}</p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <ProtocolLog entries={conn.log} />
      </main>
    </>
  );
}
