import { useEffect, useRef } from "react";
import { ChevronDown, Terminal } from "lucide-react";

// Collapsible view of the raw protocol lines, for demos and debugging.
export default function ProtocolLog({ entries }) {
  const ref = useRef(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [entries]);

  return (
    <details className="devlog">
      <summary>
        <Terminal size={16} /> Protocol log
        <span className="badge badge-neutral">{entries.length}</span>
        <ChevronDown size={16} className="chev" />
      </summary>
      <pre ref={ref}>
        {entries.length === 0 && "Nothing sent yet."}
        {entries.map((e, i) => (
          <div key={i}>
            <span className="muted">{e.time} </span>
            <span className={e.direction === "→" ? "out" : "in"}>{e.direction}</span> {e.line}
          </div>
        ))}
      </pre>
    </details>
  );
}
