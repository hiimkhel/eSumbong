import { useEffect, useMemo, useRef, useState } from "react";
import {
  Building2, CheckCircle2, ChevronDown, Database, Eye, EyeOff, Clock, Inbox, MapPin, Megaphone, MessageSquare, Plus, Radio, Send,
  ShieldCheck, Siren, Truck, User, X,
} from "lucide-react";
import AppBar from "../components/AppBar.jsx";
import Combobox from "../components/Combobox.jsx";
import ConfirmDialog from "../components/ConfirmDialog.jsx";
import ProtocolLog from "../components/ProtocolLog.jsx";
import SignIn from "../components/SignIn.jsx";
import { useToast } from "../components/Toast.jsx";
import { CategoryTile, EmptyState, FieldError, HiddenToggle, StatusBadge, StatusStepper } from "../components/ui.jsx";
import { useConnection } from "../hooks/useConnection.js";
import { useDismissed } from "../hooks/useDismissed.js";
import { advisorySender, barangayList, barangayName, categoryMeta, clockTime, isClosed, placeFromTopic } from "../lib/format.js";
import { loadConfig, oneLine, reportCovered } from "../lib/sumbong.js";

// Responders sign in with an ID and PIN; the one city desk with a password only
// (accounts are made with users.py; the broker checks them, see auth.py).
const ROLES = [
  { value: "responder", label: "Responder", hint: "Tanod or captain", icon: ShieldCheck, secretLabel: "PIN" },
  { value: "desk", label: "City desk", hint: "Handles escalations", icon: Building2, secretLabel: "Desk password", fixedId: "city" },
];

// What each role may subscribe to (the broker enforces this; see escalation.py).
// A responder account tied to a barangay (users.py --barangay) may only cover that
// barangay, so its preset is that barangay; other responders get all of Jaro.
function presetsFor(role, barangay) {
  if (role === "desk") return [{ pattern: "city.iloilo.escalated.#", label: "Escalated to the city" }];
  if (barangay) return [{ pattern: `brgy.${barangay}.#`, label: `All of ${barangayName(barangay)}` }];
  return [{ pattern: "brgy.#", label: "All of Jaro" }];
}
const PATTERN_FOR = {
  responder: (id) => `brgy.${id}.#`,
  desk: (id) => `city.iloilo.escalated.${id}`,
};

const FILTERS = [
  { id: "all", label: "All", test: () => true },
  { id: "urgent", label: "Urgent", test: (r) => r.priority === "URGENT" && !isClosed(r.status) },
  { id: "open", label: "Open", test: (r) => !isClosed(r.status) },
  { id: "escalated", label: "Escalated", test: (r) => r.escalated && !isClosed(r.status) },
  // Finished reports: resolved, plus the few withdrawn ones (they carry a Withdrawn badge).
  { id: "resolved", label: "Resolved", test: (r) => isClosed(r.status) },
];

const urgentFirst = (r) => (r.priority === "URGENT" ? 0 : 1);

// A report resolved while this desk is open stays in the Open view (dimmed,
// at the bottom) until its ✕ is clicked, so it doesn't vanish on Resolve.
const withStatus = (r, status) => ({
  ...r,
  status,
  resolvedHere: r.resolvedHere || (isClosed(status) && !isClosed(r.status)),
});
const openFirst = (r) => (isClosed(r.status) ? 1 : 0);

// Responder / desk: subscribe to topics, receive reports, publish STATUS updates.
export default function Responder() {
  const toast = useToast();
  const [identity, setIdentity] = useState({ id: "", role: "responder" });
  const [pattern, setPattern] = useState("");
  const [subs, setSubs] = useState([]);
  const [reports, setReports] = useState(() => new Map()); // report_id -> latest body + extras
  const [filter, setFilter] = useState("open"); // resolved reports live in their own tab
  const [coverageOpen, setCoverageOpen] = useState(true);  // collapsible on phones only
  const seen = useRef(new Set());     // report ids already announced
  const lastSub = useRef(null);       // so an ERR right after SUB can roll it back
  // Advisories: the post form, the one waiting for POSTED, and the latest few seen.
  const [advForm, setAdvForm] = useState({ barangay: "", text: "", urgent: false });
  const [advErrors, setAdvErrors] = useState({});
  const [advisories, setAdvisories] = useState([]);
  const postingAdvisory = useRef(null);
  const [deskId, setDeskId] = useState(ROLES[1].fixedId); // config.DESK_ID, from /api/config
  const [accountBarangay, setAccountBarangay] = useState(null); // from the broker's ME reply
  const sentNotes = useRef(new Map()); // report_id -> note sent with STATUS, until UPDATED

  const conn = useConnection({
    page: "responder",
    onState: (status) => {
      if (status !== "online") setSubs([]);
    },
    onEvent: (event) => {
      if (event.command === "ME") {
        setAccountBarangay(event.barangay);
        // The account's own spelling: someone who typed sr-t01 is SR-T01.
        setIdentity((prev) => (event.clientId && prev.id !== event.clientId ? { ...prev, id: event.clientId } : prev));
      } else if (event.command === "UPDATED") {
        // The broker accepted our STATUS; only now does the card change.
        const note = sentNotes.current.get(event.reportId);
        sentNotes.current.delete(event.reportId);
        setReports((prev) => {
          const r = prev.get(event.reportId);
          return r ? new Map(prev).set(event.reportId, { ...withStatus(r, event.status), note: note ?? r.note }) : prev;
        });
        toast(event.status === "RESPONDING" ? "Marked as responding. The resident has been notified." : "Report resolved.");
      } else if (event.command === "SUBS") {
        setSubs(event.patterns);
        // Drop reports this ID's subscriptions no longer reach (e.g. dropped by the broker).
        setReports((prev) => new Map([...prev].filter(([id, r]) => reportCovered(event.patterns, id, r))));
      } else if (event.command === "HISTEND") {
        // SUB is always followed by HISTORY, and the broker answers in order,
        // so reaching HISTEND means the SUB before it was accepted.
        lastSub.current = null;
      } else if (event.command === "HIST") {
        // A report filed before this sign-in or subscription. No toast.
        const body = event.body;
        if (!body || !body.report_id) return;
        seen.current.add(body.report_id);
        setReports((prev) => {
          const existing = prev.get(body.report_id);
          return new Map(prev).set(body.report_id, {
            ...existing,
            ...body,
            priority: body.priority || event.priority,
            lastTopic: event.topic,
            receivedAt: existing?.receivedAt || (body.created_at ? body.created_at * 1000 : Date.now()),
          });
        });
      } else if (event.command === "POSTED") {
        const posted = postingAdvisory.current;
        postingAdvisory.current = null;
        if (!posted) return;
        addAdvisory({ ...posted, advisory_id: event.advisoryId });
        setAdvForm((f) => ({ ...f, text: "", urgent: false }));
        toast(`Advisory sent to ${barangayName(posted.barangay)}.`);
      } else if (event.command === "MSG" && event.body?.advisory_id) {
        addAdvisory(event.body);
        if (event.body.from !== identity.id) {
          toast(`Advisory for ${barangayName(event.body.barangay)}: ${event.body.description}`, event.body.priority === "URGENT");
        }
      } else if (event.command === "MSG") {
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
            resolvedHere: existing ? withStatus(existing, body.status).resolvedHere : false,
          });
        });
        const what = `${categoryMeta(body.category).label} at ${placeFromTopic(body.topic)}`;
        if (body.status === "WITHDRAWN" && reports.get(body.report_id)?.status !== "WITHDRAWN") {
          toast(`Withdrawn by the resident: ${what}`);
        }
        if (!seen.current.has(body.report_id)) {
          seen.current.add(body.report_id);
          if (priority === "URGENT") toast(`Urgent: ${what}`, true);
          else if (body.escalated) toast(`Escalated to the city: ${what}`, true);
        } else if (body.escalated && !reports.get(body.report_id)?.escalated) {
          toast(`Escalated to the city: ${what}`, true);
        }
      } else if (event.command === "ERR") {
        toast(`Broker error: ${event.reason}`, true);
        const stale = /^report (\S+) is already (RESPONDING|RESOLVED|WITHDRAWN)$/.exec(event.reason);
        if (stale) {
          const [, reportId, status] = stale;
          setReports((prev) => {
            const r = prev.get(reportId);
            return r ? new Map(prev).set(reportId, withStatus(r, status)) : prev;
          });
        }
        if (lastSub.current) {
          const failed = lastSub.current;
          lastSub.current = null;
          setSubs((prev) => prev.filter((p) => p !== failed));
        }
      }
    },
  });

  const [dismissed, dismiss, restore] = useDismissed("responder", identity.id);
  const [hideAsk, setHideAsk] = useState(null); // report id waiting for "Hide?" confirmation

  function addAdvisory(a) {
    setAdvisories((prev) => (prev.some((x) => x.advisory_id === a.advisory_id)
      ? prev
      : [{ ...a, time: Date.now() }, ...prev].slice(0, 5)));
  }
  // Hidden only once resolved: an open report must never disappear from the desk.
  const visible = useMemo(
    () => [...reports.entries()].filter(([id, r]) => !(isClosed(r.status) && dismissed.has(id))),
    [reports, dismissed],
  );

  // Hidden reports appear in no list, unless "Show hidden" is open in the Resolved tab.
  // They still count as resolved, so hiding never changes the numbers.
  const [showHidden, setShowHidden] = useState(false);
  const hiddenList = useMemo(
    () => [...reports.entries()]
      .filter(([id, r]) => isClosed(r.status) && dismissed.has(id))
      .sort(([, a], [, b]) => b.receivedAt - a.receivedAt),
    [reports, dismissed],
  );
  const hiddenHere = filter === "resolved";

  const counts = useMemo(() => {
    const all = visible.map(([, r]) => r);
    const result = Object.fromEntries(FILTERS.map((f) => [f.id, all.filter(f.test).length]));
    result.resolved += hiddenList.length;
    return result;
  }, [visible, hiddenList]);

  const feed = useMemo(() => {
    const { test } = FILTERS.find((f) => f.id === filter);
    const shown = visible
      .filter(([, r]) => test(r) || (filter === "open" && r.resolvedHere))
      .sort(([, a], [, b]) => openFirst(a) - openFirst(b) || urgentFirst(a) - urgentFirst(b) || b.receivedAt - a.receivedAt);
    return showHidden && hiddenHere ? [...shown, ...hiddenList] : shown;
  }, [visible, filter, showHidden, hiddenHere, hiddenList]);

  useEffect(() => {
    loadConfig().then((c) => c.desk_id && setDeskId(c.desk_id)).catch(() => { /* keep the default */ });
  }, []);

  // A refused sign-in (wrong PIN) throws, so SignIn shows why. There is no
  // automatic sign-in after a reload: the PIN is never stored, so it is asked again.
  async function connect(id, role, secret) {
    setReports(new Map());
    seen.current = new Set();
    lastSub.current = null;
    setAccountBarangay(null);
    await conn.connect(id, role, secret);
    setIdentity({ id, role });
    try {
      await conn.send("WHOAMI");   // which barangay this account may cover
      await conn.send("SUBS");     // coverage the broker kept for this ID
      await conn.send("HISTORY");  // reports that coverage already reaches
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
          placeholder="e.g. SR-T01"
          idHint="The ID your captain gave you, e.g. SR-T01 (San Roque, tanod 1)."
          roles={ROLES.map((r) => (r.fixedId ? { ...r, fixedId: deskId } : r))}
          defaultId={conn.lastId?.id}
          defaultRole={conn.lastId?.role || identity.role}
          reason={conn.reason}
          onConnect={connect}
        />
      </>
    );
  }

  async function subscribe(raw) {
    const p = raw.trim().toLowerCase();
    if (!p || /\s/.test(p)) return toast("A topic pattern is one word, e.g. brgy.san-roque.#", true);
    if (subs.includes(p)) return toast(`Already subscribed to ${p}`);
    // Add first: the broker's ERR can arrive before the send request returns.
    lastSub.current = p;
    setSubs((prev) => [...prev, p]);
    try {
      await conn.send(`SUB ${p}`);
      await conn.send("HISTORY");  // pull in reports filed before this subscription
      setPattern("");
      setCoverageOpen(false); // on phones, get the coverage panel out of the way of the feed
    } catch (err) {
      setSubs((prev) => prev.filter((x) => x !== p));
      toast(err.message, true);
    }
  }

  async function postAdvisory(e) {
    e.preventDefault();
    const typed = advForm.barangay.trim().toLowerCase();
    const barangay = barangayList().find((b) => b.name.toLowerCase() === typed || b.id === typed)?.id;
    const text = oneLine(advForm.text);
    const errs = {};
    if (!barangay) errs.barangay = typed ? "Not a barangay of Jaro. Pick one from the list." : "Pick the barangay this is for.";
    if (!text) errs.text = "Write the announcement.";
    setAdvErrors(errs);
    if (Object.keys(errs).length) return;
    const priority = advForm.urgent ? "URGENT" : "NORMAL";
    postingAdvisory.current = { barangay, description: text, priority, from: identity.id, from_role: identity.role };
    try {
      await conn.send(`ADVISORY ${barangay} ${priority} ${text}`);
    } catch (err) {
      postingAdvisory.current = null;
      toast(err.message, true);
    }
  }

  async function unsubscribe(p) {
    try {
      await conn.send(`UNSUB ${p}`);
      const remaining = subs.filter((x) => x !== p);
      setSubs(remaining);
      // Drop reports that only that subscription brought in.
      setReports((prev) => new Map([...prev].filter(([id, r]) => reportCovered(remaining, id, r))));
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function updateStatus(reportId, status, noteText) {
    const note = oneLine(noteText) || (status === "RESPONDING" ? "On the way" : "Resolved");
    // The card updates on the broker's UPDATED reply; a refusal arrives as ERR.
    sentNotes.current.set(reportId, note);
    try {
      await conn.send(`STATUS ${reportId} ${status} ${note}`);
    } catch (err) {
      sentNotes.current.delete(reportId);
      toast(err.message, true);
    }
  }

  const role = ROLES.find((r) => r.value === identity.role) || ROLES[0];
  const responding = visible.filter(([, r]) => r.status === "RESPONDING").length;

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
                  <Combobox id="pattern" placeholder={PATTERN_FOR[role.value]("san-roque")} value={pattern} onChange={setPattern}
                    options={barangayList()
                      .filter((b) => !accountBarangay || role.value !== "responder" || b.id === accountBarangay)
                      .map((b) => ({ value: b.id, label: b.name, text: PATTERN_FOR[role.value](b.id), hint: PATTERN_FOR[role.value](b.id) }))} />
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
                  {presetsFor(role.value, accountBarangay).map(({ pattern: p, label }) => (
                    <button key={p} type="button" className="preset" disabled={subs.includes(p)} onClick={() => subscribe(p)}>
                      <span>{label}</span>
                      <code>{p}</code>
                    </button>
                  ))}
                </div>
                </div>
              </section>

              <AdvisoryCard form={advForm} setForm={setAdvForm} errors={advErrors} advisories={advisories}
                onPost={postAdvisory} />
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
                  visible.length === 0 ? (
                    <EmptyState icon={Radio} title={subs.length ? "Listening for reports" : "No coverage yet"}>
                      {subs.length
                        ? "New reports for your topics will appear here as soon as residents send them."
                        : role.value === "desk" ? "Subscribe to escalations on the left, e.g. city.iloilo.escalated.#, to receive reports sent to the city." : "Subscribe to your barangay on the left, e.g. brgy.san-roque.#, to start receiving reports."}
                    </EmptyState>
                  ) : (
                    <EmptyState icon={Inbox} title="Nothing here">No reports match this filter.</EmptyState>
                  )
                ) : (
                  <ul className="reports">
                    {feed.map(([id, r]) => (
                      <IncidentCard key={id} id={id} report={r} role={identity.role} onStatus={updateStatus}
                        hidden={dismissed.has(id)} onDismiss={setHideAsk} onRestore={restore} />
                    ))}
                  </ul>
                )}
                {hiddenHere && (
                  <HiddenToggle count={hiddenList.length} open={showHidden} onToggle={() => setShowHidden((v) => !v)} />
                )}
              </div>
            </section>
          </div>

          <ProtocolLog entries={conn.log} />
          <ConfirmDialog open={hideAsk !== null} title="Hide this report?" confirmLabel="Hide report"
            icon={EyeOff} confirmIcon={EyeOff}
            onCancel={() => setHideAsk(null)}
            onConfirm={() => { dismiss(hideAsk); setHideAsk(null); }}>
            <p className="confirm-line"><CheckCircle2 size={16} /> <span>This report will be removed from this desk's lists on this browser. You can still find it in the Resolved tab.</span></p>
            <p className="confirm-line muted"><Database size={16} /> <span>It is <strong>not deleted</strong>: the report and its full history stay saved in eSumbong.</span></p>
          </ConfirmDialog>
        </div>
      </main>
    </>
  );
}

function IncidentCard({ id, report: r, role, onStatus, hidden, onDismiss, onRestore }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const status = r.status || "RECEIVED";
  const urgent = r.priority === "URGENT";
  const resolved = isClosed(status); // resolved or withdrawn: no more actions
  // Once escalated, the city desk owns the report: tanods may respond, not resolve.
  const canResolve = !r.escalated || role === "desk";
  const canRespond = status === "RECEIVED";

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
          {resolved && hidden && <span className="badge badge-neutral"><EyeOff size={12} /> Hidden</span>}
          {resolved && !hidden && (
            <button type="button" className="icon-btn" title="Hide from this desk" aria-label={`Hide report ${id}`}
              onClick={() => onDismiss(id)}>
              <X size={16} />
            </button>
          )}
          {resolved && hidden && (
            // Only seen in the Resolved tab: brings the report back to the other lists.
            <button type="button" className="btn btn-ghost btn-sm" title="Show in the other lists again"
              aria-label={`Unhide report ${id}`} onClick={() => onRestore(id)}>
              <Eye size={15} /> Unhide
            </button>
          )}
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
      {!resolved && (canRespond || canResolve) && (
        <div className="report-actions">
          <input className="input" placeholder="Add a note for the resident (optional)" maxLength={200}
            value={note} onChange={(e) => setNote(e.target.value)} aria-label={`Note for report ${id}`} />
          {canRespond && (
            <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => act("RESPONDING")}>
              <Truck size={15} /> Respond
            </button>
          )}
          {canResolve && (
            <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => act("RESOLVED")}>
              <CheckCircle2 size={15} /> Resolve
            </button>
          )}
        </div>
      )}
      {!resolved && !canResolve && (
        <p className="card-sub"><Building2 size={13} /> Escalated to the city. Only the city desk can resolve it.</p>
      )}
    </li>
  );
}

// Captains, tanods and the city desk post announcements to one barangay's
// residents (brgy.<barangay>.advisory); the latest few are listed below.
function AdvisoryCard({ form, setForm, errors, advisories, onPost }) {
  const set = (field) => (e) => {
    const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [field]: value }));
  };
  return (
    <section className="card card-pad" aria-labelledby="adv-title">
      <div className="card-head">
        <div>
          <h2 className="card-title" id="adv-title">Post an advisory</h2>
          <p className="card-sub">Residents following that barangay get it right away.</p>
        </div>
        <Megaphone size={18} className="muted" />
      </div>
      <form className="form-stack" onSubmit={onPost} noValidate>
        <label className="field">
          <span className="field-label">Barangay</span>
          <Combobox icon={MapPin} placeholder="Type or pick, e.g. San Roque" value={form.barangay}
            invalid={Boolean(errors.barangay)}
            onChange={(text) => setForm((f) => ({ ...f, barangay: text }))}
            options={barangayList().map((b) => ({ value: b.id, label: b.name }))} />
          {errors.barangay && <FieldError>{errors.barangay}</FieldError>}
        </label>
        <label className="field">
          <span className="field-label">Announcement</span>
          <textarea className="textarea" maxLength={300} aria-invalid={errors.text ? true : undefined}
            placeholder="e.g. Water interruption tomorrow, 1-5 PM" value={form.text} onChange={set("text")} />
          {errors.text && <FieldError>{errors.text}</FieldError>}
        </label>
        <label className="switch">
          <input type="checkbox" checked={form.urgent} onChange={set("urgent")} />
          <span className="switch-track" aria-hidden="true" />
          <span className="switch-text">
            <strong>Urgent</strong>
            <span>For warnings like floods or fires.</span>
          </span>
        </label>
        <button type="submit" className="btn btn-primary"><Send size={16} /> Send advisory</button>
      </form>
      {advisories.length > 0 && (
        <ul className="advisories advisory-recent" aria-label="Recent advisories">
          {advisories.map((a) => (
            <li key={a.advisory_id} className={`advisory${a.priority === "URGENT" ? " is-urgent" : ""}`}>
              {a.priority === "URGENT" ? <Siren size={18} /> : <Megaphone size={18} />}
              <div>
                <p>{a.description}</p>
                <small>{a.from ? advisorySender(a) : barangayName(a.barangay)} · {clockTime(a.time)}</small>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
