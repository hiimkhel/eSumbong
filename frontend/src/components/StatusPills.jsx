export default function StatusPills({ status = "RECEIVED", urgent, escalated }) {
  return (
    <>
      <span className={`pill ${status.toLowerCase()}`}>{status}</span>
      {urgent && <span className="pill urgent">URGENT</span>}
      {escalated && <span className="pill escalated">ESCALATED</span>}
    </>
  );
}
