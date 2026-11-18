import { useState } from "react";
import { AlertCircle, ArrowRight, User } from "lucide-react";
import { FieldError, LogoMark } from "./ui.jsx";

// Shown instead of the page until the browser has a broker session.
// roles: optional [{ value, label, hint, icon }] to pick from. onConnect(id, role) may throw.
export default function SignIn({ title, lead, foot, placeholder, roles, defaultId, defaultRole, reason, onConnect }) {
  const [id, setId] = useState(defaultId || "");
  const [role, setRole] = useState(defaultRole || roles?.[0]?.value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    const value = id.trim();
    const problem = !value ? "Enter an ID so you can follow your reports."
      : /\s/.test(value) ? "Use one word with no spaces, e.g. juan-dc."
      : "";
    setError(problem);
    if (problem) return e.currentTarget.querySelector("input")?.focus();
    setBusy(true);
    try {
      await onConnect(id.trim(), role);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="signin-wrap">
      <section className="card signin" aria-labelledby="signin-title">
        <span className="signin-mark"><LogoMark size={40} /></span>
        <h1 id="signin-title">{title}</h1>
        <p>{lead}</p>
        <form onSubmit={submit} noValidate>
          {reason && (
            <div className="signin-alert" role="alert">
              <AlertCircle size={16} /> {reason}. Sign in again to reconnect.
            </div>
          )}
          {roles && (
            <div className="field">
              <span className="field-label" id="role-label">I am signing in as</span>
              <div className="choice-group" role="radiogroup" aria-labelledby="role-label">
                {roles.map(({ value, label, hint, icon: Icon }) => (
                  <button key={value} type="button" role="radio" aria-checked={role === value}
                    className="choice" onClick={() => setRole(value)}>
                    <Icon size={20} />
                    <strong>{label}</strong>
                    <span>{hint}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          <label className="field">
            <span className="field-label">Your ID</span>
            <span className="input-icon">
              <User size={17} />
              <input className="input" required maxLength={64} pattern="\S+" autoFocus
                placeholder={placeholder} value={id} aria-invalid={error ? true : undefined}
                onChange={(e) => { setId(e.target.value); setError(""); }} />
            </span>
            {error
              ? <FieldError>{error}</FieldError>
              : <span className="field-hint">One word, no spaces. Use the same ID to see your reports again.</span>}
          </label>
          <button type="submit" className="btn btn-primary btn-lg btn-block" disabled={busy}>
            {busy ? "Connecting…" : "Continue"} {!busy && <ArrowRight size={18} />}
          </button>
        </form>
        {foot && <p className="signin-foot">{foot}</p>}
      </section>
    </div>
  );
}
