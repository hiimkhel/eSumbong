import { useCallback, useEffect, useRef, useState } from "react";
import { Connection } from "../lib/sumbong.js";

const MAX_LOG_LINES = 500;

// One broker session for the page that uses it, plus its protocol log.
// onEvent(event) gets every parsed broker line; onState(state, reason) every change.
export function useConnection({ onEvent, onState }) {
  const [state, setState] = useState({ status: "offline", reason: "" });
  const [log, setLog] = useState([]);
  const lastCommand = useRef(null);
  const handlers = useRef({ onEvent, onState });
  handlers.current = { onEvent, onState };

  const appendLog = useCallback((direction, line) => {
    const entry = { time: new Date().toLocaleTimeString(), direction, line };
    setLog((prev) => [...prev, entry].slice(-MAX_LOG_LINES));
  }, []);

  const connRef = useRef(null);
  if (!connRef.current) {
    connRef.current = new Connection({
      onLine: (event) => {
        appendLog("←", event.raw);
        handlers.current.onEvent?.(event);
      },
      onState: (status, reason = "") => {
        setState({ status, reason });
        handlers.current.onState?.(status, reason);
      },
    });
  }
  const conn = connRef.current;

  useEffect(() => {
    const close = () => { conn.disconnect(); };
    window.addEventListener("beforeunload", close);
    return () => {
      window.removeEventListener("beforeunload", close);
      close();
    };
  }, [conn]);

  const connect = useCallback(async (clientId, role) => {
    await conn.connect(clientId, role);
    appendLog("→", `HELLO ${clientId} ${role}`);
  }, [conn, appendLog]);

  const disconnect = useCallback(() => conn.disconnect(), [conn]);

  const send = useCallback(async (line) => {
    lastCommand.current = line.split(" ", 1)[0];
    appendLog("→", line);
    await conn.send(line);
  }, [conn, appendLog]);

  return {
    online: state.status === "online",
    status: state.status,
    reason: state.reason,
    log,
    lastCommand,
    connect,
    disconnect,
    send,
  };
}
