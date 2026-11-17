// Responder / desk page: subscribe to topics, receive reports, publish STATUS updates.

(() => {
  const { Connection, oneLine, toast, setConnState, el, appendLog } = Sumbong;
  const $ = (id) => document.getElementById(id);

  const reports = new Map();  // report_id -> latest body + { priority, topic, receivedAt }
  const subs = new Set();
  let lastCommand = null;
  let lastSubPattern = null;  // so an ERR right after SUB can roll it back

  const conn = new Connection({
    onLine: handleLine,
    onState: (state, reason) => {
      setConnState($("conn"), state, reason);
      const online = state === "online";
      $("connect-btn").disabled = online;
      $("disconnect-btn").disabled = !online;
      $("sub-btn").disabled = !online;
      $("client-id").disabled = online;
      $("role").disabled = online;
      if (!online) {
        subs.clear();
        renderSubs();
        if (reason) toast(reason, true);
      }
      renderFeed();
    },
  });

  async function send(line) {
    lastCommand = line.split(" ", 1)[0];
    appendLog($("log"), "→", line);
    await conn.send(line);
  }

  function handleLine(event) {
    appendLog($("log"), "←", event.raw);
    if (event.command === "MSG") {
      const body = event.body;
      if (!body || !body.report_id) return;
      const existing = reports.get(body.report_id);
      const isNew = !existing;
      reports.set(body.report_id, {
        ...existing,
        ...body,
        priority: body.priority || event.priority,
        lastTopic: event.topic,
        receivedAt: existing?.receivedAt || Date.now(),
      });
      if (isNew && (body.priority || event.priority) === "URGENT") toast(`URGENT: ${body.category} at ${body.topic}`, true);
      renderFeed();
    } else if (event.command === "ERR") {
      toast(`Broker error: ${event.reason}`, true);
      if (lastCommand === "SUB" && lastSubPattern) {
        subs.delete(lastSubPattern);
        lastSubPattern = null;
        renderSubs();
      }
    }
  }

  async function updateStatus(reportId, status, noteInput) {
    const note = oneLine(noteInput.value) || (status === "RESPONDING" ? "On the way" : "Resolved");
    try {
      await send(`STATUS ${reportId} ${status} ${note}`);
      const r = reports.get(reportId);
      if (r) {
        r.status = status;
        r.note = note;
      }
      renderFeed();
    } catch (err) {
      toast(err.message, true);
    }
  }

  function renderSubs() {
    const list = $("subs");
    list.replaceChildren(...[...subs].map((pattern) =>
      el("li", { class: "row", style: "align-items:center" },
        el("code", {}, pattern),
        el("span", { style: "flex:0 0 auto" },
          el("button", {
            class: "small secondary",
            type: "button",
            onclick: async () => {
              try {
                await send(`UNSUB ${pattern}`);
                subs.delete(pattern);
                renderSubs();
              } catch (err) { toast(err.message, true); }
            },
          }, "Unsubscribe")),
      )));
  }

  function renderFeed() {
    const urgentOnly = $("urgent-only").checked;
    const hideResolved = $("hide-resolved").checked;
    const items = [...reports.entries()]
      .filter(([, r]) => !urgentOnly || r.priority === "URGENT")
      .filter(([, r]) => !hideResolved || r.status !== "RESOLVED")
      .sort(([, a], [, b]) =>
        (a.priority === "URGENT" ? 0 : 1) - (b.priority === "URGENT" ? 0 : 1) || b.receivedAt - a.receivedAt);

    $("feed-empty").hidden = items.length > 0;
    $("feed").replaceChildren(...items.map(([id, r]) => {
      const note = el("input", { placeholder: "Note (optional)", maxlength: "200" });
      const status = r.status || "RECEIVED";
      const disabled = !conn.connected;
      const respondBtn = el("button", { class: "small", type: "button", onclick: () => updateStatus(id, "RESPONDING", note) }, "Responding");
      const resolveBtn = el("button", { class: "small secondary", type: "button", onclick: () => updateStatus(id, "RESOLVED", note) }, "Resolved");
      respondBtn.disabled = disabled || status !== "RECEIVED";
      resolveBtn.disabled = disabled || status === "RESOLVED";
      return el("li", { class: r.priority === "URGENT" ? "urgent" : "" },
        el("div", { class: "row", style: "align-items:center" },
          el("strong", { style: "flex:0 0 auto" }, r.category || "report"),
          el("span", { style: "flex:0 0 auto" }, el("span", { class: `pill ${status.toLowerCase()}` }, status)),
          r.priority === "URGENT" ? el("span", { style: "flex:0 0 auto" }, el("span", { class: "pill urgent" }, "URGENT")) : null,
          r.escalated ? el("span", { style: "flex:0 0 auto" }, el("span", { class: "pill escalated" }, "ESCALATED")) : null,
        ),
        el("p", { style: "margin:.4rem 0" }, r.description || ""),
        el("p", { class: "meta" },
          `#${id} · ${r.topic || r.lastTopic} · ${r.reporter ? `reported by ${r.reporter}` : "anonymous"} · ${new Date(r.receivedAt).toLocaleTimeString()}`),
        r.note ? el("p", { class: "meta" }, `Last note: ${r.note}`) : null,
        status === "RESOLVED" ? null : el("div", { class: "row", style: "margin-top:.5rem" }, note,
          el("span", { style: "flex:0 0 auto" }, respondBtn),
          el("span", { style: "flex:0 0 auto" }, resolveBtn)),
      );
    }));
  }

  $("connect-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = $("client-id").value.trim();
    const role = $("role").value;
    try {
      await conn.connect(id, role);
      appendLog($("log"), "→", `HELLO ${id} ${role}`);
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("disconnect-btn").addEventListener("click", () => conn.disconnect());

  $("sub-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pattern = $("pattern").value.trim().toLowerCase();
    if (!pattern || /\s/.test(pattern)) return toast("Pattern must be one word, e.g. brgy.jaro.#", true);
    if (subs.has(pattern)) return toast(`Already subscribed to ${pattern}`);
    try {
      await send(`SUB ${pattern}`);
      subs.add(pattern);
      renderSubs();
      $("pattern").value = "";
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("urgent-only").addEventListener("change", renderFeed);
  $("hide-resolved").addEventListener("change", renderFeed);
  window.addEventListener("beforeunload", () => conn.disconnect());

  renderFeed();
})();
