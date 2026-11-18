import {
  BatteryFull, Construction, Home, MapPin, Megaphone, MessageSquare, ShieldCheck, Signal, Volume2, Wifi, Wine,
} from "lucide-react";
import { LogoMark } from "./ui.jsx";

// Decorative phone for the landing hero: shows the resident app as it really looks.
export default function PhoneMockup() {
  return (
    <div className="device-stage" aria-hidden="true">
      <div className="device-glow" />
      <div className="device-shadow" />

      <div className="device-float">
      <div className="device">
        <span className="device-btn action" />
        <span className="device-btn vol-up" />
        <span className="device-btn vol-down" />
        <span className="device-btn power" />

        <div className="device-screen">
          <span className="device-island" />
          <div className="device-status">
            <span>9:41</span>
            <span className="device-status-icons">
              <Signal size={14} strokeWidth={2.6} />
              <Wifi size={14} strokeWidth={2.6} />
              <BatteryFull size={20} strokeWidth={2} />
            </span>
          </div>

          {/* iOS-style notification banner, dropped over the app header */}
          <div className="device-push">
            <span className="push-icon"><LogoMark size={34} /></span>
            <span className="push-text">
              <span className="push-top"><b>eSumbong</b><small>now</small></span>
              <b>A tanod is responding</b>
              <span>Your noise report in Purok 3 is being handled.</span>
            </span>
          </div>

          <div className="app-head">
            <span className="brand-mini"><LogoMark size={22} variant="light" /><span><span className="e">e</span>Sumbong</span></span>
            <span className="app-avatar">JD</span>
          </div>

          <div className="app-body">
            <span className="app-place"><MapPin size={11} /> Brgy. San Roque · Purok 3</span>
            <span className="app-title">May sumbong ka?</span>
            <span className="app-cta"><Megaphone size={14} /> Report an incident</span>

            <div className="app-section"><strong>Your reports</strong><span>See all</span></div>

            <div className="app-card">
              <div className="app-card-row">
                <span className="app-tile"><Volume2 size={15} /></span>
                <span className="app-card-text"><b>Noise</b><small>Purok 3 · 9:12 PM</small></span>
                <span className="app-badge resp">Responding</span>
              </div>
              <div className="app-progress"><i className="on" /><i className="on" /><i /></div>
              <span className="app-note"><MessageSquare size={11} /> Tanod Reyes is on the way</span>
            </div>

            <div className="app-card">
              <div className="app-card-row">
                <span className="app-tile"><Wine size={15} /></span>
                <span className="app-card-text"><b>Public drinking</b><small>Purok 3 · 8:40 PM</small></span>
                <span className="app-badge esc">Escalated</span>
              </div>
            </div>

            <div className="app-card">
              <div className="app-card-row">
                <span className="app-tile"><Construction size={15} /></span>
                <span className="app-card-text"><b>Road hazard</b><small>Purok 3 · Yesterday</small></span>
                <span className="app-badge res">Resolved</span>
              </div>
            </div>

            <div className="app-advisory">
              <Megaphone size={14} />
              <span><b>Barangay advisory</b>Clean-up drive this Saturday, 7 AM at the plaza.</span>
            </div>
          </div>

          <div className="app-tabbar">
            <span><Home size={17} />Home</span>
            <span className="on"><Megaphone size={17} />Report</span>
            <span><ShieldCheck size={17} />Desk</span>
          </div>
          <div className="app-home-indicator" />
        </div>
      </div>
      </div>
    </div>
  );
}
