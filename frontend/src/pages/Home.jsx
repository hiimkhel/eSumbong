import { ArrowRight, BellRing, CheckCircle2, ChevronsUp, Clock, EyeOff, Megaphone, ShieldCheck, Zap } from "lucide-react";
import AppBar from "../components/AppBar.jsx";
import PhoneMockup from "../components/PhoneMockup.jsx";

export default function Home() {
  return (
    <>
      <AppBar />

      <section className="hero pattern">
        <div className="container hero-grid">
          <div className="hero-copy">
            <span className="eyebrow">Barangay incident reporting · Iloilo City</span>
            <h1>May <em>sumbong</em> ka?</h1>
            <p className="hero-lead">
              Report noise, fights, fires and floods straight to your barangay. Every report rises
              until it is resolved, and you can follow it the whole way.
            </p>
            <div className="hero-cta">
              <a href="#/resident" className="btn btn-amber btn-lg">
                <Megaphone size={18} /> Report an incident
              </a>
              <a href="#/responder" className="btn btn-on-dark btn-lg">
                <ShieldCheck size={18} /> Responder desk
              </a>
            </div>
            <div className="hero-proof">
              <span><Zap size={16} /> Urgent reports first</span>
              <span><EyeOff size={16} /> Anonymous option</span>
              <span><Clock size={16} /> Escalates if unanswered</span>
            </div>
          </div>

          <PhoneMockup />
        </div>
      </section>

      <section className="roles-section" aria-labelledby="roles-title">
        <div className="container">
        <div className="section-head">
          <span className="eyebrow">Get started</span>
          <h2 id="roles-title">How will you use eSumbong?</h2>
        </div>
        <div className="roles">
          <a href="#/resident" className="card role-card">
            <span className="role-icon"><Megaphone size={24} /></span>
            <h3>I'm a resident</h3>
            <p>Tell your barangay what's happening in your purok and see when help is on the way.</p>
            <ul className="role-list">
              <li><CheckCircle2 size={16} /> File a report in under a minute</li>
              <li><CheckCircle2 size={16} /> Follow it from received to resolved</li>
              <li><CheckCircle2 size={16} /> Get barangay advisories</li>
            </ul>
            <span className="role-go">Report an incident <ArrowRight size={16} /></span>
          </a>
          <a href="#/responder" className="card role-card alt">
            <span className="role-icon"><ShieldCheck size={24} /></span>
            <h3>I'm a responder</h3>
            <p>For tanods, barangay captains and the city desk: see reports as they come in and act on them.</p>
            <ul className="role-list">
              <li><CheckCircle2 size={16} /> Live feed, urgent reports first</li>
              <li><CheckCircle2 size={16} /> Mark reports responding or resolved</li>
              <li><CheckCircle2 size={16} /> City desk sees escalations</li>
            </ul>
            <span className="role-go">Open the desk <ArrowRight size={16} /></span>
          </a>
        </div>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <div className="section-head">
            <span className="eyebrow">How it works</span>
            <h2>Every report rises until it is resolved</h2>
            <p>eSumbong routes each report to the people responsible for that purok, and keeps it moving.</p>
          </div>
          <div className="steps">
            <article className="card step">
              <span className="step-num"><Megaphone size={20} /></span>
              <h3>1. You report</h3>
              <p>Pick a category and describe what happened. It's published to your purok, like <code>brgy.jaro.purok-3.fire</code>.</p>
            </article>
            <article className="card step">
              <span className="step-num"><ChevronsUp size={20} /></span>
              <h3>2. It rises</h3>
              <p>Tanods subscribed to your barangay get it instantly. If no one responds in time, it escalates to the city desk.</p>
            </article>
            <article className="card step">
              <span className="step-num"><BellRing size={20} /></span>
              <h3>3. You're kept posted</h3>
              <p>Each status change, from responding to resolved, comes back to you with the responder's note.</p>
            </article>
          </div>
        </div>
      </section>

      <footer className="footer">
        <div className="container">
          <span>eSumbong · A publish-subscribe barangay incident reporting system</span>
          <span>Iloilo City</span>
        </div>
      </footer>
    </>
  );
}
