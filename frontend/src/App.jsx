import { useEffect, useState } from "react";
import { setBarangays } from "./lib/format.js";
import { loadConfig } from "./lib/sumbong.js";
import Home from "./pages/Home.jsx";
import Resident from "./pages/Resident.jsx";
import Responder from "./pages/Responder.jsx";

// Hash routes (#/resident, #/responder) so the gateway only ever serves index.html.
const ROUTES = {
  "": { page: Home, title: "eSumbong" },
  resident: { page: Resident, title: "eSumbong · Resident" },
  responder: { page: Responder, title: "eSumbong · Responder" },
};

function currentRoute() {
  return window.location.hash.replace(/^#\/?/, "");
}

export default function App() {
  const [route, setRoute] = useState(currentRoute);
  const [, setNamesLoaded] = useState(false);

  // Barangay display names for every page ("M.H. del Pilar", not "Mh Del Pilar").
  useEffect(() => {
    loadConfig()
      .then((c) => { setBarangays(c.barangays); setNamesLoaded(true); })
      .catch(() => { /* pages fall back to title case */ });
  }, []);

  useEffect(() => {
    const onChange = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const { page: Page, title } = ROUTES[route] || ROUTES[""];

  useEffect(() => {
    document.title = title;
  }, [title]);

  // key: leaving a page unmounts it, which closes its broker session.
  return <Page key={route} />;
}
