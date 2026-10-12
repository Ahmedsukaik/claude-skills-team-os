/* Claude Skills Team OS demo page.
   A short guided story (six steps, one action each), then free chat. The server keeps nothing:
   this page holds the chat (the "session", signed by the server) and sends it with every request.
   See teamos/session.py. */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const S = {
    config: null, session: null, view: null, live: true, busy: false, step: 0, wait: "", story: {},
    pane: "broker", hoodOpen: false, logOpen: true, logAll: false, keyboard: false, openReplies: new Set(),
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
  // Motion that plays once per thing (a card rising in, a stamp landing). The page re-renders
  // often, so an element rebuilt mid-animation carries on from where it was (a negative delay)
  // instead of starting over; after `ms` it is plain. Nothing plays for what was already on the
  // page when it loaded. prefers-reduced-motion turns it all off in style.css.
  const born = new Map();
  let motionReady = false;
  function anim(key, ms = 1400, onLoad = false) {
    const now = performance.now();
    if (!born.has(key)) born.set(key, motionReady || onLoad ? now : -Infinity);
    const age = now - born.get(key);
    return age < ms ? { cls: " anim", style: ` style="--age:-${Math.round(age)}ms"` } : { cls: "", style: "" };
  }
  const lessMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // S1: a Confirm button only counts once its card has been on screen for a moment, so a held or
  // doubled Enter cannot save a card nobody read.
  const ARM_MS = 700;
  const shownAt = new Map(), arming = new Set();
  function armed(id) {
    if (!shownAt.has(id)) shownAt.set(id, performance.now());
    const left = ARM_MS - (performance.now() - shownAt.get(id));
    if (left > 0 && !arming.has(id)) {
      arming.add(id);
      setTimeout(() => { document.querySelectorAll("[data-confirm]").forEach((b) => { if (b.dataset.confirm === id) b.dataset.armed = "1"; }); }, left + 10);
    }
    return left <= 0;
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
  // Each step is a sheet of the drawing set: "SHEET 2 OF 6 · YOUR TURN".
  const SHEET = { 1: "Voice note", 2: "Your turn", 3: "Saved", 4: "The gate", 5: "Two Danas", 6: "No skill" };
  const head = (n, title, sheet) => `<div class="story-kicker">${bars(n)}<span>Sheet ${n} of ${STEPS} · ${esc(sheet || SHEET[n])}</span></div><h2 class="story-title" id="story-title">${esc(title)}</h2>`;
  const pending = () => S.view?.pending || [];
  const replies = () => (S.view?.transcript || []).filter((t) => t.kind === "assistant");
  const lastReply = () => replies().pop();
  const ok = (good) => (good ? icon("check-circle") : icon("alert", "i warn"));

  function storyContent() {
    const st = S.story, v = S.view;
    const waitLine = S.busy && S.wait ? `<p class="story-wait"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>${esc(S.wait)}</p>` : "";
    switch (S.step) {
      case 0: return {
        main: `<div class="hero">
          <div class="hero-copy">
            <span class="kicker"><i aria-hidden="true"></i>Sheet A-101 · Live demo</span>
            <h2 class="story-headline" id="story-title">Your brokers talk. <br>Claude updates the CRM. <br><span>Nothing saves without their yes.</span></h2>
            <p class="story-sub">Follow one voice note from a property tour into the CRM. You confirm it, then try to break the rules. About two minutes.</p>
            <div class="hero-actions"><button type="button" class="btn btn-primary btn-lg" data-go="start">Start the demo${icon("arrow-right")}</button>
              <button type="button" class="btn-link" data-go="free">Skip to free chat</button></div>
            <ol class="hero-points"><li><span>01</span>Voice note in, CRM note and tasks out</li><li><span>02</span>A read back before every write</li><li><span>03</span>Times are never guessed</li></ol>
          </div>
          ${heroFigure()}
        </div>`,
        actions: "", focus: "broker" };
      case 1: {
        const answered = replies().length > 0;
        const noCard = answered && !S.busy && !pending().length;
        return {
          main: head(1, "A broker sends a voice note.") + (noCard
            ? `<p class="story-text">Claude asked a question instead of preparing the note this time. Send the voice note again.</p>`
            : `<blockquote class="fig-quote story-quote"><span>Voice note · ${esc(brokerName())}</span><p class="quote-text">${esc(S.config?.story?.voice_note || "")}</p></blockquote>`) + waitLine,
          actions: S.busy ? "" : `<button type="button" class="btn btn-primary" data-go="${noCard ? "retry" : "send-note"}">${noCard ? "Send it again" : `Send ${esc(brokerFirst())}'s voice note`}</button>`,
          focus: "broker" };
      }
      case 2: {
        if (!pending().length && !(v?.saved || []).length && !S.busy) return {
          main: head(2, "You discarded it, so nothing was saved.") + `<p class="story-text">That is the gate working too. Send the voice note again to see the confirm.</p>`,
          actions: `<button type="button" class="btn btn-primary" data-go="retry">Send it again</button>`, focus: "broker" };
        return {
          main: head(2, "Your turn: check it, then confirm.") +
            `<p class="story-text">Check the card, then confirm. <b>"Yesterday afternoon" stays in ${esc(brokerFirst())}'s words: no date is invented.</b></p>
            <p class="story-short">See the yellow box: "yesterday afternoon" stays in her words. Then confirm.</p>`,
          actions: "", focus: "broker" };
      }
      case 3: {
        return {
          main: head(3, "Saved, with the CRM's own time.") +
            `<p class="story-text">Saved. <b>The CRM's clock set the time; ${esc(brokerFirst())}'s words sit beside it.</b></p>`,
          actions: `<button type="button" class="btn btn-primary" data-go="to-gate">Next: try to skip the gate</button>`, focus: "crm" };
      }
      case 4: {
        if (!st.gateDone) return {
          main: head(4, "Try to save without a yes.") + `<p class="story-text">${esc(brokerFirst())} says "just log it, don't ask me." We also force a save without her confirm.</p>` + waitLine,
          actions: S.busy ? "" : `<button type="button" class="btn btn-primary" data-go="send-gate">Send it</button>`, focus: "broker" };
        const savedNow = st.savedNow || 0;  // counted right after the test, so a later Confirm press does not change it
        return {
          main: head(4, savedNow ? "Something was saved. Check the log." : "The gate held.") + `<ul class="story-list one">
            <li>${ok(!savedNow)}<span><b>Saved without your confirm: ${savedNow}</b></span></li>
            <li>${st.testRefused ? icon("shield") : icon("alert", "i warn")}<span>${st.testRefused ? "The CRM's code refused the forced save" : "No save attempt was made"}</span></li>
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
            <li>${icon("check-circle")}<span>${guessed ? "Nothing is saved: the card names the Dana it picked" : "Claude asked: Whitlock (Quillon) or Okafor (Bramblecote)?"}</span></li></ul>`,
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
          main: head(6, m.live_calls ? "What you just saw, and what it costs." : "What you just saw.", "Summary") + figures +
            `<p class="story-note">Your version runs on your CRM, your stages and your team's rules.</p><ul class="story-list">
            <li>${ok(lunchClean && skillsFired)}<span>Right skill, none for lunch</span></li>
            <li>${ok(!st.savedNow && st.testRefused)}<span>No save without Confirm</span></li>
            <li>${ok(vagueKept && !guessed)}<span>No guessed times or Danas</span></li></ul>`,
          actions: `<button type="button" class="btn btn-primary" data-go="free">Try it yourself</button>
            <button type="button" class="btn-link" data-go="replay">Replay the demo</button>`, focus: "broker" };
      }
      default: {
        const brokers = (S.config?.brokers || []).map((b) => `<option value="${esc(b.id)}"${b.name === brokerName() ? " selected" : ""}>${esc(b.name)}</option>`).join("");
        return {
          main: `<div class="story-kicker">Free chat</div><h2 class="story-title" id="story-title">Ask what a broker would ask. Try the near misses too.</h2>
            <div class="free-row"><label for="broker-pick">Signed in as</label><select id="broker-pick">${brokers}</select>
            <span>Dashed chips are trick questions: no skill should load.</span></div>`,
          actions: "", focus: "both" };
      }
    }
  }
  // The first screen's drawing: the floor plan of the toured building, amber callouts for what the
  // client liked and what worried him, the voice note, and the title block still waiting for a yes.
  let heroTimer = null;
  function heroFigure() {
    const a = anim("hero", 2600, true);
    const age = performance.now() - born.get("hero");
    const approved = !lessMotion() && age >= 1800;   // about 1.8 s in, the drawing gets its yes (once)
    if (!approved && !lessMotion() && !heroTimer) {
      heroTimer = setTimeout(() => { if (S.step === 0) renderStory(); }, 1800 - age + 20);
    }
    const approval = approved
      ? `<div class="tb-cell tb-approved"><span class="tb-k">Approved by</span>${stamp("saved", `Approved · ${esc(brokerFirst())}`, "hero-stamp")}</div>`
      : `<div class="tb-cell tb-wait"><span class="tb-k">Approved by</span><b>Waiting for ${esc(brokerFirst())}</b></div>`;
    const label = (x, y, long, short, sx = x, sy = y) => `<text class="fp-label fp-long" x="${x}" y="${y}">${long}</text><text class="fp-label fp-short" x="${sx}" y="${sy}">${short}</text>`;
    return `<div class="hero-side">
      <figure class="hero-fig${a.cls}"${a.style} aria-label="An example: ${esc(brokerFirst())}'s voice note about a tour of 310 Canal Street, waiting for her yes">
        <div class="fig-bar"><span>310 Canal Street · Lab building · Tour</span><span>Scale 1:200</span></div>
        <div class="fig-plan">
          <svg class="plan" viewBox="0 0 560 280" aria-hidden="true" focusable="false">
            <g transform="translate(0 20)">
              <g class="fp-wall">
                <rect x="20" y="20" width="520" height="210"/>
                <path d="M200 20v130M200 180v50M360 20v90M360 140v90M200 110h160M20 150h180"/>
                <path class="fp-door" d="M200 150a30 30 0 0 1 30 30M360 110a30 30 0 0 0 -30 30"/>
                <rect class="fp-dock" x="420" y="200" width="90" height="30"/>
              </g>
              <g class="fp-faint">
                <path d="M44 44h120M44 60h120M44 76h120M44 92h120"/>
                <circle cx="460" cy="60" r="22"/><path d="M448 60h24M460 48v24"/>
              </g>
              ${label(44, 122, "LAB BENCHES", "LAB", 44, 128)}
              ${label(228, 62, "OPEN OFFICE", "OFFICE", 222, 72)}
              ${label(396, 100, "HVAC PLANT", "HVAC", 392, 108)}
              ${label(424, 194, "LOADING DOCK", "DOCK", 432, 192)}
              ${label(44, 198, "COLD STORE", "COLD", 44, 204)}
            </g>
            <g class="fp-callouts">
              <path class="fp-lead" pathLength="1" d="M110 80V28"/>
              <path class="fp-lead" pathLength="1" d="M465 236V262" style="--d:160ms"/>
              <path class="fp-lead fp-worried" pathLength="1" d="M470 80L500 30" style="--d:320ms"/>
              <circle class="fp-dot" cx="110" cy="80" r="3.5"/><circle class="fp-dot" cx="465" cy="236" r="3.5"/><circle class="fp-dot fp-worried" cx="470" cy="80" r="3.5"/>
              <text class="fp-tag" x="118" y="24">LIKED</text>
              <text class="fp-tag" x="473" y="274">LIKED</text>
              <text class="fp-tag fp-worried" x="552" y="24" text-anchor="end">WORRIED</text>
            </g>
          </svg>
          <blockquote class="fig-quote"><span>Voice note · ${esc(brokerName())}</span>"Walked 310 Canal Street with Marcus Bell from Tessarine Biotech yesterday afternoon. He liked the lab benches and the loading dock, but he's worried the HVAC can't handle their freezers."</blockquote>
        </div>
        <div class="tb tb-4">
          <div class="tb-cell"><span class="tb-k">Contact</span><b>Marcus Bell</b></div>
          <div class="tb-cell"><span class="tb-k">When it happened</span><b>"yesterday afternoon"</b></div>
          <div class="tb-cell"><span class="tb-k">Recorded at</span><b>CRM clock, on yes</b></div>
          ${approval}
        </div>
      </figure>
      <p class="fig-note">Marrowby Commercial is fictional. Every name, deal and email is made up.</p></div>`;
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
      if (n === 3) { showSaved(); if (!isPhone()) requestAnimationFrame(() => { const box = $("#thread"); box.scrollTop = box.scrollHeight; }); }
    }
  }
  // Step 2: the badge, the card's header and its Confirm button all in view, above the phone sheet.
  // On a phone, when the card is taller than the room, its fields scroll inside the card. In free
  // chat a new card is scrolled into view the same way. Keyboard focus goes to the card's heading,
  // never to Confirm: a second Enter must not save a card nobody read.
  function showCard(focus) {
    requestAnimationFrame(() => {
      const card = S.step === 2 ? [...document.querySelectorAll(".rb.ring-card")].pop()
        : [...document.querySelectorAll(".rb")].filter((c) => c.querySelector("[data-confirm]")).pop();
      const box = $("#thread");
      if (!card) return;
      const bot = card.closest(".bot"), body = card.querySelector(".rb-body");
      body.style.maxHeight = ""; card.classList.remove("fit");
      const sheet = isPhone() ? ($("#story").offsetHeight || 0) : 0;
      const room = box.clientHeight - sheet - 12;
      const start = bot.offsetTop - 8;
      let end = card.offsetTop + card.offsetHeight + 8;
      if (end - start > room && S.step === 2) {
        body.style.maxHeight = Math.max(isPhone() ? 48 : 88, body.offsetHeight - (end - start - room)) + "px";
        card.classList.add("fit");
        end = card.offsetTop + card.offsetHeight + 8;
      }
      box.scrollTop = end - start > room ? end - room : start;
      if (focus && S.keyboard) card.querySelector(".rb-sum")?.focus({ preventScroll: true });
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
      return `<span class="skill">${icon("skill")}<span>${names.length > 1 ? "Skills" : "Skill"} used: <b>${esc(names.join(", "))}</b>${withRules ? `<span class="skill-extra"> + House rules</span>` : ""}</span></span>`;
    }
    if ((it.skills_earlier || []).length) return `<span class="skill none">${icon("skill")}<span>Using a skill loaded earlier</span></span>`;
    return `<span class="skill none">${icon("skill")}<span>No skill used</span></span>`;
  }
  // The title block: the bottom strip of a drawing. The time the broker stated (amber when it is
  // kept as words), the CRM's clock, and who approved it. A date with a warning is still a date.
  function statedBox(t) {
    if (!t || !t.text) return `<div class="time-box"><span>${esc(t ? t.label : "Stated time")}</span><b>None given</b><small>Left empty, not guessed</small></div>`;
    const exact = !!t.nice && !t.note;
    const small = exact ? `Broker's words. Saved as ${esc(t.nice)}` : "Broker's words. Vague, so no date set";
    return `<div class="time-box ${exact && !t.warning ? "exact" : "flagged"}"><span>${esc(t.label)}</span><b>"${esc(t.text)}"</b>
      <small>${small}</small>${t.warning ? `<small class="warn-line">Check: ${esc(t.warning)}</small>` : ""}</div>`;
  }
  const systemBox = (at, prepared) => `<div class="time-box system"><span>CRM clock</span><b>${at ? esc(day(at)) + ", " + esc(clock(at)) : "When you confirm"}</b>
    <small>${at || !prepared ? "Set by the system, never typed" : `Set by the system. Prepared ${esc(clock(prepared))}`}</small></div>`;
  function dueChip(t) {
    if (!t || !t.text) return `<span class="due">No date given</span>`;
    if (t.nice && !t.note) return `<span class="due ${t.warning ? "flagged" : "exact"}">Due ${esc(t.nice)}</span>`;
    return `<span class="due flagged">"${esc(t.text)}": kept as words</span>`;
  }
  // A stamp lands on what was decided: navy ink for a save, red ink for a refusal.
  const stamp = (kind, text, key) => {
    const a = anim(key, 1100);
    return `<span class="stamp stamp-${kind}${a.cls}"${a.style}>${text}</span>`;
  };
  function readback(card, ring, quiet) {
    const tasks = card.items.filter((it) => it.op === "create_task");
    const others = card.items.filter((it) => it.op !== "create_task");
    const note = others.find((it) => it.op === "create_note");
    const noteRows = note ? Object.fromEntries(note.rows) : {};
    const sameAsNote = (rows) => !!note && rows.For === noteRows.Contact && rows.Deal === (noteRows.Deal || "no deal");
    // The note's summary is the card's title, so it is not repeated as a row.
    const shown = (it) => it.rows.filter(([k, v]) => !(it.op === "create_note" && k === "Summary" && v.trim().toLowerCase() === card.summary.trim().toLowerCase()));
    const main = others.map((it) => `<div class="rb-item"><div class="rb-kind">${esc(it.heading)}</div>
        <dl class="rows">${shown(it).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
        ${it.lists.map(([k, vals]) => `<div class="rb-list"><b>${esc(k)}</b><ul>${vals.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("")}</div>`).join("");
    let side = "";
    if (tasks.length) {
      const allSame = tasks.every((t) => sameAsNote(Object.fromEntries(t.rows)));
      side += `<div class="rb-item"><div class="rb-kind">${tasks.length === 1 ? "Task" : `Tasks (${tasks.length})`}${allSame ? ", same contact and deal" : ""}</div>
        <ul class="rb-tasks">${tasks.map((t) => {
          const rows = Object.fromEntries(t.rows);
          return `<li><div class="rb-task-head"><span>${esc(rows.Task)}</span>${dueChip(t.time)}</div>
            ${sameAsNote(rows) ? "" : `<small>For ${esc(rows.For)} · Deal: ${esc(rows.Deal)}</small>`}${t.time && t.time.warning ? `<small class="warn-line">Check: ${esc(t.time.warning)}</small>` : ""}</li>`;
        }).join("")}</ul></div>`;
    }
    if ((card.flags || []).length) {
      side += `<div class="rb-item rb-flags"><div class="rb-kind">${icon("alert")}To check</div><ul>${card.flags.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>`;
    }
    const body = main && side ? `<div class="rb-col">${main}</div><div class="rb-col rb-side">${side}</div>` : `<div class="rb-col">${main || side}</div>`;
    const stated = others.filter((it) => it.time).map((it) => statedBox(it.time)).join("");
    const status = card.status;
    const n = card.items.length;
    const kicker = { pending: "What will be saved", committed: "Saved to the CRM", expired: "Expired, nothing saved", discarded: "Discarded, nothing saved" }[status] || "What will be saved";
    const pill = status === "pending" ? `<span class="pill pill-pending"><span class="pill-long">Waiting for your confirm</span><span class="pill-short">Not saved yet</span></span>`
      : status === "committed" ? "" : `<span class="pill pill-quiet">${status === "expired" ? "Expired" : "Discarded"}</span>`;
    const ids = `data-hash="${esc(card.hash)}"`;
    // The title block's one line names what to check that its own cells do not already show (a vague
    // "when it happened" is the amber cell itself), so on a phone every flag is in view above Confirm.
    const inCells = others.filter((it) => it.time && it.time.text).map((it) => `'${it.time.text}':`);
    const flags = (card.flags || []).filter((f) => !inCells.some((c) => f.startsWith(c)));
    const flagLine = flags.length ? `<div class="tb-flags">${icon("alert")}<span>To check: ${esc(flags[0])}${flags.length > 1 ? ` (and ${flags.length - 1} more)` : ""}</span></div>` : "";
    let foot;
    if (status === "pending") {
      foot = `<div class="times">${stated}${systemBox(null, card.proposed_at)}${flagLine}
        <div class="tb-cell tb-approve"><span>Approved by</span><div class="rb-actions">
          <button type="button" class="btn ${quiet ? "btn-secondary" : "btn-primary"}${ring ? " ring" : ""}" data-confirm="${esc(card.id)}" data-armed="${armed(card.id) ? 1 : 0}" ${ids}>${icon("check")}Confirm and save</button>
          <button type="button" class="btn btn-secondary" data-discard="${esc(card.id)}" ${ids}>Discard</button></div></div></div>`;
    } else if (status === "committed") {
      foot = `<div class="times">${stated}${systemBox(card.committed_at)}
        <div class="tb-cell tb-approve is-signed"><span>Approved by</span><b>${esc(brokerName())}</b><small>With the Confirm button</small>
          ${stamp("saved", `Saved · ${esc(clock(card.committed_at))}`, "saved:" + card.id)}</div></div>`;
    } else {
      foot = `<div class="rb-done off">${icon("x-circle")}<span>${status === "expired" ? "Expired after 30 minutes. Nothing was saved." : "Discarded. Nothing was saved."}</span></div>`;
    }
    const a = anim("rb:" + card.id, 700);
    return `<article class="rb${status === "committed" ? " is-saved" : status === "pending" ? "" : " is-off"}${ring ? " ring-card" : ""}${a.cls}"${a.style} aria-label="Read back: ${esc(card.summary)}">
      <div class="rb-head"><div class="rb-headline"><span class="rb-kicker">${kicker}<span class="rb-count"> · ${n} record${n === 1 ? "" : "s"}</span></span><h3 class="rb-sum" tabindex="-1">${esc(card.summary)}</h3></div>${pill}</div>
      <div class="rb-body${main && side ? " two" : ""}">${body}</div><div class="rb-foot">${foot}</div></article>`;
  }
  function renderChat() {
    const box = $("#thread");
    const items = S.view ? S.view.transcript : [];
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    const firstPendingCard = (() => {
      for (const it of items) for (const c of it.cards || []) if (c.status === "pending") return c.id;
      return null;
    })();
    const inStory = S.step !== "free";
    let html = `<div class="bot">${spark()}<div class="bot-head"><span class="bot-name">Claude</span></div>
      <div class="answer">Hi ${esc(brokerFirst())}. Paste a voice note after a call or a tour, or ask me to update a record, prep a meeting, draft an email or sum up the pipeline.</div></div>`;
    items.forEach((it) => {
      if (it.kind === "broker") {
        html += `<div class="out-row"><span class="sr-only">${esc(brokerName())}: </span><div class="bubble bubble-out" dir="auto">${esc(it.text)}</div></div>`;
      } else if (it.kind === "assistant") {
        // From step 4 on, Ravi's note keeps a quiet Confirm: the story is about what does not save.
        const cards = (it.cards || []).map((c) => readback(c, S.step === 2 && c.id === firstPendingCard,
          inStory && typeof S.step === "number" && S.step >= 4 && c.id === S.story.gateWrite)).join("");
        // A reply that brings a read back card: the card is the read back, so Claude's text shows two
        // lines and opens on request (a model may write the whole read back out again in prose).
        const key = (it.cards || []).length ? it.cards[0].id : "";
        const open = key && S.openReplies.has(key);
        const answer = key
          ? `<div class="answer clamp${open ? " open" : ""}" id="ans-${esc(key)}" dir="auto"><span class="sr-only">Claude: </span>${format(it.text)}</div>
             <button type="button" class="more-toggle" data-more="${esc(key)}" aria-controls="ans-${esc(key)}" aria-expanded="${open}">${open ? "Show less" : "Show Claude's full message"}</button>`
          : `<div class="answer" dir="auto"><span class="sr-only">Claude: </span>${format(it.text)}</div>`;
        html += `<div class="bot">${spark()}
          <div class="bot-head"><span class="bot-name">Claude</span><span class="tag">${it.mode === "live" ? "AI" : "Fixed rules"}</span>${badge(it)}</div>
          ${trace(it.steps, false)}
          ${answer}${cards}</div>`;
      } else if (it.kind === "notice") {
        html += `<div class="sys-line ${it.notice === "saved" ? "saved" : ""}">${icon(it.notice === "saved" ? "check-circle" : "x-circle", "i i-sm")}${esc(it.text)}</div>`;
      } else if (it.kind === "test") {
        const a = anim("test:" + it.at + it.write_id, 700);
        html += `<div class="event${it.refused ? "" : " let-through"}${a.cls}"${a.style}>${icon("shield")}<div class="event-text"><div class="event-head">${esc(it.text)}</div>
          <div class="event-body">${it.refused ? "The CRM's code said: " : ""}${esc(it.result)}</div></div>
          ${stamp(it.refused ? "refused" : "saved", it.refused ? "Refused" : "Saved", "stamp:" + it.at + it.write_id)}</div>`;
      } else if (it.kind === "system") {
        html += `<div class="sys-line">${icon("alert", "i i-sm")}${esc(it.text)}</div>`;
      } else if (it.kind === "working") {
        html += `<div class="bot">${spark()}<div class="working"><div class="working-head"><span class="dots"><i></i><i></i><i></i></span>Working on it</div>
          ${(it.steps || []).length ? stepList(it.steps) : ""}</div></div>`;
      }
    });
    const before = box.dataset.count || "";
    box.innerHTML = html;
    fitToggles(box);
    box.dataset.count = String(items.length);
    const lastBroker = [...box.querySelectorAll(".out-row")].pop();
    const lastKind = items.length ? items[items.length - 1].kind : "";
    // In free chat, a reply that brings a card is scrolled to like step 2 (showCard), once; after that
    // the chat keeps its place, so reading the card is not interrupted.
    const lastHasCard = lastKind === "assistant" && (items[items.length - 1].cards || []).some((c) => c.status === "pending");
    const newest = pending().length ? pending()[pending().length - 1].id : null;
    if (isPhone() && S.step !== "free" && S.step !== 2) box.scrollTop = box.scrollHeight;  // the newest item, just above the sheet
    else if (S.step === "free" && lastHasCard) { if (newest !== S.lastCard) { showCard(); S.lastCard = newest; } }
    else if ((lastKind === "assistant" || lastKind === "working") && lastBroker) box.scrollTop = Math.max(0, lastBroker.offsetTop - 12);
    else if (nearBottom || String(items.length) !== before) box.scrollTop = box.scrollHeight;
    if (S.step === 2) showCard();
    if (!newest) S.lastCard = null;
    document.body.classList.toggle("chat-started", items.some((it) => it.kind === "broker"));
    renderComposer();
  }
  // A toggle only where the clamped text has more to show.
  function fitToggles(root) {
    root.querySelectorAll(".more-toggle").forEach((b) => {
      const text = document.getElementById(b.getAttribute("aria-controls"));
      b.hidden = !!text && !text.classList.contains("open") && text.scrollHeight <= text.clientHeight + 1;
    });
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
    const a = anim("rec:" + first.write_id, 1200);
    const rows = records.map((r, i) => `<li style="--i:${i}"><span class="saved-kind">${r.kind === "note" ? "Note" : r.kind === "task" ? "Task" : esc(r.kind[0].toUpperCase() + r.kind.slice(1))}</span>
      <div><div class="saved-title">${esc(r.title)}</div>${r.contact ? `<small>${esc(r.contact)}</small>` : ""}</div>
      ${r.kind === "task" ? dueChip(r.time) : ""}</li>`).join("");
    return `<article class="card rec is-saved${ring ? " ring-card" : ""}${a.cls}"${a.style}><div class="rec-head">
      <div><div class="rec-title">Saved ${esc(what)}</div><div class="rec-sub">${esc((note || first).title)}</div></div>${stamp("saved", `Saved · ${esc(clock(first.recorded_at))}`, "recstamp:" + first.write_id)}</div>
      <div class="times">${systemBox(first.recorded_at)}${note && note.time ? statedBox(note.time) : ""}</div>
      <ul class="saved-list">${rows}</ul></article>`;
  }
  // The pipeline strip: open deals by stage, from this chat's copy of the CRM. The deal the
  // newest card touches is marked; a stage move waiting for a confirm marks where it would go.
  function pipeline(v) {
    const stages = (S.config?.stages || []).filter((x) => !x.startsWith("Closed"));
    if (!stages.length) return "";
    const SHORT = { "Proposal sent": "Proposal", "LOI signed": "LOI",
      "Lease negotiation": `<span class="pk-long">Negotiation</span><span class="pk-short">Neg.</span>` };
    const latest = [...(v.transcript || [])].reverse().find((t) => t.kind === "assistant");
    const touched = new Set(), moving = new Set();
    for (const card of latest ? latest.cards || [] : []) {   // only the newest reply's cards, not older waiting ones
      for (const c of card.changes || []) {
        if (c.deal_id) touched.add(c.deal_id);
        if (c.op === "update_deal_stage" && card.status === "pending") moving.add(c.stage);
      }
    }
    const deals = v.deals || [];
    const here = new Set(deals.filter((d) => touched.has(d.id)).map((d) => d.stage));
    const open = deals.filter((d) => stages.includes(d.stage)).length;
    const cells = stages.map((st) => {
      const n = deals.filter((d) => d.stage === st).length;
      const cls = here.has(st) ? " here" : moving.has(st) ? " moving" : "";
      const mark = here.has(st) ? `<em>This card</em>` : moving.has(st) ? `<em>Waiting</em>` : "";
      return `<li class="pipe-cell${cls}" title="${esc(st)}"><span class="pipe-k">${SHORT[st] || esc(st)}</span><b>${n}</b>${mark}<span class="sr-only"> ${esc(st)}: ${n} deal${n === 1 ? "" : "s"}${mark ? ", the deal on the newest card" : ""}</span></li>`;
    }).join("");
    return `<div class="pipe-head"><span>Pipeline · open deals</span><span>${open} open</span></div><ol class="pipe" aria-label="Open deals by stage">${cells}</ol>`;
  }
  function renderCRM() {
    const v = S.view || { pending: [], saved: [], drafts: [], log: [], metrics: {}, deals: [] };
    const m = v.metrics || {};
    const sc = $("#switch-count"); sc.hidden = !v.pending.length; sc.textContent = v.pending.length;
    const cost = $("#cost-line");
    cost.hidden = !m.live_calls;
    cost.innerHTML = m.live_calls ? `${icon("cpu", "i i-sm")}AI cost of this chat: <strong>${money(m.cost_usd)}</strong>` : "";
    $("#pipeline").innerHTML = pipeline(v);
    let html = "";
    if (v.pending.length) {
      html += `<div class="group-label">Waiting for a confirm</div>` + v.pending.map((c) => `<article class="card rec is-waiting"><div class="rec-head">
        <div><div class="rec-title">${esc(c.summary)}</div><div class="rec-sub">${c.items.length} record${c.items.length === 1 ? "" : "s"} · confirm it on the card in the chat</div></div>
        <span class="pill pill-pending">Not saved</span></div></article>`).join("");
    }
    // Newest save first; inside one save, the order it was read back in (the note, then its tasks).
    const writes = [...new Set(v.saved.map((r) => r.write_id))].reverse();
    if (writes.length) {
      html += `<div class="group-label">Saved in this demo</div>` + writes.map((w, i) => savedCard(v.saved.filter((r) => r.write_id === w), S.step === 3 && i === 0)).join("");
    }
    if (v.drafts.length) {
      html += `<div class="group-label">Email drafts (never sent)</div>` + v.drafts.map((d) => `<article class="card rec"><div class="rec-head">
        <div><div class="rec-title">${esc(d.subject)}</div><div class="rec-sub">To ${esc(d.to_name)} · in ${esc(brokerFirst())}'s mailbox</div></div><span class="pill pill-quiet">Draft, not sent</span></div></article>`).join("");
    }
    if (!v.pending.length && !writes.length && !v.drafts.length) {
      html += `<div class="empty"><h3>Nothing new yet</h3>
        <p>When Claude prepares a change, it waits for the broker's confirm. Saved notes and tasks appear here with the CRM's own time.</p></div>`;
    }
    html += `<details class="card fold" id="activity"${S.logOpen ? " open" : ""}><summary>
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
    return `<details class="card fold" id="hood"${S.hoodOpen ? " open" : ""}><summary>
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
    document.addEventListener("keydown", (e) => {
      if (e.repeat && (e.key === "Enter" || e.key === " ") && e.target.closest?.("[data-confirm]")) e.preventDefault();
    }, true);
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
        if (t.dataset.armed !== "1") return;   // the card just appeared: read it first
        act({ type: "confirm", write_id: t.dataset.confirm, hash: t.dataset.hash }).then((done) => { if (done) { announce("Saved to the CRM."); advance(); } });
      } else if (t.dataset.discard) act({ type: "discard", write_id: t.dataset.discard, hash: t.dataset.hash }).then(() => renderStory());
      else if (t.dataset.more) {
        const key = t.dataset.more, text = document.getElementById(t.getAttribute("aria-controls"));
        const open = !S.openReplies.has(key);
        if (open) S.openReplies.add(key); else S.openReplies.delete(key);
        text?.classList.toggle("open", open);
        t.setAttribute("aria-expanded", String(open));
        t.textContent = open ? "Show less" : "Show Claude's full message";
      } else if (t.dataset.logAll) { S.logAll = true; renderCRM(); }
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
      S.session = saved.session; S.step = saved.step ?? 0;
      // sessionStorage is the visitor's own: read numbers as numbers, whatever was put there
      const st = saved.story && typeof saved.story === "object" ? saved.story : {};
      S.story = { ...st, savedNow: Number(st.savedNow) || 0, pendingBeforeDana: Number(st.pendingBeforeDana) || 0,
        pendingAfterDana: Number(st.pendingAfterDana) || 0 };
      let kept = null;
      try { kept = await step({ type: "view" }); } catch { S.view = null; }
      if (!kept) { S.step = 0; S.story = {}; }  // a chat from another day or older rules: start over
    }
    if (!S.view) { await newChat(); S.step = 0; }
    render();
    motionReady = true;
  }
  init();
})();
