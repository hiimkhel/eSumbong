import { useEffect, useRef } from "react";

export default function ProtocolLog({ entries }) {
  const ref = useRef(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [entries]);

  return (
    <section className="card">
      <h2>Protocol log</h2>
      <div ref={ref} className="log">
        {entries.map((e) => `${e.time} ${e.direction} ${e.line}`).join("\n")}
      </div>
    </section>
  );
}
