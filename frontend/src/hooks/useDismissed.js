import { useCallback, useState } from "react";
import { storageGet, storageSet } from "../lib/sumbong.js";

const MAX_REMEMBERED = 500;

// Resolved reports this browser chose to hide, per page and signed-in ID.
// Only the screen forgets them: the broker keeps every report.
export function useDismissed(page, clientId) {
  const key = `esumbong.dismissed.${page}.${clientId}`;
  const [state, setState] = useState({ key: null, ids: new Set() });

  // Load the list for whoever is signed in (and again if the ID changes).
  let { ids } = state;
  if (clientId && state.key !== key) {
    ids = new Set(storageGet("localStorage", key) || []);
    setState({ key, ids });
  }

  const dismiss = useCallback((reportId) => {
    setState((prev) => {
      const next = new Set(prev.ids).add(reportId);
      storageSet("localStorage", key, [...next].slice(-MAX_REMEMBERED));
      return { key, ids: next };
    });
  }, [key]);

  const restore = useCallback((reportId) => {
    setState((prev) => {
      const next = new Set(prev.ids);
      next.delete(reportId);
      storageSet("localStorage", key, [...next]);
      return { key, ids: next };
    });
  }, [key]);

  return [ids, dismiss, restore];
}
