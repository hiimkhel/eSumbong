import { useEffect, useRef, useState } from "react";
import { Bell, BellRing, Clock, Database, Eye, EyeOff, Hash, Inbox, MapPin, Megaphone, MessageSquare, PenLine, Send, Siren, Smartphone, Undo2, X } from "lucide-react";
import AppBar from "../components/AppBar.jsx";
import Combobox from "../components/Combobox.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import ProtocolLog from "../components/ProtocolLog.jsx";
import SignIn from "../components/SignIn.jsx";
import { useToast } from "../components/Toast.jsx";
import { CategoryTile, EmptyState, FieldError, HiddenToggle, StatusStepper } from "../components/ui.jsx";
import { useConnection } from "../hooks/useConnection.js";
import { useDismissed } from "../hooks/useDismissed.js";
import { barangayName, categoryMeta, clockTime, isClosed, placeFromTopic, titleCase } from "../lib/format.js";
import { loadConfig, oneLine, topicLevel } from "../lib/sumbong.js";

const STATUS_TOPIC = /^report\.[^.]+\.status$/;
const MAX_DESCRIPTION = 500;
const MAX_PLACE = 40; // purok or landmark, as one topic level

// Resident: file reports and follow their status (report.<id>.status).
export default function Resident() {
  const toast = useToast();
  const [cfg, setCfg] = useState({ categories: [], urgent_categories: [], barangays: [], district_name: "Jaro" });
  const [identity, setIdentity] = useState("");
  const [form, setForm] = useState({ barangay: "", purok: "", category: "", description: "", anonymous: false });
  const [reports, setReports] = useState(() => new Map()); // report_id -> report
  const [advisories, setAdvisories] = useState([]);
  const [following, setFollowing] = useState(null);         // advisory topic subscribed
  const [sending, setSending] = useState(false);
  const [tab, setTab] = useState("report");                 // phone-only section tabs
  const pending = useRef([]);     // reports sent, waiting for REPORTED (broker answers in order)
  const autoSignIn = useRef(false);

  const conn = useConnection({
    page: "resident",
    onState: (status) => {
      if (status !== "online") setFollowing(null);
    },
    onEvent: (event) => {
      if (event.command === "UPDATED" && event.status === "WITHDRAWN") {
        setReports((prev) => {
          const r = prev.get(event.reportId);
          return r ? new Map(prev).set(event.reportId, { ...r, status: "WITHDRAWN" }) : prev;
        });
        toast("Report withdrawn. Your barangay has been told.");
      } else if (event.command === "SUBS") {
        setFollowing(event.patterns.find((p) => /^brgy\.[^.]+\.advisory$/.test(p)) || null);
      } else if (event.command === "HIST") {
        // A report filed earlier, restored after signing in again.
        const body = event.body || {};
        if (!body.report_id) return;
        setReports((prev) => new Map(prev).set(body.report_id, {
          ...prev.get(body.report_id),
          topic: body.topic,
          category: body.category,
          description: body.description,
          status: body.status,
          escalated: Boolean(body.escalated),
          note: body.note,
          anonymous: Boolean(body.anonymous),
          sentAt: body.created_at ? body.created_at * 1000 : Date.now(),
        }));
      } else if (event.command === "REPORTED") {
        const report = pending.current.shift();
        if (!report) return;
        // Fire, fight and flood go to the city desk the moment they're filed.
        const urgent = cfg.urgent_categories.includes(report.category);
        setReports((prev) => new Map(prev).set(event.reportId, { ...report, status: "RECEIVED", escalated: urgent }));
        setTab("reports"); // on phones, show the new report's tracker
        toast(urgent ? "Report sent to your barangay and the city desk." : "Report sent. Your barangay has been notified.");
      } else if (event.command === "MSG") {
        const body = event.body || {};
        if (STATUS_TOPIC.test(event.topic) && body.report_id) {
          const before = reports.get(body.report_id);
          const label = categoryMeta(body.category).label;
          if (body.status === "WITHDRAWN") { /* UPDATED already confirmed it */ }
          else if (body.escalated && !before?.escalated) toast(`Your ${label.toLowerCase()} report was escalated to the city desk.`);
          else toast(`${label} report is now ${titleCase(String(body.status).toLowerCase())}`);
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

  const [restoring, setRestoring] = useState(Boolean(conn.saved));
  const [dismissed, dismiss, restore] = useDismissed("resident", identity);
  const [showHidden, setShowHidden] = useState(false);
  const [withdrawAsk, setWithdrawAsk] = useState(null); // report id waiting for "Withdraw?" confirmation
  const [errors, setErrors] = useState({});     // field -> message, shown under the field
  const [hideAsk, setHideAsk] = useState(null); // report id waiting for "Hide?" confirmation

  async function connect(id) {
    setReports(new Map());
    setAdvisories([]);
    pending.current = [];
    try {
      await conn.connect(id, "resident");
      setIdentity(id);
      await conn.send("SUBS");     // which advisories this ID follows
      await conn.send("HISTORY");  // reports this ID filed before
    } catch (err) {
      toast(err.message, true);
    } finally {
      setRestoring(false);
    }
  }

  // Sign this tab back in after a reload or the back button.
  useEffect(() => {
    if (autoSignIn.current) return;
    autoSignIn.current = true;
    if (conn.saved) connect(conn.saved.id);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!conn.online) {
    if (restoring) return <AppBar active="resident" conn={conn} />;
    return (
      <>
        <AppBar active="resident" conn={conn} />
        <SignIn
          defaultId={conn.lastId?.id}
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
    setErrors((errs) => (errs[field] ? { ...errs, [field]: undefined } : errs)); // fixing it clears it
  };

  // The barangay must be one of the district's (typed or picked from the list).
  const typed = form.barangay.trim().toLowerCase();
  const barangayId = cfg.barangays.find((b) => b.name.toLowerCase() === typed || b.id === topicLevel(typed))?.id || "";
  const unknownBarangay = typed !== "" && !barangayId;
  // Only flag it red once no barangay even contains the text (not while typing "san").
  const noBarangayMatch = unknownBarangay && !cfg.barangays.some((b) => b.name.toLowerCase().includes(typed));
  const barangayError = errors.barangay || (noBarangayMatch ? `Not a barangay of ${cfg.district_name}. Pick one from the list.` : null);
  const place = topicLevel(form.purok).slice(0, MAX_PLACE).replace(/-+$/, "");
  const levels = [barangayId, place, form.category];
  const topic = levels.every(Boolean) ? `brgy.${levels.join(".")}` : null;
  const isUrgent = (category) => cfg.urgent_categories.includes(category);

  async function onReport(e) {
    e.preventDefault();
    const description = oneLine(form.description);
    const errs = {};
    if (!typed) errs.barangay = `Pick your barangay in ${cfg.district_name}.`;
    else if (!barangayId) errs.barangay = `Not a barangay of ${cfg.district_name}. Pick one from the list.`;
    if (!form.purok.trim()) errs.purok = "Add your purok or a nearby landmark.";
    else if (!place) errs.purok = "Use letters or numbers, e.g. Purok 3.";
    if (!description) errs.description = "Tell your barangay what's happening.";
    setErrors(errs);
    const first = ["barangay", "purok", "description"].find((k) => errs[k]);
    if (first) {
      document.getElementById(`f-${first}`)?.focus();
      return;
    }
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
    const barangay = barangayId;
    if (!barangay) return toast(`Pick your barangay of ${cfg.district_name} first.`, true);
    const advisoryTopic = `brgy.${barangay}.advisory`;
    if (following === advisoryTopic) return;
    try {
      if (following) await conn.send(`UNSUB ${following}`);
      await conn.send(`SUB ${advisoryTopic}`);
      setFollowing(advisoryTopic);
      toast(`You'll get advisories from ${barangayName(barangay)}.`);
    } catch (err) {
      toast(err.message, true);
    }
  }

  // Resolved reports the resident hid stay off the list (only in this browser),
  // unless "Show hidden" is open; they then come last, marked Hidden.
  const isHidden = (id, r) => isClosed(r.status) && dismissed.has(id);
  const newestFirst = [...reports.entries()].reverse();
  const hiddenCount = newestFirst.filter(([id, r]) => isHidden(id, r)).length;
  const shownList = newestFirst.filter(([id, r]) => !isHidden(id, r));
  const reportList = showHidden ? [...shownList, ...newestFirst.filter(([id, r]) => isHidden(id, r))] : shownList;
  const followTarget = barangayId;
  const isFollowingTarget = following && following === `brgy.${followTarget}.advisory`;
  const hideOnPhone = (id) => (tab === id ? "" : " m-hide");
  const tabs = [
    { id: "report", label: "New report", icon: PenLine },
    { id: "reports", label: "My reports", icon: Inbox, count: shownList.length },
    { id: "advisories", label: "Advisories", icon: Megaphone, count: advisories.length },
  ];

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

          <div className="m-tabs" role="tablist" aria-label="Sections">
            {tabs.map(({ id, label, icon: Icon, count }) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
                <Icon size={16} /> {label}
                {count > 0 && <span className="count">{count}</span>}
              </button>
            ))}
          </div>

          <div className="split">
            <section className={`card card-pad${hideOnPhone("report")}`} aria-labelledby="new-report">
              <div className="card-head">
                <div>
                  <h2 className="card-title" id="new-report">New report</h2>
                  <p className="card-sub">Your barangay and purok or landmark send it to the right tanods.</p>
                </div>
              </div>

              <form className="form-stack" onSubmit={onReport} noValidate>
                <div className="field-row">
                  <label className="field">
                    <span className="field-label">Barangay</span>
                    <Combobox id="f-barangay" icon={MapPin} required placeholder="Type or pick, e.g. San Roque"
                      value={form.barangay} invalid={Boolean(barangayError)}
                      onChange={(text) => set("barangay")({ target: { value: text } })}
                      options={cfg.barangays.map((b) => ({ value: b.id, label: b.name }))} />
                    {barangayError
                      ? <FieldError>{barangayError}</FieldError>
                      : <span className="field-hint">{cfg.district_name}, {cfg.city_name || "Iloilo City"}</span>}
                  </label>
                  <label className="field">
                    <span className="field-label">Purok / Landmark</span>
                    <span className="input-icon">
                      <Hash size={17} />
                      <input id="f-purok" className="input" required maxLength={MAX_PLACE} placeholder="e.g. Purok 3 or near Jaro Plaza"
                        aria-invalid={errors.purok ? true : undefined} value={form.purok} onChange={set("purok")} />
                    </span>
                    {errors.purok
                      ? <FieldError>{errors.purok}</FieldError>
                      : <span className="field-hint">Purok number or a nearby landmark</span>}
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
                    <Siren size={16} /> {categoryMeta(form.category).label} reports are marked urgent, go to the top of the responders' feed, and are sent to the city desk at once.
                  </div>
                )}

                <label className="field">
                  <span className="field-label">What happened?</span>
                  <textarea id="f-description" className="textarea" required maxLength={MAX_DESCRIPTION}
                    aria-invalid={errors.description ? true : undefined}
                    placeholder="Describe what's happening and the exact spot, e.g. near the chapel on Rizal St."
                    value={form.description} onChange={set("description")} />
                  <span className="field-foot">
                    {errors.description ? <FieldError>{errors.description}</FieldError> : <span />}
                    <span className="counter">{form.description.length}/{MAX_DESCRIPTION}</span>
                  </span>
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
              <section className={`card card-pad${hideOnPhone("reports")}`} aria-labelledby="your-reports">
                <div className="card-head">
                  <div>
                    <h2 className="card-title" id="your-reports">Your reports</h2>
                    <p className="card-sub">Updates appear here as responders act.</p>
                  </div>
                  {shownList.length > 0 && <span className="badge badge-neutral">{shownList.length}</span>}
                </div>
                {reportList.length === 0 ? (
                  <EmptyState icon={Inbox} title={hiddenCount ? "All your reports are hidden" : "No reports yet"}>
                    {hiddenCount ? "They're resolved and still saved. Show them below." : "When you send a report, you'll follow it here from received to resolved."}
                  </EmptyState>
                ) : (
                  <ul className="reports">
                    {reportList.map(([id, r]) => {
                      const urgent = isUrgent(r.category);
                      const resolved = isClosed(r.status); // resolved or withdrawn
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
                              {resolved && isHidden(id, r) ? (
                                <>
                                  <span className="badge badge-neutral"><EyeOff size={12} /> Hidden</span>
                                  <button type="button" className="btn btn-ghost btn-sm" aria-label={`Unhide report ${id}`}
                                    onClick={() => restore(id)}>
                                    <Eye size={15} /> Unhide
                                  </button>
                                </>
                              ) : resolved && (
                                <button type="button" className="icon-btn" title="Hide this resolved report"
                                  aria-label={`Hide report ${id}`} onClick={() => setHideAsk(id)}>
                                  <X size={16} />
                                </button>
                              )}
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
                          {(r.status || "RECEIVED") === "RECEIVED" && (
                            <div className="report-foot">
                              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setWithdrawAsk(id)}>
                                <Undo2 size={15} /> Withdraw report
                              </button>
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
                <HiddenToggle count={hiddenCount} open={showHidden} onToggle={() => setShowHidden((v) => !v)} />
              </section>

              <section className={`card card-pad${hideOnPhone("advisories")}`} aria-labelledby="advisories">
                <div className="card-head">
                  <div>
                    <h2 className="card-title" id="advisories">Barangay advisories</h2>
                    <p className="card-sub">
                      {following ? `Following ${placeFromTopic(following).split(" · ")[0] || following}` : "Announcements from your barangay."}
                    </p>
                  </div>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={onFollow} disabled={!followTarget || isFollowingTarget}>
                    {isFollowingTarget ? <><BellRing size={15} /> Following</> : <><Bell size={15} /> Follow{followTarget ? ` ${barangayName(followTarget)}` : ""}</>}
                  </button>
                </div>
                {advisories.length === 0 ? (
                  <EmptyState icon={Megaphone} title="No advisories">
                    {following
                      ? "You'll see announcements here when your barangay posts them."
                      : followTarget ? `Follow ${barangayName(followTarget)} to get its announcements here.` : "Enter your barangay in the report form, then follow it here."}
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
          <ConfirmDialog open={hideAsk !== null} title="Hide this report?" confirmLabel="Hide report"
            icon={EyeOff} confirmIcon={EyeOff}
            onCancel={() => setHideAsk(null)}
            onConfirm={() => { dismiss(hideAsk); setHideAsk(null); }}>
            <p className="confirm-line"><Smartphone size={16} /> <span>This report will be removed from your list on this device.</span></p>
            <p className="confirm-line muted"><Database size={16} /> <span>It is <strong>not deleted</strong>: the report and its full history stay saved in eSumbong.</span></p>
          </ConfirmDialog>
          <ConfirmDialog open={withdrawAsk !== null} title="Withdraw this report?" confirmLabel="Withdraw report"
            icon={Undo2} confirmIcon={Undo2}
            onCancel={() => setWithdrawAsk(null)}
            onConfirm={() => {
              const id = withdrawAsk;
              setWithdrawAsk(null);
              conn.send(`WITHDRAW ${id}`).catch((err) => toast(err.message, true));
            }}>
            <p className="confirm-line"><Megaphone size={16} /> <span>Use this if you sent it by mistake or twice. Your barangay's tanods will be told it was withdrawn.</span></p>
            <p className="confirm-line muted"><Database size={16} /> <span>It is <strong>not deleted</strong>: it stays saved in eSumbong, marked Withdrawn.</span></p>
          </ConfirmDialog>
        </div>
      </main>
    </>
  );
}
