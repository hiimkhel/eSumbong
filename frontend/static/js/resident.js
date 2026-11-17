// Resident page: file reports and follow their status (report.<id>.status).

(() => {
  const { Connection, loadConfig, oneLine, topicLevel, toast, setConnState, el, appendLog } = Sumbong;
  const $ = (id) => document.getElementById(id);

  const reports = new Map();   // report_id -> { topic, category, description, anonymous, status, escalated, note }
  const pending = [];          // reports sent, waiting for REPORTED (broker answers in order)
  const advisories = [];
  let lastCommand = null;
  let followedAdvisory = null;
  let cfg = { categories: [], urgent_categories: [] };

  const conn = new Connection({
    onLine: handleLine,
    onState: (state, reason) => {
      setConnState($("conn"), state, reason);
      const online = state === "online";
      $("connect-btn").disabled = online;
      $("disconnect-btn").disabled = !online;
      $("report-btn").disabled = !online;
      $("advisory-btn").disabled = !online;
      $("client-id").disabled = online;
      if (!online) {
        followedAdvisory = null;
        if (reason) toast(reason, true);
      }
    },
  });

  async function send(line) {
    lastCommand = line.split(" ", 1)[0];
    appendLog($("log"), "→", line);
    await conn.send(line);
  }

  function handleLine(event) {
    appendLog($("log"), "←", event.raw);
    switch (event.command) {
      case "REPORTED": {
        const report = pending.shift();
        if (!report) return;
        reports.set(event.reportId, { ...report, status: "RECEIVED", escalated: false });
        toast(`Report ${event.reportId} received`);
        renderReports();
        break;
      }
      case "MSG": {
        const body = event.body || {};
        if (/^report\.[^.]+\.status$/.test(event.topic) && body.report_id) {
          const existing = reports.get(body.report_id) || {};
          reports.set(body.report_id, {
            ...existing,
            topic: existing.topic || body.topic,
            category: existing.category || body.category,
            description: existing.description || body.description,
            status: body.status || existing.status,
            escalated: Boolean(body.escalated),
            note: body.note || existing.note,
          });
          renderReports();
          toast(`Report ${body.report_id}: ${body.status}`);
        } else {
          advisories.unshift({ topic: event.topic, priority: event.priority, body, time: new Date() });
          renderAdvisories();
        }
        break;
      }
      case "ERR":
        if (lastCommand === "REPORT" && pending.length) pending.shift();
        toast(`Broker error: ${event.reason}`, true);
        break;
    }
  }

  function currentTopic() {
    const parts = [$("barangay").value, $("purok").value, $("category").value].map(topicLevel);
    return parts.every(Boolean) ? `brgy.${parts.join(".")}` : null;
  }

  function renderReports() {
    const list = $("reports");
    list.replaceChildren();
    const entries = [...reports.entries()].reverse();
    $("reports-empty").hidden = entries.length > 0;
    for (const [id, r] of entries) {
      const urgent = cfg.urgent_categories.includes(r.category);
      list.append(el("li", { class: urgent ? "urgent" : "" },
        el("div", { class: "row" },
          el("strong", {}, r.category || "report"),
          el("span", {}, el("span", { class: `pill ${(r.status || "").toLowerCase()}` }, r.status || "RECEIVED")),
          urgent ? el("span", {}, el("span", { class: "pill urgent" }, "URGENT")) : null,
          r.escalated ? el("span", {}, el("span", { class: "pill escalated" }, "ESCALATED")) : null,
        ),
        el("p", { style: "margin:.4rem 0" }, r.description || ""),
        r.note ? el("p", { class: "meta" }, `Responder note: ${r.note}`) : null,
        el("p", { class: "meta" }, `#${id} · ${r.topic || ""}${r.anonymous ? " · anonymous" : ""}`),
      ));
    }
  }

  function renderAdvisories() {
    const list = $("advisories");
    list.replaceChildren();
    $("advisories-empty").hidden = advisories.length > 0;
    for (const a of advisories) {
      list.append(el("li", { class: a.priority === "URGENT" ? "urgent" : "" },
        el("p", { style: "margin:0" }, a.body?.description || JSON.stringify(a.body)),
        el("p", { class: "meta" }, `${a.topic} · ${a.time.toLocaleTimeString()}`),
      ));
    }
  }

  $("connect-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = $("client-id").value.trim();
    try {
      await conn.connect(id, "resident");
      appendLog($("log"), "→", `HELLO ${id} resident`);
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("disconnect-btn").addEventListener("click", () => conn.disconnect());

  $("report-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const topic = currentTopic();
    const description = oneLine($("description").value);
    if (!topic || !description) return toast("Fill in barangay, purok, category, and description", true);
    const anonymous = $("anonymous").checked;
    const report = { topic, category: $("category").value, description, anonymous };
    pending.push(report);
    try {
      await send(`REPORT ${topic} ${anonymous ? "Y" : "N"} ${description}`);
      $("description").value = "";
    } catch (err) {
      pending.pop();
      toast(err.message, true);
    }
  });

  $("advisory-btn").addEventListener("click", async () => {
    const barangay = topicLevel($("barangay").value);
    if (!barangay) return toast("Enter your barangay first", true);
    const topic = `brgy.${barangay}.advisory`;
    if (followedAdvisory === topic) return toast(`Already following ${topic}`);
    try {
      if (followedAdvisory) await send(`UNSUB ${followedAdvisory}`);
      await send(`SUB ${topic}`);
      followedAdvisory = topic;
      toast(`Following ${topic}`);
    } catch (err) {
      toast(err.message, true);
    }
  });

  for (const id of ["barangay", "purok", "category"]) {
    $(id).addEventListener("input", () => { $("topic-preview").textContent = currentTopic() || "—"; });
  }

  window.addEventListener("beforeunload", () => conn.disconnect());

  loadConfig()
    .then((c) => {
      cfg = c;
      $("category").replaceChildren(...c.categories.map((name) =>
        el("option", { value: name }, c.urgent_categories.includes(name) ? `${name} (urgent)` : name)));
      $("topic-preview").textContent = currentTopic() || "—";
    })
    .catch((err) => toast(err.message, true));
})();
