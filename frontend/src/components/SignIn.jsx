import { useState } from "react";
import { AlertCircle, ArrowRight, KeyRound, User } from "lucide-react";
import { FieldError, LogoMark } from "./ui.jsx";

// Shown instead of the page until the browser has a broker session.
// roles: optional [{ value, label, hint, icon, secretLabel?, fixedId? }] to pick from.
//   secretLabel: the role signs in with a PIN/password (e.g. "PIN"), asked for here
//   and never stored; fixedId: the role has one account, so no ID is asked (the desk).
// onConnect(id, role, secret) may throw; its message is shown (e.g. a wrong PIN).
export default function SignIn({ title, lead, foot, placeholder, roles, defaultId, defaultRole, reason, onConnect }) {
  const [id, setId] = useState(defaultId || "");
  const [role, setRole] = useState(defaultRole || roles?.[0]?.value);
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState({});
  const [failure, setFailure] = useState("");

  const current = roles?.find((r) => r.value === role) || {};
  const needsId = !current.fixedId;
  const secretLabel = current.secretLabel;
  // "PIN" stays as it is; "Desk password" reads "desk password" mid-sentence.
  const secretNoun = secretLabel && (/^[A-Z]+$/.test(secretLabel) ? secretLabel : secretLabel.toLowerCase());

  async function submit(e) {
    e.preventDefault();
    const value = id.trim();
    const errs = {};
    if (needsId) {
      if (!value) errs.id = "Enter an ID so you can follow your reports.";
      else if (/\s/.test(value)) errs.id = "Use one word with no spaces, e.g. juan-dc.";
    }
    if (secretLabel) {
      if (!secret) errs.secret = `Enter your ${secretNoun}.`;
      else if (/\s/.test(secret)) errs.secret = `Your ${secretNoun} has no spaces.`;
    }
    setErrors(errs);
    setFailure("");
    const first = Object.keys(errs)[0];
    if (first) return e.currentTarget.querySelector(`[data-field="${first}"]`)?.focus();
    setBusy(true);
    try {
      await onConnect(needsId ? value : current.fixedId, role, secretLabel ? secret : undefined);
    } catch (err) {
      setFailure(err.message || "Couldn't sign in");
      setSecret("");
    } finally {
      setBusy(false);
    }
  }

  function pickRole(value) {
    setRole(value);
    setSecret("");
    setErrors({});
    setFailure("");
  }

  return (
    <div className="signin-wrap">
      <section className="card signin" aria-labelledby="signin-title">
        <span className="signin-mark"><LogoMark size={40} /></span>
        <h1 id="signin-title">{title}</h1>
        <p>{lead}</p>
        <form onSubmit={submit} noValidate>
          {(failure || reason) && (
            <div className="signin-alert" role="alert">
              <AlertCircle size={16} /> {failure ? `Couldn't sign in: ${failure}.` : `${reason}. Sign in again to reconnect.`}
            </div>
          )}
          {roles && (
            <div className="field">
              <span className="field-label" id="role-label">I am signing in as</span>
              <div className="choice-group" role="radiogroup" aria-labelledby="role-label">
                {roles.map(({ value, label, hint, icon: Icon }) => (
                  <button key={value} type="button" role="radio" aria-checked={role === value}
                    className="choice" onClick={() => pickRole(value)}>
                    <Icon size={20} />
                    <strong>{label}</strong>
                    <span>{hint}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {needsId && (
            <label className="field">
              <span className="field-label">Your ID</span>
              <span className="input-icon">
                <User size={17} />
                <input className="input" data-field="id" required maxLength={64} pattern="\S+" autoFocus
                  autoComplete="username" placeholder={placeholder} value={id}
                  aria-invalid={errors.id ? true : undefined}
                  onChange={(e) => { setId(e.target.value); setErrors((x) => ({ ...x, id: undefined })); }} />
              </span>
              {errors.id
                ? <FieldError>{errors.id}</FieldError>
                : <span className="field-hint">One word, no spaces. Use the same ID to see your reports again.</span>}
            </label>
          )}
          {secretLabel && (
            <label className="field">
              <span className="field-label">{secretLabel}</span>
              <span className="input-icon">
                <KeyRound size={17} />
                <input className="input" data-field="secret" type="password" required maxLength={64}
                  autoComplete="current-password" autoFocus={!needsId} value={secret}
                  aria-invalid={errors.secret ? true : undefined}
                  onChange={(e) => { setSecret(e.target.value); setErrors((x) => ({ ...x, secret: undefined })); }} />
              </span>
              {errors.secret
                ? <FieldError>{errors.secret}</FieldError>
                : <span className="field-hint">
                  {current.fixedId ? "The one city desk account. Ask your admin if you don't have the password." : "Given to you by your barangay captain."}
                </span>}
            </label>
          )}
          <button type="submit" className="btn btn-primary btn-lg btn-block" disabled={busy}>
            {busy ? "Connecting…" : "Continue"} {!busy && <ArrowRight size={18} />}
          </button>
        </form>
        {foot && <p className="signin-foot">{foot}</p>}
      </section>
    </div>
  );
}
