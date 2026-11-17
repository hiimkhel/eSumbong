import { useEffect, useRef, useState } from "react";
import { Bell, BellRing, Clock, EyeOff, Hash, Inbox, MapPin, Megaphone, MessageSquare, Send, Siren } from "lucide-react";
import AppBar from "../components/AppBar.jsx";
import ProtocolLog from "../components/ProtocolLog.jsx";
import SignIn from "../components/SignIn.jsx";
import { useToast } from "../components/Toast.jsx";
import { CategoryTile, EmptyState, StatusStepper } from "../components/ui.jsx";
import { useConnection } from "../hooks/useConnection.js";
import { categoryMeta, clockTime, placeFromTopic, titleCase } from "../lib/format.js";
import { loadConfig, oneLine, topicLevel } from "../lib/sumbong.js";

const STATUS_TOPIC = /^report\.[^.]+\.status$/;
const MAX_DESCRIPTION = 500;

// Resident: file reports and follow their status (report.<id>.status).
export default function Resident() {
  const toast = useToast();
  const [cfg, setCfg] = useState({ categories: [], urgent_categories: [] });
  const [identity, setIdentity] = useState("");
  const [form, setForm] = useState({ barangay: "", purok: "", category: "", description: "", anonymous: false });
  const [reports, setReports] = useState(() => new Map()); // report_id -> report
  const [advisories, setAdvisories] = useState([]);
  const [following, setFollowing] = useState(null);         // advisory topic subscribed
  const [sending, setSending] = useState(false);
  const pending = useRef([]);     // reports sent, waiting for REPORTED (broker answers in order)

  const conn = useConnection({
    onState: (status) => {
      if (status !== "online") setFollowing(null);
    },
    onEvent: (event) => {
      if (event.command === "REPORTED") {
        const report = pending.current.shift();
        if (!report) return;
        setReports((prev) => new Map(prev).set(event.reportId, { ...report, status: "RECEIVED", escalated: false }));
        toast("Report sent. Your barangay has been notified.");
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
              sentAt: existing.sentAt || Date.now(),
            });
          });
          toast(`${categoryMeta(body.category).label} report is now ${titleCase(String(body.status).toLowerCase())}`);
        } else {
          const advisory = { topic: event.topic, priority: event.priority, body, time: Date.now() };
          setAdvisories((prev) => [advisory, ...prev]);
        }
      } else if (event.command === "ERR") {
        if (conn.lastCommand.current === "REPORT") pending.current.shift();
        toast(`Couldn't complete that: ${event.reason}`, true);
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

  async function connect(id) {
    try {
      await conn.connect(id, "resident");
      setIdentity(id);
    } catch (err) {
      toast(err.message, true);
    }
  }

  if (!conn.online) {
    return (
      <>
        <AppBar active="resident" conn={conn} />
        <SignIn
          title="Report an incident"
          lead="Sign in with a short ID so you can follow your reports as your barangay responds."
          foot="Your reports go straight to your barangay's responders."
          placeholder="e.g. juan-dc"
          reason={conn.reason}
          onConnect={connect}
        />
      </>
    );
  }

  const set = (field) => (e) => {
    const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [field]: value }));
  };

  const levels = [form.barangay, form.purok, form.category].map(topicLevel);
  const topic = levels.every(Boolean) ? `brgy.${levels.join(".")}` : null;
  const isUrgent = (category) => cfg.urgent_categories.includes(category);

  async function onReport(e) {
    e.preventDefault();
    const description = oneLine(form.description);
    if (!topic || !description) return toast("Add your barangay, purok, a category and what happened.", true);
    pending.current.push({ topic, category: form.category, description, anonymous: form.anonymous, sentAt: Date.now() });
    setSending(true);
    try {
      await conn.send(`REPORT ${topic} ${form.anonymous ? "Y" : "N"} ${description}`);
      setForm((f) => ({ ...f, description: "" }));
    } catch (err) {
      pending.current.pop();
      toast(err.message, true);
    } finally {
      setSending(false);
    }
  }

  async function onFollow() {
    const barangay = topicLevel(form.barangay);
    if (!barangay) return toast("Enter your barangay first.", true);
    const advisoryTopic = `brgy.${barangay}.advisory`;
    if (following === advisoryTopic) return;
    try {
      if (following) await conn.send(`UNSUB ${following}`);
      await conn.send(`SUB ${advisoryTopic}`);
      setFollowing(advisoryTopic);
      toast(`You'll get advisories from ${titleCase(barangay)}.`);
    } catch (err) {
      toast(err.message, true);
    }
  }

  const reportList = [...reports.entries()].reverse();
  const followTarget = topicLevel(form.barangay);
  const isFollowingTarget = following && following === `brgy.${followTarget}.advisory`;

  return (
    <>
      <AppBar active="resident" conn={conn} identity={identity} />
      <main className="page">
        <div className="container">
          <div className="page-head">
            <div>
              <span className="eyebrow">Resident</span>
              <h1>May sumbong ka?</h1>
              <p>Tell your barangay what's happening. You'll see each update here.</p>
            </div>
          </div>

          <div className="split">
            <section className="card card-pad" aria-labelledby="new-report">
              <div className="card-head">
                <div>
                  <h2 className="card-title" id="new-report">New report</h2>
                  <p className="card-sub">Your barangay and purok send it to the right tanods.</p>
                </div>
              </div>

              <form className="form-stack" onSubmit={onReport}>
                <div className="field-row">
                  <label className="field">
                    <span className="field-label">Barangay</span>
                    <span className="input-icon">
                      <MapPin size={17} />
                      <input className="input" required placeholder="e.g. Jaro" value={form.barangay} onChange={set("barangay")} />
                    </span>
                  </label>
                  <label className="field">
                    <span className="field-label">Purok</span>
                    <span className="input-icon">
                      <Hash size={17} />
                      <input className="input" required placeholder="e.g. Purok 3" value={form.purok} onChange={set("purok")} />
                    </span>
                  </label>
                </div>

                <div className="field">
                  <span className="field-label" id="cat-label">What kind of incident?</span>
                  <div className="cat-grid" role="radiogroup" aria-labelledby="cat-label">
                    {cfg.categories.map((name) => {
                      const { label, icon: Icon } = categoryMeta(name);
                      const urgent = isUrgent(name);
                      return (
                        <button key={name} type="button" role="radio" aria-checked={form.category === name}
                          className={`cat${urgent ? " is-urgent" : ""}`}
                          onClick={() => setForm((f) => ({ ...f, category: name }))}>
                          {urgent && <span className="cat-flag" title="Urgent" />}
                          <Icon size={22} />
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {isUrgent(form.category) && (
                  <div className="urgent-note">
                    <Siren size={16} /> {categoryMeta(form.category).label} reports are marked urgent and go to the top of the responders' feed.
                  </div>
                )}

                <label className="field">
                  <span className="field-label">What happened?</span>
                  <textarea className="textarea" required maxLength={MAX_DESCRIPTION}
                    placeholder="Describe what's happening and the exact spot, e.g. near the chapel on Rizal St."
                    value={form.description} onChange={set("description")} />
                  <span className="counter">{form.description.length}/{MAX_DESCRIPTION}</span>
                </label>

                <label className="switch">
                  <input type="checkbox" checked={form.anonymous} onChange={set("anonymous")} />
                  <span className="switch-track" aria-hidden="true" />
                  <span className="switch-text">
                    <strong>Report anonymously</strong>
                    <span>Responders won't see your ID.</span>
                  </span>
                </label>

                <div className="form-foot">
                  <span className="topic-chip" title="Topic this report is published to">
                    <Hash size={13} /> {topic || "brgy.barangay.purok.category"}
                  </span>
                  <button type="submit" className="btn btn-primary btn-lg" disabled={sending}>
                    <Send size={17} /> {sending ? "Sending…" : "Send report"}
                  </button>
                </div>
              </form>
            </section>

            <div className="stack">
              <section className="card card-pad" aria-labelledby="your-reports">
                <div className="card-head">
                  <div>
                    <h2 className="card-title" id="your-reports">Your reports</h2>
                    <p className="card-sub">Updates appear here as responders act.</p>
                  </div>
                  {reportList.length > 0 && <span className="badge badge-neutral">{reportList.length}</span>}
                </div>
                {reportList.length === 0 ? (
                  <EmptyState icon={Inbox} title="No reports yet">
                    When you send a report, you'll follow it here from received to resolved.
                  </EmptyState>
                ) : (
                  <ul className="reports">
                    {reportList.map(([id, r]) => {
                      const urgent = isUrgent(r.category);
                      const resolved = r.status === "RESOLVED";
                      return (
                        <li key={id} className={`report${urgent ? " is-urgent" : ""}${resolved ? " is-resolved" : ""}`}>
                          <div className="report-head">
                            <CategoryTile category={r.category} urgent={urgent} />
                            <div className="report-title">
                              <strong>{categoryMeta(r.category).label}</strong>
                              <span><MapPin size={13} /> {placeFromTopic(r.topic)}</span>
                            </div>
                            <div className="report-badges">
                              {urgent && <span className="badge badge-urgent">Urgent</span>}
                              {r.escalated && <span className="badge badge-escalated">Escalated to city</span>}
                            </div>
                          </div>
                          {r.description && <p className="report-desc">{r.description}</p>}
                          <StatusStepper status={r.status} />
                          {r.note && (
                            <p className="report-note"><MessageSquare size={15} /> <span><strong>Responder:</strong> {r.note}</span></p>
                          )}
                          <div className="report-meta">
                            <span>#{id}</span>
                            {r.sentAt && <span><Clock size={12} /> {clockTime(r.sentAt)}</span>}
                            {r.anonymous && <span><EyeOff size={12} /> Anonymous</span>}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>

              <section className="card card-pad" aria-labelledby="advisories">
                <div className="card-head">
                  <div>
                    <h2 className="card-title" id="advisories">Barangay advisories</h2>
                    <p className="card-sub">
                      {following ? `Following ${placeFromTopic(following).split(" · ")[0] || following}` : "Announcements from your barangay."}
                    </p>
                  </div>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={onFollow} disabled={!followTarget || isFollowingTarget}>
                    {isFollowingTarget ? <><BellRing size={15} /> Following</> : <><Bell size={15} /> Follow{followTarget ? ` ${titleCase(followTarget)}` : ""}</>}
                  </button>
                </div>
                {advisories.length === 0 ? (
                  <EmptyState icon={Megaphone} title="No advisories">
                    {following
                      ? "You'll see announcements here when your barangay posts them."
                      : followTarget ? `Follow ${titleCase(followTarget)} to get its announcements here.` : "Enter your barangay in the report form, then follow it here."}
                  </EmptyState>
                ) : (
                  <ul className="advisories">
                    {advisories.map((a, i) => (
                      <li key={advisories.length - i} className={`advisory${a.priority === "URGENT" ? " is-urgent" : ""}`}>
                        {a.priority === "URGENT" ? <Siren size={18} /> : <Megaphone size={18} />}
                        <div>
                          <p>{a.body?.description || JSON.stringify(a.body)}</p>
                          <small>{clockTime(a.time)}</small>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </div>

          <ProtocolLog entries={conn.log} />
        </div>
      </main>
    </>
  );
}
