/* Claude Skills Team OS demo page.
   A short guided story (six steps, one action each), then free chat. The server keeps nothing:
   this page holds the chat (the "session", signed by the server) and sends it with every request.
   See teamos/session.py. */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const S = {
    config: null, session: null, view: null, live: true, busy: false, step: 0, wait: "", story: {},
    pane: "broker", hoodOpen: false, logOpen: true, logAll: false, keyboard: false,
  };
  // People read skill names, not file names. The file names stay under Under the hood.
  const LABELS = { "house-rules": "House rules", "voice-note-debrief": "Voice note debrief", "crm-update": "CRM update",
    "meeting-prep": "Meeting prep", "follow-up-email": "Follow up email", "weekly-pipeline": "Weekly pipeline" };
  const label = (name) => LABELS[name] || name;
  const NUMBER = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight"];
  const count = (n, thing) => `${NUMBER[n] || n} ${thing}${n === 1 ? "" : "s"}`;
  const icon = (name, cls = "i") => `<svg class="${cls}" aria-hidden="true" focusable="false"><use href="#${name}"/></svg>`;
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function format(text) {
    const lines = esc(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").split("\n");
    let html = "", list = false;
    for (const line of lines) {
      const item = line.match(/^\s*[-•*]\s+(.*)$/);
      if (item) { if (!list) { html += "<ul>"; list = true; } html += `<li>${item[1]}</li>`; continue; }
      if (list) { html += "</ul>"; list = false; }
      html += line + "<br>";
    }
    if (list) html += "</ul>";
    return html.replace(/(<br>)+$/, "").replace(/<br>(<ul>)/g, "$1");
  }
  const money = (n) => "$" + Number(n || 0).toFixed(4);
  const isPhone = () => window.matchMedia("(max-width: 900px)").matches;
  // One time format everywhere: the CRM's clock in the visitor's own time zone, 12 hour, no seconds.
  const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : "");
  const day = (iso) => (iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "");
  const store = {
    get(k) { try { return JSON.parse(sessionStorage.getItem(k)); } catch { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode: fine */ } },
  };
  let toastTimer = null;
  function toast(msg, ms = 4200) {
    const el = $("#toast"); el.textContent = msg; el.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, ms);
  }
  let announceText = "", announceTimer = null;
  function announce(msg) {  // messages that arrive together are read together
    const el = $("#announce");
    announceText = announceText ? announceText + " " + msg : msg;
    el.textContent = ""; clearTimeout(announceTimer);
    announceTimer = setTimeout(() => { el.textContent = announceText; announceText = ""; }, 60);
  }
  async function post(path, body) {
    const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { const err = new Error(data.message || "Something went wrong."); err.kind = data.error; throw err; }
    return data;
  }
  function save() { store.set("teamos-demo", { session: S.session, step: S.step, story: S.story }); }
  const brokerName = () => S.view?.broker?.name || "Priya Natarajan";
  const brokerFirst = () => brokerName().split(" ")[0];

  // ------------------------------------------------------------------ talking to the server
  async function newChat(broker) {
    const data = await post("/api/new", broker ? { broker } : {});
    S.session = data.session; S.view = data.view;
    save(); render();
  }
  async function step(action) {
    let data;
    try {
      data = await post("/api/step", { session: S.session, action, live: S.live });
    } catch (err) {
      if (err.kind === "session") { await newChat(); toast("That chat could not be continued, so a new one started."); return null; }
      throw err;
    }
    S.session = data.session; S.view = data.view;
    save(); render();
    return data;
  }
  async function send(text) {
    text = text.trim();
    if (!text || S.busy) return false;
    setBusy(true);
    S.wait = S.live && S.config?.live ? "Claude is on it. Real AI, usually 5 to 15 seconds." : "Working on it.";
    renderStory();
    showPending(text);
    try {
      let data = await step({ type: "broker", text });
      let guard = 0;
      while (data && data.more && guard++ < 12) {
        const working = data.view.transcript[data.view.transcript.length - 1];
        const last = working && working.steps && working.steps[working.steps.length - 1];
        if (last) { S.wait = `${last.label}...`; renderStory(); }
        data = await step({ type: "continue" });
      }
      const reply = (S.view?.transcript || []).filter((t) => t.kind === "assistant").pop();
      if (reply) announce("Claude: " + reply.text);
      return true;
    } catch (err) {
      toast(err.message); render(); return false;
    } finally { S.wait = ""; setBusy(false); }
  }
  async function act(action) {
    if (S.busy) return false;
    setBusy(true);
    try { await step(action); return true; }
    catch (err) { toast(err.message); return false; }
    finally { setBusy(false); }
  }
  function setBusy(b) {
    S.busy = b;
    document.body.classList.toggle("busy", b);
    document.querySelectorAll("#story-actions button, .rb-actions .btn, .chip, #send").forEach((x) => { x.disabled = b; });
    if (!b) renderComposer();
  }

  // ------------------------------------------------------------------ the story
  const STEPS = 6;
  const bars = (n) => `<span class="story-bars" aria-hidden="true">${Array.from({ length: STEPS }, (_, i) => `<i class="${i < n ? "on" : ""}"></i>`).join("")}</span>`;
  const head = (n, title) => `<div class="story-kicker">${bars(n)}Step ${n} of ${STEPS}</div><h2 class="story-title" id="story-title">${esc(title)}</h2>`;
  const pending = () => S.view?.pending || [];
  const replies = () => (S.view?.transcript || []).filter((t) => t.kind === "assistant");
  const lastReply = () => replies().pop();
  const taskSkill = (r) => (r?.skills || []).filter((s) => s !== "house-rules")[0] || (r?.skills || [])[0] || "";
  const ok = (good) => (good ? icon("check-circle") : icon("alert", "i warn"));

  function storyContent() {
    const st = S.story, v = S.view;
    const waitLine = S.busy && S.wait ? `<p class="story-wait"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>${esc(S.wait)}</p>` : "";
    switch (S.step) {
      case 0: return {
        main: `<span class="pill pill-demo pill-plain">Live demo on a made up brokerage</span>
          <h2 class="story-headline" id="story-title">Your brokers talk. Claude updates the CRM. Nothing saves without their yes.</h2>
          <p class="story-sub">Follow one broker's voice note into the CRM. You confirm it, then try to break the rules. About two minutes.</p>
          <ul class="hero-points"><li>${icon("check")}Voice note in, CRM note and tasks out</li><li>${icon("check")}A read back before every write</li><li>${icon("check")}Times are never guessed</li></ul>`,
        actions: `<button type="button" class="btn btn-primary" data-go="start">Start the demo</button>
          <button type="button" class="btn-link" data-go="free">Skip to free chat</button>`, focus: "broker" };
      case 1: {
        const answered = replies().length > 0;
        const noCard = answered && !S.busy && !pending().length;
        return {
          main: head(1, "A broker sends a voice note.") + (noCard
            ? `<p class="story-text">Claude asked a question instead of preparing the note this time. Send the voice note again.</p>`
            : `<p class="story-text">${esc(brokerFirst())} just toured a lab building with a client. She pastes her voice note into Claude.</p>`) + waitLine,
          actions: S.busy ? "" : `<button type="button" class="btn btn-primary" data-go="${noCard ? "retry" : "send-note"}">${noCard ? "Send it again" : `Send ${esc(brokerFirst())}'s voice note`}</button>`,
          focus: "broker" };
      }
      case 2: {
        const r = lastReply();
        const skill = taskSkill(r);
        if (!pending().length && !(v?.saved || []).length && !S.busy) return {
          main: head(2, "You discarded it, so nothing was saved.") + `<p class="story-text">That is the gate working too. Send the voice note again to see the confirm.</p>`,
          actions: `<button type="button" class="btn btn-primary" data-go="retry">Send it again</button>`, focus: "broker" };
        const picked = !skill ? "Claude read the note back." : r.mode === "live"
          ? `Claude picked the ${esc(label(skill).toLowerCase())} skill on its own and read the note back.`
          : `The ${esc(label(skill).toLowerCase())} skill loaded and the note was read back.`;
        return {
          main: head(2, "Your turn: check it, then confirm.") +
            `<p class="story-text">${picked} <b>"Yesterday afternoon" stays in ${esc(brokerFirst())}'s words: it is vague, so no date is made up.</b> Confirm it on the card.</p>
            <p class="story-short">See the yellow box: "yesterday afternoon" stays in her words. Then confirm.</p>`,
          actions: "", focus: "broker" };
      }
      case 3: {
        const saved = (v?.saved || []);
        const tasks = saved.filter((r) => r.kind === "task").length;
        const notes = saved.filter((r) => r.kind === "note").length;
        const what = [notes ? count(notes, "note") : "", tasks ? count(tasks, "task") : ""].filter(Boolean).join(" and ") || "the record";
        return {
          main: head(3, "Saved, with the CRM's own time.") +
            `<p class="story-text">Your confirm saved ${what}. <b>The CRM's clock stamped them; ${esc(brokerFirst())}'s own words for the time sit beside it.</b></p>`,
          actions: `<button type="button" class="btn btn-primary" data-go="to-gate">Next: try to skip the gate</button>`, focus: "crm" };
      }
      case 4: {
        if (!st.gateDone) return {
          main: head(4, "Try to skip the gate.") + `<p class="story-text">${esc(brokerFirst())} says "just log it, don't ask me". For this test we also make the assistant try to save without your confirm.</p>` + waitLine,
          actions: S.busy ? "" : `<button type="button" class="btn btn-primary" data-go="send-gate">Send it</button>`, focus: "broker" };
        const savedNow = st.savedNow || 0;  // counted right after the test, so a later Confirm press does not change it
        return {
          main: head(4, savedNow ? "Something was saved. Check the log." : "The gate held.") + `<ul class="story-list one">
            <li>${ok(!savedNow)}<span><b>Saved without your confirm: ${savedNow}</b></span></li>
            <li>${st.testRefused ? icon("shield") : icon("alert", "i warn")}<span>${st.testRefused ? "The save attempt was refused by the CRM's code: only your Confirm button can save" : "No save attempt was made"}</span></li>
            <li>${icon("clock")}<span>Ravi's note still waits for ${esc(brokerFirst())}'s confirm. Nothing saves on its own.</span></li></ul>`,
          actions: `<button type="button" class="btn btn-primary" data-go="to-dana">Next: two people called Dana</button>`, focus: "broker" };
      }
      case 5: {
        if (!st.danaDone) return {
          main: head(5, "Two people called Dana.") + `<p class="story-text">${esc(brokerFirst())} asks Claude to move "Dana's deal" to LOI signed. The CRM has two contacts called Dana.</p>` + waitLine,
          actions: S.busy ? "" : `<button type="button" class="btn btn-primary" data-go="send-dana">Send it</button>`, focus: "broker" };
        const guessed = st.pendingAfterDana > st.pendingBeforeDana;
        return {
          main: head(5, guessed ? "It picked one, and it still waits for you." : "It asked instead of guessing.") + `<ul class="story-list one">
            <li>${ok(!guessed)}<span><b>Changes prepared: ${guessed ? 1 : 0}</b></span></li>
            <li>${icon("check-circle")}<span>${guessed ? "Nothing is saved: the card names the Dana it picked, so a wrong pick is caught before your confirm" : "Claude asked which Dana: Whitlock (Quillon Logistics) or Okafor (Bramblecote Foods)"}</span></li></ul>`,
          actions: `<button type="button" class="btn btn-primary" data-go="to-lunch">Next: when no skill fits</button>`, focus: "broker" };
      }
      case 6: {
        if (!st.lunchDone) return {
          main: head(6, "Not every question needs a skill.") + `<p class="story-text">${esc(brokerFirst())} asks something off topic. No skill should load, and the CRM should not be touched.</p>` + waitLine,
          actions: S.busy ? "" : `<button type="button" class="btn btn-primary" data-go="send-lunch">Ask about lunch</button>`, focus: "broker" };
        const m = v?.metrics || {};
        const all = replies();
        const lunch = all[all.length - 1];
        const lunchClean = lunch && !(lunch.skills || []).length && !(lunch.steps || []).length;
        const skillsFired = all.slice(0, -1).some((r) => (r.skills || []).length);
        const note = (v?.saved || []).find((r) => r.kind === "note");
        const vagueKept = !!(note && note.time && note.time.text && !note.time.nice);
        const guessed = st.pendingAfterDana > st.pendingBeforeDana;
        const figures = m.live_calls ? `<div class="story-figures"><div><span>This whole chat</span><strong>${money(m.cost_usd)}</strong></div>
            <div><span>1,000 chats like it</span><strong>$${(m.cost_usd * 1000).toFixed(2)}</strong></div></div>`
          : `<p class="story-text">Fixed rules answered, so this chat cost nothing. Cost shows when the live AI answers.</p>`;
        return {
          main: head(6, "What you just saw, and what it costs.") + figures + `<ul class="story-list">
            <li>${ok(lunchClean && skillsFired)}<span>The right skill loaded for each request, none for lunch</span></li>
            <li>${ok(!st.savedNow)}<span>Nothing reached the CRM until you pressed Confirm</span></li>
            <li>${ok(st.testRefused)}<span>A save without your confirm was refused by the CRM's code</span></li>
            <li>${ok(vagueKept)}<span>Vague times stayed in ${esc(brokerFirst())}'s words</span></li>
            <li>${ok(!guessed)}<span>Two Danas got a question, not a guess</span></li></ul>
            <p class="story-note">Your version runs on your CRM, your stages and your team's rules.</p>`,
          actions: `<button type="button" class="btn btn-primary" data-go="free">Try it yourself</button>
            <button type="button" class="btn-link" data-go="replay">Replay the demo</button>`, focus: "broker" };
      }
      default: {
        const brokers = (S.config?.brokers || []).map((b) => `<option value="${esc(b.id)}"${b.name === brokerName() ? " selected" : ""}>${esc(b.name)}</option>`).join("");
        return {
          main: `<div class="story-kicker">Free chat</div><h2 class="story-title" id="story-title">Ask what a broker would ask. Try the near misses too.</h2>
            <div class="free-row"><label for="broker-pick">Signed in as</label><select id="broker-pick">${brokers}</select>
            <span>Dashed chips should not load a skill.</span></div>`,
          actions: "", focus: "both" };
      }
    }
  }
  function renderStory() {
    const c = storyContent();
    $("#story-main").innerHTML = c.main;
    $("#story-actions").innerHTML = c.actions;
    document.body.dataset.step = String(S.step);
    document.body.dataset.focus = c.focus;
    document.body.classList.toggle("in-story", S.step !== "free");
    $("#replay").hidden = [0, 1, 2].includes(S.step);
    document.querySelectorAll("#story-actions button").forEach((x) => { x.disabled = S.busy; });
    $(".layout").inert = S.step === 0;
    requestAnimationFrame(() => {
      const story = $("#story");
      document.body.style.setProperty("--story-h", (getComputedStyle(story).position === "fixed" ? story.offsetHeight : 0) + "px");
      if (isPhone() && S.step !== "free" && S.step !== 2 && S.step !== 0) { const box = $("#thread"); box.scrollTop = box.scrollHeight; }
      if (S.step === 2) showCard();
    });
  }
  function setStep(n) {
    const before = S.step;
    S.step = n;
    save(); render();
    const c = storyContent();
    if (before !== n) {
      announce($("#story-title")?.textContent || "");
      if (isPhone() && c.focus !== "both" && c.focus !== S.pane) setPane(c.focus, true);
      const primary = $("#story-actions .btn-primary");
      if (primary && n !== 0 && S.keyboard) primary.focus({ preventScroll: true });  // keyboard users keep their place; no ring for clicks
      if (n === 2) showCard(true);
      if (n === 3) showSaved();
    }
  }
  // Step 2: the badge, the card's header and its Confirm button all in view, above the phone sheet.
  // When the card is taller than the room, its fields scroll inside the card.
  function showCard(focus) {
    requestAnimationFrame(() => {
      const card = [...document.querySelectorAll(".rb.ring-card")].pop(), box = $("#thread");
      if (!card) return;
      const bot = card.closest(".bot"), body = card.querySelector(".rb-body");
      body.style.maxHeight = ""; card.classList.remove("fit");
      const sheet = isPhone() ? ($("#story").offsetHeight || 0) : 0;
      const room = box.clientHeight - sheet - 12;
      const start = bot.offsetTop - 8;
      let end = card.offsetTop + card.offsetHeight + 8;
      if (end - start > room) {
        body.style.maxHeight = Math.max(isPhone() ? 60 : 88, body.offsetHeight - (end - start - room)) + "px";
        card.classList.add("fit");
        end = card.offsetTop + card.offsetHeight + 8;
      }
      box.scrollTop = end - start > room ? end - room : start;
      if (focus && S.keyboard) card.querySelector("[data-confirm]")?.focus({ preventScroll: true });
    });
  }
  function showSaved() {
    requestAnimationFrame(() => {
      const first = $(".rec.ring-card"), panel = $("#panel");
      if (first) panel.scrollTop += first.getBoundingClientRect().top - panel.getBoundingClientRect().top - 12;
    });
  }
  function advance() {
    if (S.step === 1 && pending().length) setStep(2);
    else if (S.step === 2 && (S.view?.saved || []).length) setStep(3);
  }
  function refocus() {
    if (S.keyboard && document.activeElement === document.body) $("#story-actions .btn-primary")?.focus({ preventScroll: true });
  }
  async function go(what) {
    if (S.busy) return;
    const story = S.config?.story || {};
    try {
      if (what === "start" || what === "replay") { S.story = {}; await newChat(); setStep(1); }
      else if (what === "send-note" || what === "retry") {
        if (what === "retry") { await newChat(); setStep(1); }
        await send(story.voice_note); advance(); render(); refocus();
      } else if (what === "to-gate") setStep(4);
      else if (what === "send-gate") {
        const savedBefore = S.view?.metrics?.writes_saved || 0;
        if (await send(story.gate)) {
          const gate = pending()[pending().length - 1];
          if (gate) {
            S.story.gateWrite = gate.id;
            await act({ type: "test", test: "commit_without_confirm" });
            const test = (S.view?.transcript || []).filter((t) => t.kind === "test").pop();
            S.story.testRefused = !!(test && test.refused);
          }
          S.story.savedNow = (S.view?.metrics?.writes_saved || 0) - savedBefore;
          S.story.gateDone = true; save();
        }
        render(); refocus();
      } else if (what === "to-dana") setStep(5);
      else if (what === "send-dana") {
        S.story.pendingBeforeDana = (S.view?.metrics?.writes_proposed || 0);
        if (await send(story.ambiguity)) { S.story.danaDone = true; S.story.pendingAfterDana = (S.view?.metrics?.writes_proposed || 0); save(); }
        render(); refocus();
      } else if (what === "to-lunch") setStep(6);
      else if (what === "send-lunch") {
        if (await send(story.off_topic)) { S.story.lunchDone = true; save(); }
        render(); refocus();
      } else if (what === "free") {
        S.story = {}; await newChat(); setStep("free"); $("#input").value = ""; autosize();
        if (!isPhone()) $("#input").focus();  // on a phone the keyboard would cover the suggestions
      }
    } catch (err) { toast(err.message); }
  }

  // ------------------------------------------------------------------ the chat
  const spark = (cls = "avatar sm") => `<span class="${cls}" aria-hidden="true"><svg><use href="#spark"/></svg></span>`;
  const stepList = (steps) => `<ol class="steps">${steps.map((s) => `<li><span class="tick ${s.ok ? "" : s.outcome === "blocked" ? "blocked" : "no"}">${icon(s.ok ? "check" : "x")}</span><span>${esc(s.label)}</span></li>`).join("")}</ol>`;
  function showPending(text) {
    const box = $("#thread");
    box.insertAdjacentHTML("beforeend", `<div class="out-row"><span class="sr-only">${esc(brokerName())}: </span><div class="bubble bubble-out" dir="auto">${esc(text)}</div></div>
      <div class="bot">${spark()}<div class="working"><div class="working-head"><span class="dots"><i></i><i></i><i></i></span>Working on it</div></div></div>`);
    box.scrollTop = box.scrollHeight;
    $("#input").value = ""; autosize();
  }
  function trace(steps, open) {
    if (!steps || !steps.length) return "";
    const failed = steps.some((s) => !s.ok);
    return `<details class="trace"${open ? " open" : ""}><summary>${icon(failed ? "shield" : "check-circle", "i ok")}Looked at ${steps.length} thing${steps.length === 1 ? "" : "s"}${icon("chev-down", "i chev")}</summary>${stepList(steps)}</details>`;
  }
  function badge(it) {
    const loaded = it.skills || [];
    if (loaded.length) {
      const tasks = loaded.filter((s) => s !== "house-rules");
      const names = (tasks.length ? tasks : loaded).map(label);
      const withRules = tasks.length && loaded.includes("house-rules");
      return `<span class="skill">${icon("book")}<span>${names.length > 1 ? "Skills" : "Skill"} used: <b>${esc(names.join(", "))}</b>${withRules ? `<span class="skill-extra"> + House rules</span>` : ""}</span></span>`;
    }
    if ((it.skills_earlier || []).length) return `<span class="skill none">${icon("book")}<span>Using a skill loaded earlier</span></span>`;
    return `<span class="skill none">${icon("book")}<span>No skill used</span></span>`;
  }
  // The time the broker stated, beside the CRM's clock. A date with a warning is still a date.
  function statedBox(t) {
    if (!t || !t.text) return `<div class="time-box"><span>${esc(t ? t.label : "Stated time")}</span><b>None given</b><small>Left empty, not guessed</small></div>`;
    const exact = !!t.nice && !t.note;
    const small = exact ? `Broker's words. Saved as ${esc(t.nice)}` : "Broker's words. Vague, so no date set";
    return `<div class="time-box ${exact && !t.warning ? "exact" : "flagged"}"><span>${esc(t.label)}</span><b>"${esc(t.text)}"</b>
      <small>${small}</small>${t.warning ? `<small class="warn-line">Check: ${esc(t.warning)}</small>` : ""}</div>`;
  }
  const systemBox = (at, prepared) => `<div class="time-box system"><span>Recorded at (CRM clock)</span><b>${at ? esc(day(at)) + ", " + esc(clock(at)) : "When you confirm"}</b>
    <small>${at || !prepared ? "Set by the system, never typed" : `Set by the system. Prepared ${esc(clock(prepared))}`}</small></div>`;
  function dueChip(t) {
    if (!t || !t.text) return `<span class="due">No date given</span>`;
    if (t.nice && !t.note) return `<span class="due ${t.warning ? "flagged" : "exact"}">Due ${esc(t.nice)}</span>`;
    return `<span class="due flagged">"${esc(t.text)}": kept as words</span>`;
  }
  function readback(card, ring, quiet) {
    const tasks = card.items.filter((it) => it.op === "create_task");
    const others = card.items.filter((it) => it.op !== "create_task");
    let body = others.map((it) => `<div class="rb-item"><div class="rb-kind">${icon(it.op === "create_note" ? "doc" : "database")}${esc(it.heading)}</div>
        <dl class="rows">${it.rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
        ${it.lists.map(([k, vals]) => `<div class="rb-list"><b>${esc(k)}</b><ul>${vals.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("")}</div>`).join("");
    if (tasks.length) {
      body += `<div class="rb-item"><div class="rb-kind">${icon("task")}${tasks.length === 1 ? "Task" : `Tasks (${tasks.length})`}</div>
        <ul class="rb-tasks">${tasks.map((t) => {
          const rows = Object.fromEntries(t.rows);
          return `<li><div class="rb-task-head"><span>${esc(rows.Task)}</span>${dueChip(t.time)}</div>
            <small>For ${esc(rows.For)} · Deal: ${esc(rows.Deal)}</small>${t.time && t.time.warning ? `<small class="warn-line">Check: ${esc(t.time.warning)}</small>` : ""}</li>`;
        }).join("")}</ul></div>`;
    }
    if ((card.flags || []).length) {
      body += `<div class="rb-item rb-flags"><div class="rb-kind">${icon("alert")}To check</div><ul>${card.flags.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>`;
    }
    const stated = others.filter((it) => it.time).map((it) => statedBox(it.time)).join("");
    const status = card.status;
    const pill = status === "pending" ? `<span class="pill pill-pending"><span class="pill-long">Waiting for your confirm</span><span class="pill-short">Not saved yet</span></span>`
      : status === "committed" ? `<span class="pill pill-saved">Saved</span>`
      : `<span class="pill pill-quiet">${status === "expired" ? "Expired" : "Discarded"}</span>`;
    const times = `<div class="times">${stated || ""}${systemBox(status === "committed" ? card.committed_at : null, card.proposed_at)}</div>`;
    const ids = `data-hash="${esc(card.hash)}"`;
    const foot = status === "pending"
      ? `${times}<div class="rb-actions"><span class="rb-note">Nothing is saved until you confirm.</span><button type="button" class="btn btn-secondary" data-discard="${esc(card.id)}" ${ids}>Discard</button>
         <button type="button" class="btn ${quiet ? "btn-secondary" : "btn-primary"}${ring ? " ring" : ""}" data-confirm="${esc(card.id)}" ${ids}>${icon("check")}Confirm and save</button></div>`
      : status === "committed"
        ? `${times}<div class="rb-done">${icon("check-circle")}<span><b>Saved by ${esc(brokerName())}</b> with the Confirm button.</span></div>`
        : `<div class="rb-done off">${icon("x-circle")}<span>${status === "expired" ? "Expired after 30 minutes. Nothing was saved." : "Discarded. Nothing was saved."}</span></div>`;
    return `<article class="rb${status === "committed" ? " is-saved" : status === "pending" ? "" : " is-off"}${ring ? " ring-card" : ""}" aria-label="Read back: ${esc(card.summary)}">
      <div class="rb-head"><div class="rb-title">${icon("doc")}What will be saved</div>${pill}</div>
      <div class="rb-body">${body}</div><div class="rb-foot">${foot}</div></article>`;
  }
  function renderChat() {
    const box = $("#thread");
    const items = S.view ? S.view.transcript : [];
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    const lastBot = items.map((t) => t.kind).lastIndexOf("assistant");
    const firstPendingCard = (() => {
      for (const it of items) for (const c of it.cards || []) if (c.status === "pending") return c.id;
      return null;
    })();
    const inStory = S.step !== "free";
    let html = `<div class="bot">${spark()}<div class="bot-head"><span class="bot-name">Claude</span></div>
      <div class="answer">Hi ${esc(brokerFirst())}. Paste a voice note after a call or a tour, or ask me to update a record, prep a meeting, draft an email or sum up the pipeline.</div></div>`;
    items.forEach((it, idx) => {
      if (it.kind === "broker") {
        html += `<div class="out-row"><span class="sr-only">${esc(brokerName())}: </span><div class="bubble bubble-out" dir="auto">${esc(it.text)}</div></div>`;
      } else if (it.kind === "assistant") {
        // From step 4 on, Ravi's note keeps a quiet Confirm: the story is about what does not save.
        const cards = (it.cards || []).map((c) => readback(c, S.step === 2 && c.id === firstPendingCard,
          inStory && typeof S.step === "number" && S.step >= 4 && c.id === S.story.gateWrite)).join("");
        html += `<div class="bot">${spark()}
          <div class="bot-head"><span class="bot-name">Claude</span><span class="tag">${it.mode === "live" ? "AI" : "Fixed rules"}</span>${badge(it)}</div>
          ${trace(it.steps, idx === lastBot && S.step === "free" && !isPhone())}
          <div class="answer" dir="auto"><span class="sr-only">Claude: </span>${format(it.text)}</div>${cards}</div>`;
      } else if (it.kind === "notice") {
        html += `<div class="sys-line ${it.notice === "saved" ? "saved" : ""}">${icon(it.notice === "saved" ? "check-circle" : "x-circle", "i i-sm")}${esc(it.text)}</div>`;
      } else if (it.kind === "test") {
        html += `<div class="event">${icon("shield")}<div class="event-head"><span>${esc(it.text)}</span><span class="pill ${it.refused ? "pill-refused" : "pill-saved"}">${it.refused ? "Refused" : "Saved"}</span></div>
          <div class="event-body">${it.refused ? "The CRM's code said: " : ""}${esc(it.result)}</div></div>`;
      } else if (it.kind === "system") {
        html += `<div class="sys-line">${icon("alert", "i i-sm")}${esc(it.text)}</div>`;
      } else if (it.kind === "working") {
        html += `<div class="bot">${spark()}<div class="working"><div class="working-head"><span class="dots"><i></i><i></i><i></i></span>Working on it</div>
          ${(it.steps || []).length ? stepList(it.steps) : ""}</div></div>`;
      }
    });
    const before = box.dataset.count || "";
    box.innerHTML = html;
    box.dataset.count = String(items.length);
    const lastBroker = [...box.querySelectorAll(".out-row")].pop();
    const lastKind = items.length ? items[items.length - 1].kind : "";
    if (isPhone() && S.step !== "free" && S.step !== 2) box.scrollTop = box.scrollHeight;  // the newest item, just above the sheet
    else if ((lastKind === "assistant" || lastKind === "working") && lastBroker) box.scrollTop = Math.max(0, lastBroker.offsetTop - 12);
    else if (nearBottom || String(items.length) !== before) box.scrollTop = box.scrollHeight;
    if (S.step === 2) showCard();
    renderComposer();
  }
  function renderComposer() {
    const input = $("#input");
    const inStory = S.step !== "free";
    const story = S.config?.story || {};
    const preset = S.step === 1 && !pending().length ? story.voice_note : S.step === 4 && !S.story.gateDone ? story.gate
      : S.step === 5 && !S.story.danaDone ? story.ambiguity : S.step === 6 && !S.story.lunchDone ? story.off_topic : "";
    const full = (S.view?.metrics?.broker_messages || 0) >= 25;
    input.readOnly = inStory;
    if (inStory) { input.value = S.busy ? "" : (preset || ""); input.placeholder = "The demo writes the next message for you"; }
    else input.placeholder = full ? "Message limit reached: replay the demo to start over" : isPhone() ? "Paste a voice note or ask" : "Paste a voice note or ask about a client";
    input.disabled = !inStory && full;
    $("#send").disabled = S.busy || (inStory && !preset) || full;
    autosize();
    $("#chat-status").textContent = isPhone() ? `${brokerName()} · fictional brokerage` : `Signed in as ${brokerName()} · Marrowby Commercial (fictional)`;
    const chips = S.config?.chips || [];
    $("#suggest").innerHTML = inStory ? "" : chips.map((c, i) => `<button type="button" class="chip${c.kind === "near_miss" ? " chip-near" : c.kind === "test" ? " chip-test" : ""}" data-chip="${i}"${c.kind === "near_miss" ? ' title="A near miss: no skill should load"' : ""}>${c.kind === "test" ? icon("shield") : ""}${esc(c.label)}</button>`).join("");
  }

  // ------------------------------------------------------------------ the CRM
  const ACTIONS = { search: "Looked up", "open record": "Opened", "read pipeline": "Read the pipeline:", "read calendar": "Read the calendar:",
    "propose write": "Prepared a change:", save: "Save:", discard: "Discarded:", "draft email": "Drafted an email" };
  function who(actor) {
    if (actor.startsWith("Claude for ")) return "Claude, for " + actor.slice(11).split(" ")[0];
    if (actor.startsWith("Test")) return "Test, acting as the assistant";
    return actor;
  }
  function logList(entries, all) {
    const list = [...entries].reverse();
    const shown = all ? list : list.slice(0, 8);
    const rows = shown.map((e) => {
      const outcome = e.outcome === "ok" ? "" : `<span class="pill ${e.outcome === "blocked" ? "pill-pending" : "pill-refused"}">${e.outcome === "blocked" ? "Blocked" : "Refused"}</span>`;
      return `<li class="${e.outcome === "ok" ? "" : esc(e.outcome)}"><span class="at" title="${esc(e.at)}">${esc(clock(e.at))}</span>
        <span class="what">${esc(ACTIONS[e.action] || e.action)} ${esc(e.detail)}<span class="who">${esc(who(e.actor))}</span></span>${outcome}</li>`;
    }).join("");
    const more = list.length > shown.length ? `<div class="log-more"><button type="button" class="btn-link" data-log-all="1">Show all ${list.length} entries</button></div>` : "";
    return `<ul class="log">${rows}</ul>${more}`;
  }
  // One card per save: the CRM's clock once, then each record with the time the broker stated.
  function savedCard(records, ring) {
    const first = records[0];
    const note = records.find((r) => r.kind === "note");
    const kinds = {};
    records.forEach((r) => { kinds[r.kind] = (kinds[r.kind] || 0) + 1; });
    const what = Object.entries(kinds).map(([k, n]) => count(n, k)).join(" and ");
    const rows = records.map((r) => `<li><span class="tile sm">${icon(r.kind === "task" ? "task" : r.kind === "note" ? "doc" : "database")}</span>
      <div><div class="saved-title">${esc(r.title)}</div><small>${r.kind === "note" ? "Note" : r.kind === "task" ? "Task" : esc(r.kind[0].toUpperCase() + r.kind.slice(1))}${r.contact ? " · " + esc(r.contact) : ""}</small></div>
      ${r.kind === "task" ? dueChip(r.time) : ""}</li>`).join("");
    return `<article class="card rec${ring ? " ring-card" : ""}"><div class="rec-head"><span class="tile">${icon("database")}</span>
      <div><div class="rec-title">Saved ${esc(what)}</div><div class="rec-sub">${esc((note || first).title)}</div></div><span class="pill pill-saved">Saved</span></div>
      <div class="times">${systemBox(first.recorded_at)}${note && note.time ? statedBox(note.time) : ""}</div>
      <ul class="saved-list">${rows}</ul></article>`;
  }
  function renderCRM() {
    const v = S.view || { pending: [], saved: [], drafts: [], log: [], metrics: {}, deals: [] };
    const m = v.metrics || {};
    const sc = $("#switch-count"); sc.hidden = !v.pending.length; sc.textContent = v.pending.length;
    const cost = $("#cost-line");
    cost.hidden = !m.live_calls;
    cost.innerHTML = m.live_calls ? `${icon("cpu", "i i-sm")}AI cost of this chat: <strong>${money(m.cost_usd)}</strong>` : "";
    let html = "";
    if (v.pending.length) {
      html += `<div class="group-label">Waiting for a confirm</div>` + v.pending.map((c) => `<article class="card rec"><div class="rec-head"><span class="tile">${icon("clock")}</span>
        <div><div class="rec-title">${esc(c.summary)}</div><div class="rec-sub">${c.items.length} record${c.items.length === 1 ? "" : "s"} · confirm it on the card in the chat</div></div>
        <span class="pill pill-pending">Not saved</span></div></article>`).join("");
    }
    // Newest save first; inside one save, the order it was read back in (the note, then its tasks).
    const writes = [...new Set(v.saved.map((r) => r.write_id))].reverse();
    if (writes.length) {
      html += `<div class="group-label">Saved in this demo</div>` + writes.map((w, i) => savedCard(v.saved.filter((r) => r.write_id === w), S.step === 3 && i === 0)).join("");
    }
    if (v.drafts.length) {
      html += `<div class="group-label">Email drafts (never sent)</div>` + v.drafts.map((d) => `<article class="card rec"><div class="rec-head"><span class="tile">${icon("mail")}</span>
        <div><div class="rec-title">${esc(d.subject)}</div><div class="rec-sub">To ${esc(d.to_name)} · in ${esc(brokerFirst())}'s mailbox</div></div><span class="pill pill-quiet">Draft, not sent</span></div></article>`).join("");
    }
    if (!v.pending.length && !writes.length && !v.drafts.length) {
      html += `<div class="empty"><span class="tile">${icon("database")}</span><h3>Nothing new yet</h3>
        <p>When Claude prepares a change, it waits for the broker's confirm. Saved notes and tasks appear here with the CRM's own time.</p></div>`;
    }
    html += `<details class="card fold" id="activity"${S.logOpen ? " open" : ""}><summary><span class="tile">${icon("list")}</span>
      <div><div class="fold-title">Activity log</div><div class="fold-sub">Every read and write, with the CRM's clock</div></div>${icon("chev-down", "i chev")}</summary>
      ${v.log.length ? logList(v.log, S.logAll) : '<p class="explain" style="padding:0 16px 16px">Every lookup, change, refusal and save appears here.</p>'}</details>`;
    html += hoodCard(v);
    const panel = $("#panel");
    const keep = panel.scrollTop;
    panel.innerHTML = html;
    panel.scrollTop = keep;
  }
  function hoodCard(v) {
    const m = v.metrics || {};
    const cfg = S.config || {};
    const tokens = (n) => (n || 0).toLocaleString("en-US");
    const used = new Set(v.skills_used || []);
    const skills = (cfg.skills || []).map((s) => `<li><span class="tick ${used.has(s.name) ? "" : "idle"}">${icon("check")}</span><span><b>${esc(label(s.name))}</b> <code>${esc(s.name)}</code>: ${esc(s.description)}</span></li>`).join("");
    const deals = (v.deals || []).map((d) => `<tr><td>${esc(d.name)}</td><td>${esc(d.stage)}</td><td>${esc(d.owner)}</td></tr>`).join("");
    const raw = (v.log || []).slice(-40).map((e) => `${e.at}  ${e.actor} | ${e.action} | ${e.ref || "-"} | ${e.outcome}\n  ${e.detail}`).join("\n");
    const model = cfg.model ? prettyModel(cfg.model) : "not configured";
    return `<details class="card fold" id="hood"${S.hoodOpen ? " open" : ""}><summary><span class="tile">${icon("cpu")}</span>
      <div><div class="fold-title">Under the hood</div><div class="fold-sub">Who answers, the six skills, usage, the raw log, deals</div></div>${icon("chev-down", "i chev")}</summary>
      <div class="hood-body">
        <div><h4>Who answers</h4><div class="seg" role="group" aria-label="Who answers">
          <button type="button" data-mode="live" aria-pressed="${S.live && !!cfg.live}"${cfg.live ? "" : " disabled"}><span class="live-dot"></span>Live AI (${esc(model)})</button>
          <button type="button" data-mode="rules" aria-pressed="${!(S.live && cfg.live)}">Fixed rules, no AI</button></div>
          <p class="explain" style="margin-top:8px">Live AI: Claude sees each skill's name and description, and loads the ones that fit with a <code>load_skill</code> tool. Nothing in the code picks the skill. Fixed rules: simple keyword rules pick it instead, and every reply is labelled "Fixed rules". Both go through the same CRM rules.${cfg.live ? "" : " This server has no API key, so fixed rules answer."}</p></div>
        <div><h4>The six skills (ticked: loaded in this chat)</h4><ul class="skill-list">${skills}</ul></div>
        <div><h4>Usage in this chat</h4><dl class="usage">
          <div><dt>Live AI calls</dt><dd>${m.live_calls || 0}</dd></div><div><dt>Tool calls</dt><dd>${m.tool_calls || 0}</dd></div>
          <div><dt>Tokens read</dt><dd>${tokens(m.input_tokens)} <small>(${tokens(m.cached_tokens)} cached)</small></dd></div><div><dt>Tokens written</dt><dd>${tokens(m.output_tokens)}</dd></div>
          <div><dt>AI cost</dt><dd>${money(m.cost_usd)}</dd></div><div><dt>Average step</dt><dd>${m.avg_ms ? (m.avg_ms / 1000).toFixed(1) + " s" : "n/a"}</dd></div>
          <div><dt>Writes proposed / saved</dt><dd>${m.writes_proposed || 0} / ${m.writes_saved || 0}</dd></div><div><dt>Saves refused</dt><dd>${m.saves_refused || 0}</dd></div></dl></div>
        <div><h4>Raw activity log, with record and write ids</h4><pre class="raw">${esc(raw || "empty")}</pre></div>
        <div><h4>Deals in the CRM (your private copy)</h4><table class="table"><thead><tr><th>Deal</th><th>Stage</th><th>Owner</th></tr></thead><tbody>${deals}</tbody></table></div>
      </div></details>`;
  }
  function prettyModel(m) {
    const x = String(m).match(/^claude-(\w+)-(\d+)-(\d+)/);
    return x ? `Claude ${x[1][0].toUpperCase()}${x[1].slice(1)} ${x[2]}.${x[3]}` : m;
  }

  function render() { renderStory(); renderChat(); renderCRM(); }

  // ------------------------------------------------------------------ events
  function autosize() { const t = $("#input"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 120) + "px"; }
  let labelTimer = null;
  function setPane(pane, announceIt) {
    S.pane = pane;
    document.body.dataset.pane = pane;
    document.querySelectorAll(".switch-row button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.pane === pane)));
    if (announceIt && isPhone()) {
      const el = $("#side-label");
      el.textContent = pane === "crm" ? "Now: the CRM" : "Back to the chat";
      el.hidden = false; clearTimeout(labelTimer); labelTimer = setTimeout(() => { el.hidden = true; }, 1500);
    }
  }
  function composerSend() {
    if (S.step === 1) return go(pending().length ? "" : "send-note");
    if (S.step === 4 && !S.story.gateDone) return go("send-gate");
    if (S.step === 5 && !S.story.danaDone) return go("send-dana");
    if (S.step === 6 && !S.story.lunchDone) return go("send-lunch");
    if (S.step === "free") return send($("#input").value);
    return null;
  }
  function wire() {
    document.addEventListener("keydown", (e) => { if (e.key === "Tab" || e.key === "Enter" || e.key === " ") S.keyboard = true; }, true);
    document.addEventListener("pointerdown", () => { S.keyboard = false; }, true);
    $("#composer").addEventListener("submit", (e) => { e.preventDefault(); composerSend(); });
    $("#input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); composerSend(); } });
    $("#input").addEventListener("input", autosize);
    document.addEventListener("change", async (e) => {
      if (e.target.id === "broker-pick" && !S.busy) { try { await newChat(e.target.value); } catch (err) { toast(err.message); } }
    });
    document.addEventListener("click", (e) => {
      const t = e.target.closest("button");
      if (!t || t.disabled) return;
      if (t.dataset.go) go(t.dataset.go);
      else if (t.dataset.chip !== undefined) send(S.config.chips[+t.dataset.chip].text);
      else if (t.dataset.confirm) {
        act({ type: "confirm", write_id: t.dataset.confirm, hash: t.dataset.hash }).then((done) => { if (done) { announce("Saved to the CRM."); advance(); } });
      } else if (t.dataset.discard) act({ type: "discard", write_id: t.dataset.discard, hash: t.dataset.hash }).then(() => renderStory());
      else if (t.dataset.logAll) { S.logAll = true; renderCRM(); }
      else if (t.dataset.mode) { S.live = t.dataset.mode === "live"; store.set("teamos-live", S.live); renderCRM(); }
      else if (t.dataset.pane) setPane(t.dataset.pane);
    });
    document.addEventListener("toggle", (e) => {
      if (e.target.id === "hood") S.hoodOpen = e.target.open;
      if (e.target.id === "activity") S.logOpen = e.target.open;
    }, true);
    $("#replay").addEventListener("click", () => go("replay"));
    window.addEventListener("resize", () => renderStory());
  }

  async function init() {
    wire();
    try {
      S.config = await (await fetch("/api/config")).json();
    } catch { toast("The demo server is not reachable."); return; }
    const savedLive = store.get("teamos-live");
    S.live = !!S.config.live && savedLive !== false;
    const saved = store.get("teamos-demo");
    if (saved && saved.session) {
      S.session = saved.session; S.story = saved.story || {}; S.step = saved.step ?? 0;
      let kept = null;
      try { kept = await step({ type: "view" }); } catch { S.view = null; }
      if (!kept) { S.step = 0; S.story = {}; }  // a chat from another day or older rules: start over
    }
    if (!S.view) { await newChat(); S.step = 0; }
    render();
  }
  init();
})();
