// Contoso KB Guru - web UI. Talks to the single Python `bridge` over QWebChannel.
// When run in a plain browser (no Qt), a mock bridge with sample data takes over so
// the same files render for design review / Playwright checks.
"use strict";
(function () {
  var B = null, MOCK = false, els = {}, sending = false;

  // ---------------- mock bridge (browser preview only) ----------------
  function sig() { var fns = []; return { connect: function (f) { fns.push(f); }, emit: function (a) { fns.forEach(function (f) { f(a); }); } }; }
  function mockBridge() {
    MOCK = true;
    var providers = {
      local: { display: "Local (on-prem)", default_model: "contoso-reasoning-qwen25-7b", models: { "Contoso Reasoning (Qwen2.5-7B)": "contoso-reasoning-qwen25-7b" } },
      claude: { display: "Claude", default_model: "claude-sonnet-4-6", models: { "Sonnet (smarter)": "claude-sonnet-4-6", "Haiku (fast / cheap)": "claude-haiku-4-5-20251001" } },
      openai: { display: "ChatGPT", default_model: "gpt-5.4", models: { "GPT-5.4": "gpt-5.4", "GPT-5.4-mini (fast / cheap)": "gpt-5.4-mini" } }
    };
    var chats = [
      { id: "c1", title: "drawdown margin duplication", ts: "2026-07-09T11:24" },
      { id: "c2", title: "Ticket #75919", ts: "2026-07-09T09:48" },
      { id: "c3", title: "How do I post a deal in TD?", ts: "2026-07-08T16:00" }
    ];
    var b = {
      answerReady: sig(), turnFailed: sig(), turnProgress: sig(), turnStopped: sig(), chatsChanged: sig(), _t: null,
      ping: function () { return Promise.resolve("pong"); },
      config_json: function () {
        var disp = {}, mbp = {}; for (var k in providers) { disp[k] = providers[k].display; mbp[k] = providers[k].models; }
        return Promise.resolve(JSON.stringify({ default_provider: "local", default_model: "contoso-reasoning-qwen25-7b",
          products: { api: "API", tradedesk: "TradeDesk", saleshub: "SalesHub", formflow: "FormFlow", web2: "Web2", web4: "Web4", other: "Other" },
          provider_display: disp, models_by_provider: mbp }));
      },
      list_chats: function () { return Promise.resolve(JSON.stringify(chats)); },
      search_chats: function (q) { q = (q || "").toLowerCase(); return Promise.resolve(JSON.stringify(chats.filter(function (c) { return c.title.toLowerCase().indexOf(q) >= 0; }))); },
      load_chat: function (id) { var c = chats.filter(function (x) { return x.id === id; })[0] || {}; return Promise.resolve(JSON.stringify({ id: id, title: c.title || "Chat", turns: [] })); },
      new_chat: function () { if (b._t) { clearTimeout(b._t); b._t = null; } },
      rename_chat: function () {}, delete_chat: function () {},
      set_provider: function () {}, set_model: function () {},
      stop: function () { if (b._t) { clearTimeout(b._t); b._t = null; } b.turnStopped.emit(); },
      send_message: function (text) {
        var num = (text.match(/\d{3,7}/) || [""])[0];
        var title = /ticket|bug|#/i.test(text) && num ? "Ticket #" + num : text.slice(0, 60);
        chats.unshift({ id: "m" + (chats.length + 1), title: title, ts: "now" });
        b.chatsChanged.emit();
        b.turnProgress.emit("searching tickets & KB");
        b._t = setTimeout(function () { b._t = null; b.answerReady.emit(JSON.stringify(mockAnswer(text))); }, 1600);
      }
    };
    return b;
  }
  function mockAnswer() {
    return {
      kind: "answer",
      markdown: "Drawdown margin duplication is a known **TD Client Server** issue: on a full drawdown of a multi-line forward deal, margin is calculated once per transaction line instead of once for the drawdown event. [Ticket #54000](https://portal.contoso.example/tickets/54000/edit)\n\n#### Root cause\nThe drawdown routine loops the transaction lines and applies the GBP-cost margin on each pass. [Ticket #54000](https://portal.contoso.example/tickets/54000/edit)\n\n#### Resolution\n1. Aggregate the lines before the margin step so margin is computed once against the total drawn amount. [Ticket #54000](https://portal.contoso.example/tickets/54000/edit)\n2. For partial drawdowns, recalc margin on the outstanding balance after each draw. [Ticket #45615](https://portal.contoso.example/tickets/45615/edit)\n\n**Where seen:** 2 tickets - Litware (#54000, resolved Aug 2024) and Monex USA (#45615, 2023). Most recent fix: #54000. Handled by jchen (CSQA), dana.",
      citations: [], chat_id: "c1",
      sources: [
        { kind: "ticket", ticket_id: "54000", title: "Full-drawdown margin duplicated across transaction lines", url: "https://portal.contoso.example/tickets/54000/edit", product: "tradedesk", created_at: "2024-08-22", resolved: true },
        { kind: "ticket", ticket_id: "45615", title: "Partial-drawdown margin differs from initial margin required", url: "https://portal.contoso.example/tickets/45615/edit", product: "tradedesk", created_at: "2023-05-10", resolved: true },
        { kind: "article", ticket_id: "", title: "Drawdowns & Margin - TradeDesk Dealing guide", url: "https://help.contoso.example/display/FX/Drawdowns", product: "tradedesk", created_at: "", resolved: null }
      ],
      debug: { model: "contoso-reasoning-qwen25-7b", tokens_in: 1240, tokens_out: 380, latency_ms: 2140, retrieved_ids: ["t1", "t2", "a1"] }
    };
  }

  // ---------------- helpers ----------------
  function $(id) { return document.getElementById(id); }
  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  function fmtTs(ts) { if (!ts) return ""; return String(ts).replace("T", " ").slice(0, 16); }
  function renderMarkdown(md) {
    var html = (window.marked ? marked.parse(String(md || ""), { breaks: true }) : esc(md));
    return window.DOMPurify ? DOMPurify.sanitize(html) : html;
  }

  // ---------------- rendering ----------------
  function renderConfig(cfg) {
    var prov = $("provider"), model = $("model"), product = $("product");
    prov.innerHTML = ""; product.innerHTML = "<option value=''>All products</option>";
    Object.keys(cfg.provider_display).forEach(function (pid) {
      var o = document.createElement("option"); o.value = pid; o.textContent = cfg.provider_display[pid];
      if (pid === cfg.default_provider) o.selected = true; prov.appendChild(o);
    });
    Object.keys(cfg.products).forEach(function (slug) {
      if (slug === "other") return;
      var o = document.createElement("option"); o.value = slug; o.textContent = cfg.products[slug]; product.appendChild(o);
    });
    els.modelsByProvider = cfg.models_by_provider;
    fillModels(cfg.default_provider, cfg.default_model);
    setDot(cfg.default_provider);
  }
  function fillModels(pid, selected) {
    var model = $("model"), map = (els.modelsByProvider || {})[pid] || {};
    model.innerHTML = "";
    Object.keys(map).forEach(function (label) {
      var o = document.createElement("option"); o.value = map[label]; o.textContent = label;
      if (map[label] === selected) o.selected = true; model.appendChild(o);
    });
  }
  function setDot(pid) {
    // Real readiness wiring lands with the onboarding wizard; local is always ready.
    var d = $("provdot"); d.className = "dot"; d.title = "Ready";
  }

  function renderChats(list, activeId) {
    var box = $("chats"); box.innerHTML = "";
    if (!list.length) { box.innerHTML = "<div class='src-empty' style='padding:8px 10px'>No chats yet.</div>"; return; }
    list.forEach(function (c) {
      var isTkt = /^Ticket #/.test(c.title || "");
      var row = document.createElement("div");
      row.className = "chat" + (isTkt ? " tkt" : "") + (c.id === activeId ? " active" : "");
      row.innerHTML = "<div class='txt'><div class='t'></div><div class='d'></div></div>"
        + "<div class='acts'>"
        + "<button data-act='rename' title='Rename'><svg width='13' height='13' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><path d='M12 20h9'/><path d='M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z'/></svg></button>"
        + "<button data-act='delete' title='Delete'><svg width='13' height='13' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><path d='M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14'/></svg></button>"
        + "</div>";
      row.querySelector(".t").textContent = c.title || "Untitled";
      row.querySelector(".d").textContent = fmtTs(c.ts);
      row.addEventListener("click", function (e) {
        var act = e.target.closest("[data-act]");
        if (act) { e.stopPropagation(); onChatAct(act.getAttribute("data-act"), c); return; }
        selectChat(c.id);
      });
      box.appendChild(row);
    });
  }

  function emptyState() {
    $("thread").innerHTML = "<div class='empty'><div class='big'>📘</div>"
      + "<div class='h'>Ask the KB Guru</div>"
      + "<div>Ask about a product, an error, or a ticket. Every answer cites the tickets &amp; KB it draws from.</div></div>";
    clearSources();
  }
  function clearSources() {
    $("srclist").innerHTML = "<div class='src-empty'>Sources for an answer will appear here.</div>";
    $("srccount").textContent = ""; $("hood").style.display = "none";
  }
  function bubble(role) {
    if ($("thread").querySelector(".empty")) $("thread").innerHTML = "";
    var t = document.createElement("div"); t.className = "turn " + role;
    var who = role === "user"
      ? "<span>You</span><span class='av me'>A</span>"
      : "<span class='av ai'>ds</span><span>KB Guru</span>";
    t.innerHTML = "<div class='bubble'><div class='who'>" + who + "</div><div class='msg'></div></div>";
    $("thread").appendChild(t); return t.querySelector(".msg");
  }
  function scrollBottom() { var th = $("thread"); th.scrollTop = th.scrollHeight; }

  function addUser(text) { var m = bubble("user"); m.textContent = text; scrollBottom(); }
  function showThinking(msg, subnote) {
    var m = bubble("ai"); m.dataset.thinking = "1";
    var html = "<div class='thinking'><span class='d'></span><span class='d'></span><span class='d'></span> " + esc(msg || "thinking") + "…</div>";
    if (subnote) html += "<div class='subnote'>" + esc(subnote) + "</div>";
    m.innerHTML = html;
    scrollBottom(); return m;
  }
  // The on-prem model loads on demand (cold start can take ~a minute on the AI PC).
  // Show — and escalate — a note so the wait reads as "loading", not "frozen".
  function setSubnote(text) {
    if (!els.thinkingEl) return;
    var s = els.thinkingEl.querySelector(".subnote");
    if (!s) { s = document.createElement("div"); s.className = "subnote"; els.thinkingEl.appendChild(s); }
    s.textContent = text;
  }
  function clearWakeTimers() {
    (els.wakeTimers || []).forEach(function (t) { clearTimeout(t); });
    els.wakeTimers = [];
  }
  function renderAnswer(m, payload) {
    if (payload.kind === "abstain" || payload.kind === "clarification") {
      m.classList.toggle("err", payload.kind === "abstain");
      m.innerHTML = "<div class='ans'>" + renderMarkdown(payload.markdown) + "</div>";
    } else {
      m.innerHTML = "<div class='ans'>" + renderMarkdown(payload.markdown) + "</div>";
    }
    renderSources(payload.sources || [], payload.debug || {});
    wireCitations(m, payload.sources || []);
    scrollBottom();
  }
  function renderSources(sources, debug) {
    var list = $("srclist"); list.innerHTML = "";
    $("srccount").textContent = sources.length ? String(sources.length) : "";
    if (!sources.length) { list.innerHTML = "<div class='src-empty'>No sources for this answer.</div>"; }
    sources.forEach(function (s) {
      // Built with DOM APIs (textContent / setAttribute) — no innerHTML with
      // metadata — so titles/URLs can't inject markup or break out of attributes.
      var isTkt = s.kind === "ticket";
      var safeUrl = (typeof s.url === "string" && /^https?:\/\//i.test(s.url)) ? s.url : "";
      var card = document.createElement("article"); card.className = "src";
      if (safeUrl) card.setAttribute("data-url", safeUrl);
      var r1 = document.createElement("div"); r1.className = "r1";
      var tag = document.createElement("span"); tag.className = "tag"; tag.textContent = isTkt ? "Ticket" : "KB";
      var idEl = document.createElement("span"); idEl.className = "id";
      idEl.textContent = isTkt ? ("#" + (s.ticket_id || "")) : (s.product ? prettyProduct(s.product) : "KB");
      r1.appendChild(tag); r1.appendChild(idEl);
      if (s.resolved === true || s.resolved === false) {
        var badge = document.createElement("span"); badge.className = "badge " + (s.resolved ? "ok" : "no");
        badge.textContent = s.resolved ? "✓ Resolved" : "Unresolved"; r1.appendChild(badge);
      }
      var title = document.createElement("div"); title.className = "title"; title.textContent = s.title || "(untitled)";
      var meta = document.createElement("div"); meta.className = "meta";
      if (s.product) { var p = document.createElement("span"); p.textContent = prettyProduct(s.product); meta.appendChild(p); }
      if (s.created_at) { var dt = document.createElement("span"); dt.className = "mono"; dt.textContent = s.created_at; meta.appendChild(dt); }
      card.appendChild(r1); card.appendChild(title); card.appendChild(meta);
      if (safeUrl) {
        var a = document.createElement("a"); a.className = "open";
        a.setAttribute("href", safeUrl); a.setAttribute("target", "_blank"); a.setAttribute("rel", "noopener");
        a.textContent = "Open " + (isTkt ? "ticket ↗" : "article ↗");
        card.appendChild(a);
      }
      list.appendChild(card);
    });
    var kv = $("hoodkv");
    kv.innerHTML = ""
      + row("Model", debug.model || "-")
      + row("Retrieval", "hybrid (vec+BM25)")
      + row("Context", (debug.retrieved_ids ? debug.retrieved_ids.length : 0) + " chunks")
      + row("Tokens", (debug.tokens_in || 0).toLocaleString() + " in · " + (debug.tokens_out || 0).toLocaleString() + " out")
      + row("Latency", (debug.latency_ms || 0).toLocaleString() + " ms");
    $("hood").style.display = "";
  }
  function row(k, v) { return "<dt>" + esc(k) + "</dt><dd>" + esc(v) + "</dd>"; }
  function prettyProduct(slug) {
    var map = { tradedesk: "TradeDesk", api: "API", saleshub: "SalesHub", formflow: "FormFlow", web2: "Web2", web4: "Web4", other: "Other" };
    return map[slug] || slug;
  }
  function wireCitations(msgEl, sources) {
    var cards = {};
    $("srclist").querySelectorAll(".src").forEach(function (c) { if (c.dataset.url) cards[c.dataset.url] = c; });
    msgEl.querySelectorAll("a[href]").forEach(function (a) {
      a.setAttribute("target", "_blank"); a.setAttribute("rel", "noopener");
      var card = cards[a.getAttribute("href")];
      if (!card) return;
      a.addEventListener("mouseenter", function () { card.classList.add("lit"); a.classList.add("lit"); });
      a.addEventListener("mouseleave", function () { card.classList.remove("lit"); a.classList.remove("lit"); });
      a.addEventListener("click", function () { card.scrollIntoView({ behavior: "smooth", block: "center" }); card.classList.add("lit"); setTimeout(function () { card.classList.remove("lit"); }, 1200); });
    });
  }

  // ---------------- actions ----------------
  function refreshChats() { B.list_chats().then(function (j) { renderChats(JSON.parse(j || "[]"), els.activeChat); }); }
  function selectChat(id) {
    B.load_chat(id).then(function (j) {
      var c = JSON.parse(j || "{}"); els.activeChat = id;
      refreshChats();
      $("thread").innerHTML = "";
      (c.turns || []).forEach(function (t) {
        if (t.role === "user") addUser(t.content || "");
        else { var m = bubble("ai"); m.innerHTML = "<div class='ans'>" + renderMarkdown(t.content || "") + "</div>"; wireCitations(m, []); }
      });
      if (!(c.turns || []).length) emptyState();
      clearSources();
    });
  }
  function onChatAct(act, c) {
    if (act === "delete") { B.delete_chat(c.id); }
    else if (act === "rename") {
      var t = window.prompt("Rename chat", c.title || "");
      if (t != null && t.trim()) B.rename_chat(c.id, t.trim());
    }
  }
  function newChat() {
    B.new_chat();
    clearWakeTimers();
    els.activeChat = null; els.thinkingEl = null; setSending(false);
    emptyState(); refreshChats(); $("input").focus();
  }

  function setSending(on) {
    sending = on;
    $("send").style.display = on ? "none" : "";
    $("stop").style.display = on ? "" : "none";
  }
  function send() {
    if (sending) return;
    var text = $("input").value.trim(); if (!text) return;
    setSending(true);
    addUser(text); $("input").value = ""; $("input").style.height = "auto";
    var isLocal = ($("provider").value === "local");
    var msg = isLocal ? "waking the on-prem model & searching KB"
                      : "searching tickets & KB, then asking the model";
    var note = isLocal ? "The on-prem model loads on demand — the first answer can take up to a minute. You can Stop anytime." : "";
    els.thinkingEl = showThinking(msg, note);
    clearWakeTimers();
    if (isLocal) {
      els.wakeTimers = [
        setTimeout(function () { setSubnote("Still waking the on-prem model on the AI PC — hang tight. You can Stop anytime."); }, 15000),
        setTimeout(function () { setSubnote("The on-prem model is taking longer than usual to wake. You can keep waiting or Stop and try again."); }, 45000),
      ];
    }
    B.send_message(text, $("product").value || "");
  }
  function onAnswer(j) {
    clearWakeTimers();
    var payload = JSON.parse(j || "{}");
    var m = els.thinkingEl || bubble("ai");
    renderAnswer(m, payload); els.thinkingEl = null;
    if (payload.chat_id) els.activeChat = payload.chat_id;
    setSending(false);
  }
  function onFailed(msg) {
    clearWakeTimers();
    var m = els.thinkingEl || bubble("ai"); m.classList.add("err");
    m.innerHTML = "<div class='ans'>" + esc(msg || "Something went wrong.") + "</div>";
    els.thinkingEl = null; setSending(false); scrollBottom();
  }
  function onStopped() {
    clearWakeTimers();
    if (els.thinkingEl) {
      els.thinkingEl.innerHTML = "<div class='ans' style='color:var(--ink-faint)'>Stopped. Your question is saved in the chat list.</div>";
      els.thinkingEl = null;
    }
    setSending(false);
  }
  function onProgress(stage) { if (els.thinkingEl) els.thinkingEl.querySelector(".thinking").lastChild.textContent = " " + stage + "…"; }

  // ---------------- boot ----------------
  function boot(bridge) {
    B = bridge; els.activeChat = null;
    B.answerReady.connect(onAnswer);
    B.turnFailed.connect(onFailed);
    B.turnProgress.connect(onProgress);
    if (B.turnStopped && B.turnStopped.connect) B.turnStopped.connect(onStopped);
    if (B.chatsChanged && B.chatsChanged.connect) B.chatsChanged.connect(refreshChats);

    B.config_json().then(function (j) { renderConfig(JSON.parse(j)); });
    refreshChats();
    emptyState();

    // rails
    var body = $("body");
    function setNav(open) { body.classList.toggle("nav-collapsed", !open); $("navToggle").setAttribute("aria-expanded", String(open)); }
    function setSrc(open) { body.classList.toggle("src-collapsed", !open); $("srcToggle").classList.toggle("on", open); $("srcToggle").setAttribute("aria-expanded", String(open)); }
    $("navToggle").addEventListener("click", function () { setNav(body.classList.contains("nav-collapsed")); });
    $("srcToggle").addEventListener("click", function () { setSrc(body.classList.contains("src-collapsed")); });
    setNav(window.innerWidth >= 1180); setSrc(window.innerWidth >= 760);

    // composer
    var input = $("input");
    input.addEventListener("input", function () { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; });
    input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
    $("send").addEventListener("click", send);
    $("stop").addEventListener("click", function () { B.stop(); });
    $("newchat").addEventListener("click", newChat);
    $("newtop").addEventListener("click", newChat);

    // config changes
    $("provider").addEventListener("change", function (e) { B.set_provider(e.target.value); fillModels(e.target.value); setDot(e.target.value); var mv = $("model").value; if (mv) B.set_model(mv); });
    $("model").addEventListener("change", function (e) { B.set_model(e.target.value); });

    // search (debounced)
    var t = null;
    $("chatsearch").addEventListener("input", function (e) {
      clearTimeout(t); var q = e.target.value;
      t = setTimeout(function () { B.search_chats(q).then(function (j) { renderChats(JSON.parse(j || "[]"), els.activeChat); }); }, 150);
    });
  }

  if (typeof QWebChannel !== "undefined" && window.qt && qt.webChannelTransport) {
    new QWebChannel(qt.webChannelTransport, function (channel) { boot(channel.objects.bridge); });
  } else {
    boot(mockBridge());
  }
})();
