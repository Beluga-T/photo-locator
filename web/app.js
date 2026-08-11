/* ═══════════════════════════════════════════════════════════════════
   Reverse Image Location — frontend

   Responsibilities, in the order they happen:
     intake   pick an image by click, drag-anywhere, or paste
     dispatch POST it to /api/locate, cancellable, with a live timer
     render   build the verdict / evidence / alternatives readout
     recall   keep the session's shots in a rail so they can be revisited

   Everything is built with createElement + textContent: model output is
   untrusted text and must never reach innerHTML. Every user-facing string
   is resolved through window.RIL.i18n (web/i18n.js) at render time, so
   the readout follows the header's language toggle. Motion 11 is optional —
   if it fails to load, or the visitor asked for reduced motion, every
   element is already in its final state and only the animation is lost.
   ═══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const SVG_NS = "http://www.w3.org/2000/svg";

  const dom = {
    frame: $("frame"),
    drop: $("drop"),
    file: $("file"),
    photo: $("photo"),
    fix: $("fix"),
    run: $("run"),
    runLabel: $("run-label"),
    cancel: $("cancel"),
    reset: $("reset"),
    readout: $("readout"),
    idlePanel: $("idle-panel"),
    plateDims: $("plate-dims"),
    cornerRead: $("corner-read"),
    cornerFmt: $("corner-fmt"),
    cornerSize: $("corner-size"),
    exifNote: $("exif-note"),
    railWrap: $("rail-wrap"),
    rail: $("rail"),
    hints: $("hints"),
    veil: $("veil"),
    toasts: $("toasts"),
    modelChip: $("model-chip"),
    modelName: $("model-name"),
    themeToggle: $("theme-toggle"),
    footMap: $("foot-map"),
    settings: $("settings"),
    settingsOpen: $("settings-open"),
    settingsClose: $("settings-close"),
    settingsSave: $("settings-save"),
    settingsRevert: $("settings-revert"),
    settingsTest: $("settings-test"),
    tokenInput: $("mapbox-token"),
    tokenHint: $("mapbox-hint"),
    modelHint: $("model-hint"),
    effortHint: $("effort-hint"),
    historyHint: $("history-hint"),
    historyClear: $("history-clear"),
    groupClaude: $("group-claude"),
    groupOpenai: $("group-openai"),
  };
  dom.tabs = Array.from(document.querySelectorAll(".tab"));
  dom.modelDot = dom.modelChip.querySelector(".chip__dot");

  const prefersReduced = matchMedia("(prefers-reduced-motion: reduce)");
  const M = window.Motion || null;

  /* i18n loads before this file and owns both dictionaries. The shim keeps the
   * app alive (showing raw keys) if that file somehow failed to load — the
   * same philosophy as the settings.js shim below: degrade, never throw. */
  const i18n = (window.RIL && window.RIL.i18n) || {
    lang: () => "zh",
    t: (key) => key,
    onChange: () => {},
    apply: () => {},
  };
  const t = (key, params) => i18n.t(key, params);

  /* In EN mode the Latin name leads when the model provided one; name_zh is
   * the fallback either way — its semantics are fixed in both languages.
   * Reads both shapes a place arrives in: {name_zh, name_en} off the API and
   * the already-plucked {zh, en} pairs headlineOf()/draftHeadline() build. */
  function placeName(place) {
    if (!place) return "";
    const zh = place.zh != null ? place.zh : place.name_zh || "";
    const en = place.en != null ? place.en : place.name_en || "";
    return i18n.lang() === "en" && en ? en : zh;
  }

  /** Run a Motion animation, or do nothing if Motion is unavailable/unwanted. */
  function anim(target, keyframes, options = {}) {
    if (!M || typeof M.animate !== "function" || prefersReduced.matches) return null;
    try {
      // motion@11 reads `ease`; the Motion One lineage read `easing`. Send both so
      // the curve survives either resolution path.
      const opts = { ...options };
      if (opts.ease && !opts.easing) opts.easing = opts.ease;
      if (opts.easing && !opts.ease) opts.ease = opts.easing;
      return M.animate(target, keyframes, opts);
    } catch {
      return null;
    }
  }

  const EASE_OUT = [0.22, 1, 0.36, 1];

  // ── Tiny DOM builder ─────────────────────────────────────────────────

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null && text !== "") node.textContent = String(text);
    return node;
  }

  function svg(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      node.setAttribute(key, String(value));
    }
    return node;
  }

  /* A live Mapbox instance holds a WebGL context and observers; hand it back
   * before dropping the nodes that own it. Separate from clear() because the
   * handoff to the final render detaches the draft's map first, and a node that
   * is already off the tree is exactly the one clear() can no longer find. */
  function dropView(node) {
    if (!node || typeof node.__rilDestroy !== "function") return;
    try {
      node.__rilDestroy();
    } catch {
      /* teardown is best-effort */
    }
  }

  function clear(node) {
    for (const view of node.querySelectorAll(".map")) dropView(view);
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function panel(labelText) {
    const box = el("section", "panel");
    if (labelText) box.append(el("span", "label", labelText));
    return box;
  }

  // ── Session state ────────────────────────────────────────────────────

  const state = {
    // The photo currently on the plate. A freshly picked one owns a blob: URL
    // and its File; one restored from the rail has neither — just the server's
    // image URL — which is why re-analysing a restored shot is disabled.
    shot: null,
    // Mirrors the server's index. The cap lives on the server (store.HISTORY_CAP),
    // not here: the browser is a view, not the owner.
    history: [],
    historyCount: 0,
    // The masked config the server has saved, as returned by /api/settings.
    saved: {},
    busy: false,
    controller: null,
    seq: 0,
    maxUploadMb: 12,
    // The token the backend handed down, and the browser-local override that
    // beats it. `mapboxToken` is always whichever one is actually in force.
    serverToken: "",
    mapboxToken: "",
    serverConfig: null,
  };

  function makeShot(file) {
    state.seq += 1;
    return { id: `live-${state.seq}`, file, url: URL.createObjectURL(file), payload: null };
  }

  /** Release a picked photo's blob URL. Server-backed history has none. */
  function releaseShot(shot) {
    if (!shot || shot === state.shot) return;
    if (shot.url && shot.url.startsWith("blob:")) URL.revokeObjectURL(shot.url);
  }

  // ── Server errors in the visitor's language ──────────────────────────

  /* Every API error body carries {code, message}, message in Chinese. zh mode
   * shows it verbatim. EN mode prefers the translated code — but only for the
   * codes listed here, whose server message is static: the ones left out
   * (bad_override, bad_json, bad_request, …) carry dynamic detail (the
   * offending field, the upstream's own words) that a canned English line
   * would erase, so those fall back to the server's message. */
  const ERR_CODES = new Set([
    "rate_limited", "empty", "too_large", "bad_image", "not_configured",
    "auth", "network", "upstream", "timeout", "refused", "truncated",
    "billing", "forbidden", "bad_response", "internal",
  ]);

  function errText(code, message) {
    if (i18n.lang() === "en" && ERR_CODES.has(code)) {
      // too_large is the one translated code with a variable — the limit is
      // config this frontend already holds.
      return t("err." + code, { mb: state.maxUploadMb });
    }
    return message;
  }

  // ── Toasts ───────────────────────────────────────────────────────────

  function toast(kind, message, ttl = 3600) {
    const node = el("div", "toast", message);
    node.dataset.kind = kind;
    dom.toasts.append(node);
    anim(node, { opacity: [0, 1], x: [16, 0] }, { duration: 0.26, ease: EASE_OUT });

    const drop = () => {
      const out = anim(node, { opacity: [1, 0], x: [0, 16] }, { duration: 0.22 });
      if (out && typeof out.finished?.then === "function") {
        out.finished.then(() => node.remove()).catch(() => node.remove());
      } else {
        node.remove();
      }
    };
    setTimeout(drop, ttl);
    node.addEventListener("click", drop);
  }

  // ── The spoken line ──────────────────────────────────────────────────

  /* #readout is a polite live region, but it stays aria-busy for as long as the
   * model is writing: unmuting it would read the whole card out again on each of
   * the fifteen-odd frames. The milestones that actually change the answer are
   * mirrored into this one off-screen line instead, so a screen-reader user
   * hears the card converge instead of nothing at all until the very end. */
  const announcer = el("div", "sr-live");
  announcer.setAttribute("role", "status");
  announcer.setAttribute("aria-live", "polite");
  document.body.append(announcer);

  let announced = "";

  function announce(message) {
    if (!message || message === announced) return;
    announced = message;
    announcer.textContent = message;
  }

  /** Drop the line between runs. Removing text is not itself announced. */
  function clearAnnounce() {
    announced = "";
    announcer.textContent = "";
  }

  // ── Theme ────────────────────────────────────────────────────────────

  function toggleTheme() {
    const root = document.documentElement;
    const current =
      root.dataset.theme ||
      (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    const next = current === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem("ril-theme", next);
    } catch {
      /* private browsing — the toggle still holds for this session */
    }
  }

  dom.themeToggle.addEventListener("click", toggleTheme);

  // ── The Mapbox token ─────────────────────────────────────────────────
  // Server-side config like everything else. It used to live in this browser's
  // localStorage, which meant opening the sheet on a second machine and saving
  // would blank the stored one — the form had nothing to put back.

  /** Take the token from /api/config and reflect it in the footer. */
  function applyToken() {
    state.mapboxToken = (state.serverConfig && state.serverConfig.mapboxToken) || "";
    if (dom.footMap) {
      dom.footMap.textContent = state.mapboxToken ? t("foot.map.on") : t("foot.map.off");
    }
    return state.mapboxToken;
  }

  function describeToken() {
    return applyToken() ? t("settings.token.set") : t("settings.token.unset");
  }

  // ── Settings: the model credentials ──────────────────────────────────

  /* web/settings.js validates a typed draft and resolves what the server says
   * is in force. The credentials themselves live on the server, not here. If
   * that file failed to load, this shim keeps the whole sheet working — the
   * backend validates everything again anyway — rather than throwing on the
   * first click. */
  const models = (window.RIL && window.RIL.settings) || {
    validate: () => [],
    describe: (server) => ({
      provider: (server && server.provider) || "",
      model: (server && server.model) || "",
      configured: Boolean(server && server.configured),
      source: server && server.configured ? "server" : "none",
      note: "",
    }),
    maskKey: (value) => (value ? "***" : ""),
  };

  /* Field id in the sheet -> the key the server stores it under.
   *
   * `secret` fields are WRITE-ONLY in this UI. The server masks them on read,
   * so echoing what it returned back into the input would save the mask over
   * the real value on the next click. They stay blank with the mask shown as
   * a placeholder, and are only sent when the user actually types something. */
  const MODEL_FIELDS = [
    ["provider", "provider", false],
    ["anthropic-key", "anthropic_api_key", true],
    ["anthropic-model", "anthropic_model", false],
    ["anthropic-effort", "anthropic_effort", false],
    ["openai-base", "openai_base_url", true],
    ["openai-key", "openai_api_key", true],
    ["openai-model", "openai_model", false],
  ];

  const SECRET_FIELDS = new Set(
    MODEL_FIELDS.filter(([, , secret]) => secret).map(([, key]) => key)
  );

  /** The form as the user left it, keyed the way the server wants. */
  function readDraft() {
    const draft = {};
    for (const [id, key] of MODEL_FIELDS) {
      const input = $(id);
      draft[key] = input ? input.value.trim() : "";
    }
    return draft;
  }

  /* What to PUT. Secrets left untouched are omitted entirely rather than sent
   * blank — the server reads an empty string as "delete this key", which would
   * wipe a working credential just because the user came in to change the
   * model name. Non-secret fields are always sent: the form shows their real
   * values, so whatever is there is what the user means. */
  function buildPatch(draft) {
    const patch = {};
    for (const [, key, secret] of MODEL_FIELDS) {
      const value = draft[key] || "";
      if (secret && !value) continue;
      patch[key] = value;
    }
    return patch;
  }

  /** A concrete value for the selects when the server has nothing stored. */
  function selectDefault(key) {
    const server = state.serverConfig || {};
    if (key === "provider") return "auto";
    if (key === "anthropic_effort") return String(server.effort || "medium");
    return "";
  }

  /* Paint the form from the server's masked view. Secrets do not go into the
   * value — the mask becomes the placeholder instead, so the field reads as
   * "something is saved here" while staying empty and therefore harmless to
   * submit untouched. */
  function fillForm(saved) {
    for (const [id, key, secret] of MODEL_FIELDS) {
      const input = $(id);
      if (!input) continue;
      const stored = String(saved[key] || "");
      if (secret) {
        input.value = "";
        input.placeholder = stored
          ? t("settings.secret.saved", { mask: stored })
          : input.dataset.blank || "";
      } else {
        input.value = stored || selectDefault(key);
      }
    }
  }

  /** Which provider the *unsaved form* would resolve to — the same rule the
   *  backend applies, so the dimming cannot contradict what actually runs. */
  function resolveDraft(draft) {
    const server = state.serverConfig || {};
    const chosen = draft.provider;
    if (chosen === "claude" || chosen === "openai") return chosen;
    // A secret field left blank means "keep what is stored", so the server's
    // presence flags are what decide, not the empty input.
    const hasGateway =
      (Boolean(draft.openai_base_url) || server.hasOpenaiBase === true) &&
      (Boolean(draft.openai_api_key) || server.hasOpenaiKey === true);
    return hasGateway ? "openai" : "claude";
  }

  // What each rung actually costs the user, in the terms they care about here.
  // Keys into the i18n dictionaries, resolved at display time so the hint
  // follows a language switch made while the sheet is open.
  const EFFORT_NOTE = {
    low: "settings.effortnote.low",
    medium: "settings.effortnote.medium",
    high: "settings.effortnote.high",
    xhigh: "settings.effortnote.xhigh",
    max: "settings.effortnote.max",
  };

  /** Dim the provider block that is not going to be used, and explain effort. */
  function updateGroups() {
    const draft = readDraft();
    const provider = resolveDraft(draft);
    dom.groupClaude.dataset.active = String(provider === "claude");
    dom.groupOpenai.dataset.active = String(provider === "openai");

    if (!dom.effortHint) return;
    const server = state.serverConfig || {};
    // The select always carries a concrete level now, so the hint only has to
    // explain what that level costs — plus a warning when the resolved provider
    // is the gateway, where effort has no equivalent and is simply ignored.
    const note = EFFORT_NOTE[draft.anthropic_effort] ? t(EFFORT_NOTE[draft.anthropic_effort]) : "";
    const scope = provider === "openai" ? t("settings.effortnote.na") : "";
    setHint(dom.effortHint, [scope, note].filter(Boolean).join(" "), scope ? "warn" : "info");
  }

  function setHint(node, text, kind) {
    node.textContent = text;
    node.dataset.kind = kind || "info";
  }

  // ── Talking to the server about saved settings ───────────────────────

  /** GET the saved config (secrets masked) and remember it for the form. */
  async function loadSaved() {
    try {
      const response = await fetch("/api/settings");
      if (!response.ok) throw new Error(String(response.status));
      const body = await response.json();
      state.saved = body.config || {};
      state.historyCount = Number(body.historyCount) || 0;
    } catch {
      state.saved = {};
      state.historyCount = 0;
    }
    return state.saved;
  }

  function describeModel() {
    const server = state.serverConfig || {};
    if (!server.configured) {
      return t("settings.model.none");
    }
    const saved = state.saved || {};
    const key = server.provider === "openai" ? saved.openai_api_key : saved.anthropic_api_key;
    const where = key ? t("settings.model.keysaved", { mask: key }) : t("settings.model.keyenv");
    return t("settings.model.using", { provider: server.provider, model: server.model, where });
  }

  /** The top-bar chip names whatever will actually run. */
  function refreshChip() {
    const server = state.serverConfig || {};
    dom.modelName.textContent = server.model || server.provider || t("chip.unset");
    dom.modelDot.dataset.state = server.configured ? "ok" : "off";
    dom.modelChip.title = server.configured
      ? `provider ${server.provider} · model ${server.model} · effort ${server.effort || "?"}`
      : t("chip.nokey");
  }

  function describeHistory() {
    const n = state.historyCount || 0;
    return n ? t("settings.history.some", { n }) : t("settings.history.none");
  }

  // ── Settings sheet: open / close / tabs ──────────────────────────────

  function selectTab(name) {
    for (const tab of dom.tabs) {
      const active = tab.id === `tab-${name}`;
      tab.setAttribute("aria-selected", String(active));
      const pane = $(tab.getAttribute("aria-controls"));
      if (pane) pane.hidden = !active;
    }
  }

  async function openSettings(tab) {
    await loadSaved();
    fillForm(state.saved);
    updateGroups();
    setHint(dom.modelHint, describeModel(), "info");
    if (dom.historyHint) setHint(dom.historyHint, describeHistory(), "info");
    // Not a secret, so unlike the API keys it round-trips as a real value.
    dom.tokenInput.value = String(state.saved.mapbox_token || "");
    setHint(dom.tokenHint, describeToken(), "info");
    selectTab(tab || "model");

    if (typeof dom.settings.showModal === "function") dom.settings.showModal();
    else dom.settings.setAttribute("open", "");
    anim(dom.settings, { opacity: [0, 1], y: [12, 0] }, { duration: 0.24, ease: EASE_OUT });
  }

  function closeSettings() {
    if (typeof dom.settings.close === "function") dom.settings.close();
    else dom.settings.removeAttribute("open");
  }

  /** Validate the Mapbox field on its own terms; returns true when it is safe. */
  function checkToken(token) {
    // A secret token in a browser is a real credential leak, not a style nit —
    // refuse it outright rather than storing it and warning afterwards.
    if (token.startsWith("sk.")) {
      setHint(dom.tokenHint, t("settings.token.sk"), "err");
      return false;
    }
    if (token && !token.startsWith("pk.")) {
      setHint(dom.tokenHint, t("settings.token.pk"), "warn");
      return false;
    }
    return true;
  }

  async function saveSettings() {
    const token = dom.tokenInput.value.trim();
    if (!checkToken(token)) {
      selectTab("map");
      return;
    }

    const draft = readDraft();
    const errors = (models.validate(draft) || []).filter((item) => item.level !== "warn");
    if (errors.length) {
      setHint(dom.modelHint, errors[0].message, "err");
      selectTab("model");
      return;
    }

    // The Mapbox token rides along in the same document — it is server-side
    // config now too, not a browser-local override.
    const patch = buildPatch(draft);
    patch.mapbox_token = token;

    dom.settingsSave.disabled = true;
    try {
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        const err = body && body.error;
        const message = err
          ? errText(err.code, err.message)
          : t("err.http", { status: response.status });
        setHint(dom.modelHint, message, "err");
        selectTab("model");
        return;
      }
      state.saved = (body && body.config) || {};
    } catch {
      setHint(dom.modelHint, t("settings.save.offline"), "err");
      return;
    } finally {
      dom.settingsSave.disabled = false;
    }

    await loadConfig(); // the effective view changed; re-read it rather than guess
    toast("ok", t("settings.save.ok"));
    closeSettings();
    // Redraw in place so a map or provider change shows without re-analysing —
    // but never over a stream in flight. The payload in hand is the *previous*
    // result, and rendering it would reset the draft and delete every partial
    // already on screen. The sheet is closed while busy; this is the backstop.
    if (state.shot && state.shot.payload && !state.busy) render(state.shot.payload);
  }

  async function revertSettings() {
    try {
      await fetch("/api/settings", { method: "DELETE" });
    } catch {
      toast("err", t("settings.revert.offline"));
      return;
    }
    await loadSaved();
    await loadConfig();
    fillForm(state.saved);
    dom.tokenInput.value = "";
    updateGroups();
    setHint(dom.modelHint, describeModel(), "info");
    setHint(dom.tokenHint, describeToken(), "info");
    toast("ok", t("settings.revert.ok"));
    if (state.shot && state.shot.payload && !state.busy) render(state.shot.payload);
  }

  /** Wipe the saved photos and results. Destructive, so it asks first. */
  async function clearHistory() {
    if (!window.confirm(t("settings.history.confirm"))) return;
    try {
      const response = await fetch("/api/history", { method: "DELETE" });
      const body = await response.json().catch(() => ({}));
      state.historyCount = 0;
      state.history = [];
      drawRail();
      setHint(dom.historyHint, describeHistory(), "info");
      toast("ok", t("settings.history.cleared", { n: body.removed || 0 }));
    } catch {
      toast("err", t("settings.history.offline"));
    }
  }

  /* The X-RIL-* headers are the "this request only" layer, and testing an
   * unsaved form is exactly what they are for: the server cannot know about a
   * draft nobody has saved yet. A secret left blank sends no header, so the
   * probe falls through to the stored credential — which is the right answer
   * for "I only changed the model name". */
  const DRAFT_HEADERS = {
    provider: "X-RIL-Provider",
    anthropic_api_key: "X-RIL-Anthropic-Key",
    anthropic_model: "X-RIL-Anthropic-Model",
    anthropic_effort: "X-RIL-Anthropic-Effort",
    openai_base_url: "X-RIL-OpenAI-Base",
    openai_api_key: "X-RIL-OpenAI-Key",
    openai_model: "X-RIL-OpenAI-Model",
  };

  // Headers are latin-1 on the wire; a stray full-width character from a paste
  // makes fetch() itself throw, which would read as "the backend is down".
  const SENDABLE = /^[\x20-\x7e]+$/;

  function draftHeaders(draft) {
    const headers = {};
    for (const [key, name] of Object.entries(DRAFT_HEADERS)) {
      const value = (draft[key] || "").trim();
      if (value && SENDABLE.test(value)) headers[name] = value;
    }
    return headers;
  }

  /** Has the form diverged from what the server has stored? */
  function isDirty(draft) {
    const saved = state.saved || {};
    for (const [, key, secret] of MODEL_FIELDS) {
      const value = draft[key] || "";
      // A blank secret means "leave it alone", not a change.
      if (secret ? Boolean(value) : value !== String(saved[key] || selectDefault(key))) return true;
    }
    return false;
  }

  /* /api/verify verdicts carry {code, message, model} with a Chinese message.
   * Same split as errText(): zh mode trusts the server's wording, EN mode
   * rebuilds the line from the code — every verify code is enumerable, and the
   * one variable worth keeping ({model}) rides along in the body. */
  const VERIFY_CODES = new Set([
    "ok", "not_configured", "auth", "rate_limited",
    "timeout", "network", "upstream", "unconfirmed",
  ]);

  function verifyText(body) {
    if (i18n.lang() === "en" && VERIFY_CODES.has(body.code)) {
      return t("verify." + body.code, { model: body.model || "?" });
    }
    return body.message;
  }

  /** Ask the backend to prove the credential works, without spending tokens. */
  async function testConnection() {
    const draft = readDraft();
    const errors = (models.validate(draft) || []).filter((item) => item.level !== "warn");
    if (errors.length) {
      setHint(dom.modelHint, errors[0].message, "err");
      selectTab("model");
      return;
    }

    dom.settingsTest.disabled = true;
    const restore = dom.settingsTest.textContent;
    dom.settingsTest.textContent = t("settings.testing");
    setHint(dom.modelHint, t("settings.connecting"), "info");

    try {
      const response = await fetch("/api/verify", { method: "POST", headers: draftHeaders(draft) });
      const body = await response.json().catch(() => null);
      if (!body) {
        setHint(dom.modelHint, t("settings.test.bad"), "err");
        return;
      }
      if (body.error) {
        setHint(
          dom.modelHint,
          (body.error.message && errText(body.error.code, body.error.message)) || t("settings.test.invalid"),
          "err"
        );
        return;
      }
      // The probe used the form as it stands, not what is stored — say so, or a
      // user who tests a new key and walks away will keep running the old one.
      const dirty = isDirty(draft);
      const suffix = body.ok && dirty ? t("settings.test.unsaved") : "";
      const message =
        verifyText(body) + (body.detail ? t("settings.test.detail", { detail: body.detail }) : "") + suffix;
      setHint(
        dom.modelHint,
        message,
        body.ok ? (dirty ? "warn" : "info") : body.code === "unconfirmed" ? "warn" : "err"
      );
    } catch {
      setHint(dom.modelHint, t("settings.test.offline"), "err");
    } finally {
      dom.settingsTest.disabled = false;
      dom.settingsTest.textContent = restore;
    }
  }

  dom.settingsOpen.addEventListener("click", () => openSettings("model"));
  dom.settingsClose.addEventListener("click", closeSettings);
  dom.settingsSave.addEventListener("click", saveSettings);
  dom.settingsRevert.addEventListener("click", revertSettings);
  dom.settingsTest.addEventListener("click", testConnection);
  if (dom.historyClear) dom.historyClear.addEventListener("click", clearHistory);

  for (const tab of dom.tabs) {
    tab.addEventListener("click", () => selectTab(tab.id.replace("tab-", "")));
  }

  // Reveal toggles for the two key fields.
  for (const button of document.querySelectorAll("[data-reveal]")) {
    button.addEventListener("click", () => {
      const input = $(button.dataset.reveal);
      if (!input) return;
      const hidden = input.type === "password";
      input.type = hidden ? "text" : "password";
      button.textContent = hidden ? t("settings.hide") : t("settings.reveal");
    });
  }

  // Typing in the provider or gateway fields re-dims the inactive block.
  for (const [id] of MODEL_FIELDS) {
    const input = $(id);
    if (input) input.addEventListener("input", updateGroups);
  }
  // <select> fires `input` in modern browsers, but `change` is the guaranteed
  // one — both selects drive the hint, so wire it explicitly.
  for (const id of ["provider", "anthropic-effort"]) {
    const select = $(id);
    if (select) select.addEventListener("change", updateGroups);
  }

  dom.tokenInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      saveSettings();
    }
  });
  // Clicking the backdrop closes it; clicks inside the sheet must not.
  dom.settings.addEventListener("click", (event) => {
    if (event.target === dom.settings) closeSettings();
  });

  // ── Backend handshake ────────────────────────────────────────────────

  async function loadConfig() {
    try {
      const response = await fetch("/api/config");
      if (!response.ok) throw new Error(String(response.status));
      const config = await response.json();
      state.maxUploadMb = config.maxUploadMb || state.maxUploadMb;
      state.serverConfig = config;
      applyToken();
      refreshChip();

      // Only nag when nobody at all can supply a key — a browser-local one is
      // a perfectly good answer and must not draw a warning.
      const view = models.describe(config);
      if (!view.configured) {
        toast("warn", t("toast.nokey"), 8000);
      }
    } catch {
      dom.modelName.textContent = t("chip.offline");
      dom.modelDot.dataset.state = "off";
      dom.modelChip.title = t("chip.offline.title");
      toast("err", t("toast.offline"), 7000);
    }
  }

  // ── Intake ───────────────────────────────────────────────────────────

  const FORMAT_NAMES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "image/gif": "GIF",
    "image/bmp": "BMP",
    "image/tiff": "TIFF",
  };

  function humanBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  function acceptFile(file) {
    if (!file) return;

    if (!file.type.startsWith("image/")) {
      toast("err", t("toast.notimage"), 5000);
      return;
    }
    if (file.size > state.maxUploadMb * 1024 * 1024) {
      toast(
        "err",
        t("toast.toolarge", { size: humanBytes(file.size), max: state.maxUploadMb }),
        6000
      );
      return;
    }

    const previous = state.shot;
    state.shot = makeShot(file);
    releaseShot(previous);

    dom.photo.onload = () => {
      dom.plateDims.textContent = `${dom.photo.naturalWidth} × ${dom.photo.naturalHeight}`;
    };
    dom.photo.src = state.shot.url;
    dom.photo.hidden = false;
    dom.drop.hidden = true;

    dom.cornerFmt.textContent = FORMAT_NAMES[file.type] || file.type.replace("image/", "").toUpperCase();
    dom.cornerSize.textContent = humanBytes(file.size);
    dom.cornerRead.hidden = false;

    dom.reset.hidden = false;
    dom.run.disabled = false;
    dom.runLabel.textContent = t("run.start");
    dom.fix.style.opacity = "0";
    dom.exifNote.hidden = true;
    markRailActive(null);
    showIdle();

    anim(dom.photo, { opacity: [0, 1], scale: [1.025, 1] }, { duration: 0.5, ease: EASE_OUT });
    anim(dom.frame, { borderColor: ["var(--fix)", "var(--line)"] }, { duration: 0.7 });
  }

  dom.drop.addEventListener("click", () => dom.file.click());

  dom.file.addEventListener("change", () => {
    acceptFile(dom.file.files && dom.file.files[0]);
    dom.file.value = ""; // allow re-picking the same file later
  });

  // Drag anywhere on the window, not just onto the plate. `depth` survives the
  // dragenter/dragleave storm that firing over child elements produces.
  let dragDepth = 0;

  window.addEventListener("dragenter", (event) => {
    if (!event.dataTransfer || state.busy) return;
    dragDepth += 1;
    dom.veil.classList.add("is-on");
  });

  window.addEventListener("dragover", (event) => {
    if (event.dataTransfer) event.preventDefault();
  });

  window.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) dom.veil.classList.remove("is-on");
  });

  window.addEventListener("drop", (event) => {
    event.preventDefault();
    dragDepth = 0;
    dom.veil.classList.remove("is-on");
    if (state.busy) return;
    const file = event.dataTransfer && event.dataTransfer.files[0];
    acceptFile(file);
  });

  document.addEventListener("paste", (event) => {
    if (state.busy || !event.clipboardData) return;
    for (const item of event.clipboardData.items) {
      if (item.type.startsWith("image/")) {
        acceptFile(item.getAsFile());
        event.preventDefault();
        return;
      }
    }
  });

  function resetPlate() {
    if (state.busy) return;
    const previous = state.shot;
    state.shot = null;
    releaseShot(previous);

    dom.photo.removeAttribute("src");
    dom.photo.hidden = true;
    dom.drop.hidden = false;
    dom.cornerRead.hidden = true;
    dom.reset.hidden = true;
    dom.run.disabled = true;
    dom.runLabel.textContent = t("run.start");
    dom.fix.style.opacity = "0";
    dom.plateDims.textContent = "—";
    dom.exifNote.hidden = true;
    markRailActive(null);
    showIdle();
  }

  dom.reset.addEventListener("click", resetPlate);

  // ── Readout: idle / working / error ──────────────────────────────────

  /* The invariant for everything below: whatever clears the readout also stops
   * the tick, because the tick writes into nodes that live in the readout.
   * showWorking() and ensureDraft() clear it and immediately install a new
   * painter; these two clear it and leave nothing ticking. */

  function showIdle() {
    stopWorking();
    clear(dom.readout);
    dom.readout.setAttribute("aria-busy", "false");
    dom.readout.append(dom.idlePanel);
  }

  function showError(code, title, message) {
    stopWorking();
    clear(dom.readout);
    dom.readout.setAttribute("aria-busy", "false");

    const box = panel(t("panel.error"));
    const alarm = el("div", "alarm");
    alarm.append(el("b", null, title), el("span", null, message));
    if (code) alarm.append(el("code", null, code));
    box.append(alarm);

    const acts = el("div", "acts");
    const retry = el("button", "mini", t("act.retry"));
    retry.type = "button";
    retry.addEventListener("click", run);
    acts.append(retry);
    box.append(acts);

    dom.readout.append(box);
    anim(box, { opacity: [0, 1], y: [10, 0] }, { duration: 0.3, ease: EASE_OUT });
  }

  // Dictionary keys, resolved when each line is painted: the rotation keeps
  // running across a language switch, and the next line lands translated.
  const PHASES = [
    "phase.terrain",
    "phase.text",
    "phase.road",
    "phase.infra",
    "phase.shadow",
    "phase.chain",
  ];

  // One 100ms tick for the whole request. The working panel starts it and the
  // provisional card takes it over when the first field lands: a second interval
  // would only be a second thing to leak into a node that has been removed, and
  // the two would disagree about how long the wait has been.
  let timerHandle = null;
  let phaseHandle = null;
  let clockStarted = 0;

  /** Seconds since this request went out — never restarted mid-wait. */
  function elapsed() {
    return (performance.now() - clockStarted) / 1000;
  }

  /** Hand the tick to `paint`, taking it away from whoever had it. */
  function tickInto(paint) {
    if (timerHandle) clearInterval(timerHandle);
    paint(); // paint once now rather than show a blank for the first 100ms
    timerHandle = setInterval(paint, 100);
  }

  function showWorking() {
    clear(dom.readout);
    dom.readout.setAttribute("aria-busy", "true");

    const box = panel(null);
    const working = el("div", "working");

    const head = el("div", "working__head");
    head.append(el("span", "label", t("panel.reading")));
    const timer = el("span", "working__timer", "0.0s");
    head.append(timer);

    const text = el("p", "working__text", t(PHASES[0]));

    const bones = el("div", "bones");
    bones.append(el("div", "bone bone--lg"));
    for (const width of [92, 74, 86, 58, 68, 40]) {
      const bone = el("div", "bone");
      bone.style.width = `${width}%`;
      bones.append(bone);
    }

    working.append(head, text, bones);
    box.append(working);
    dom.readout.append(box);
    anim(box, { opacity: [0, 1], y: [10, 0] }, { duration: 0.3, ease: EASE_OUT });

    clockStarted = performance.now();
    tickInto(() => {
      timer.textContent = `${elapsed().toFixed(1)}s`;
    });

    let phase = 0;
    stopPhases(); // tickInto() guards the clock; the rotation needs the same
    phaseHandle = setInterval(() => {
      phase = (phase + 1) % PHASES.length;
      const out = anim(text, { opacity: [1, 0], y: [0, -6] }, { duration: 0.18 });
      const swap = () => {
        // clearInterval cannot cancel a fade that has already started, and the
        // first partial can land inside those 180ms — by which time ensureDraft
        // has removed this panel. Writing the next phase into a node the
        // document no longer holds is a leak with nothing to show for it.
        if (!text.isConnected) return;
        text.textContent = t(PHASES[phase]);
        anim(text, { opacity: [0, 1], y: [6, 0] }, { duration: 0.22, ease: EASE_OUT });
      };
      if (out && typeof out.finished?.then === "function") {
        out.finished.then(swap).catch(swap);
      } else {
        swap();
      }
    }, 3800);
  }

  /** The rotating copy belongs to the working panel alone: the provisional card
   *  replaces that panel and says what is actually happening instead. */
  function stopPhases() {
    if (phaseHandle) clearInterval(phaseHandle);
    phaseHandle = null;
  }

  function stopWorking() {
    if (timerHandle) clearInterval(timerHandle);
    timerHandle = null;
    stopPhases();
  }

  // ── Readout: the verdict ─────────────────────────────────────────────

  const BAND_TEXT = { high: "band.high", medium: "band.medium", low: "band.low" };

  /** The band's display text; the untranslated fallback matches the old code. */
  function bandText(band) {
    return BAND_TEXT[band] ? t(BAND_TEXT[band]) : "confidence";
  }
  const GAUGE_R = 59;
  const GAUGE_LEN = Math.PI * GAUGE_R;
  const GAUGE_ARC = `M 7 68 A ${GAUGE_R} ${GAUGE_R} 0 0 1 125 68`;

  /* `entering` is false when a gauge already showing this number is being
   * rebuilt — the draft's has been sitting on it for twenty seconds, and the
   * sweep back to 0 and up again is the final render admitting it threw the
   * provisional card away. Same rule the evidence rows follow. */
  function buildGauge(confidence, band, entering = true) {
    const wrap = el("div", "gauge-wrap");
    wrap.dataset.band = band;

    const chart = svg("svg", { class: "gauge", viewBox: "0 0 132 74", "aria-hidden": "true" });
    chart.append(svg("path", { class: "gauge__track", d: GAUGE_ARC }));

    const value = svg("path", { class: "gauge__value", d: GAUGE_ARC });
    value.style.strokeDasharray = String(GAUGE_LEN);
    chart.append(value);

    const num = el("div", "gauge__num");
    const digits = document.createTextNode("");
    num.append(digits, el("sub", null, "/100"));

    wrap.append(chart, num, el("div", "gauge__label", bandText(band)));

    const target = GAUGE_LEN * (1 - Math.max(0, Math.min(100, confidence)) / 100);
    if (!entering) {
      value.style.strokeDashoffset = String(target);
      digits.textContent = String(confidence);
      return wrap;
    }

    value.style.strokeDashoffset = String(GAUGE_LEN);
    digits.textContent = "0";
    requestAnimationFrame(() => {
      value.style.strokeDashoffset = String(target);
      digits.textContent = String(confidence);

      if (!M || prefersReduced.matches) return;
      anim(value, { strokeDashoffset: [GAUGE_LEN, target] }, { duration: 1.0, ease: EASE_OUT });

      // Self-terminating: the last frame is the one that writes the real number,
      // so nothing has to be cancelled if the node leaves the document first.
      const started = performance.now();
      const tick = (now) => {
        const p = Math.min(1, (now - started) / 1000);
        digits.textContent = String(Math.round(confidence * (1 - Math.pow(1 - p, 3))));
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });

    return wrap;
  }

  function buildCoords(coordinates) {
    const box = el("div", "coords");
    box.append(el("span", "label label--dim", t("coords.label")));

    const lat = coordinates.lat.toFixed(4);
    const lon = coordinates.lon.toFixed(4);
    box.append(el("div", "coords__value", `${lat}, ${lon}`));
    box.append(el("div", "coords__radius", t("coords.radius", { km: Math.round(coordinates.radius_km) })));

    const links = el("div", "coords__links");

    const gmaps = el("a", "mini", "GOOGLE MAPS");
    gmaps.href = `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`;
    const osm = el("a", "mini", "OSM");
    osm.href = `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=11/${lat}/${lon}`;
    for (const link of [gmaps, osm]) {
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }

    const copy = el("button", "mini", t("coords.copy"));
    copy.type = "button";
    copy.addEventListener("click", () => copyText(`${lat}, ${lon}`, t("coords.copied")));

    links.append(gmaps, osm, copy);
    box.append(links);
    return box;
  }

  function buildGlobe(coordinates) {
    if (!window.RIL || typeof window.RIL.createGlobe !== "function" || !coordinates) return null;
    let node;
    try {
      node = window.RIL.createGlobe({
        lat: coordinates.lat,
        lon: coordinates.lon,
        radiusKm: coordinates.radius_km,
      });
    } catch {
      return null;
    }
    if (!node) return null;

    const wrap = el("div", "globe-wrap");
    wrap.append(node, el("span", "globe__cap", t("globe.cap")));
    anim(node, { opacity: [0, 1], rotate: [-14, 0], scale: [0.9, 1] }, { duration: 0.8, ease: EASE_OUT });
    return wrap;
  }

  /** Prefer a real Mapbox map; fall back to the schematic globe without a token. */
  function buildLocationView(coordinates, headline) {
    if (!coordinates) return null;

    if (state.mapboxToken && window.RIL && typeof window.RIL.createMap === "function") {
      try {
        const node = window.RIL.createMap({
          lat: coordinates.lat,
          lon: coordinates.lon,
          radiusKm: coordinates.radius_km,
          token: state.mapboxToken,
          label: headline,
        });
        if (node) {
          anim(node, { opacity: [0, 1], y: [10, 0] }, { duration: 0.5, ease: EASE_OUT });
          return node;
        }
      } catch {
        /* fall through to the globe */
      }
    }
    return buildGlobe(coordinates);
  }

  // ── Handing the draft's map to the final render ──────────────────────

  const RING_SOURCE = "ril-uncertainty"; // the source id map.js gives the circle
  const RING_VERTICES = 96;
  const EARTH_KM = 6371;

  /* Flying an existing map to a corrected fix means handing its circle a new
   * ring: map.js closes over the one it drew and offers no way to ask for
   * another short of building a second map, which is the blink this whole
   * section exists to avoid. Same closed-form spherical walk it does, left
   * unwrapped around the centre longitude for the same reason — normalising into
   * [-180, 180] tears any circle that straddles the antimeridian. */
  function ringFeature(lat, lon, radiusKm) {
    const rad = Math.PI / 180;
    // Exactly at a pole cos(lat) collapses and the ring's longitudes go arbitrary.
    const lat1 = Math.max(-89.9999, Math.min(89.9999, lat)) * rad;
    const lon1 = lon * rad;
    const angular = Math.max(0.1, radiusKm) / EARTH_KM;
    const ring = [];

    for (let i = 0; i <= RING_VERTICES; i += 1) {
      const bearing = (i / RING_VERTICES) * 2 * Math.PI;
      const lat2 = Math.asin(
        Math.sin(lat1) * Math.cos(angular) + Math.cos(lat1) * Math.sin(angular) * Math.cos(bearing)
      );
      const lon2 =
        lon1 +
        Math.atan2(
          Math.sin(bearing) * Math.sin(angular) * Math.cos(lat1),
          Math.cos(angular) - Math.sin(lat1) * Math.sin(lat2)
        );
      ring.push([lon2 / rad, lat2 / rad]);
    }
    return { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [ring] } };
  }

  /** The same fix, to the precision the panel actually prints. */
  function sameFix(a, b) {
    return (
      a.lat.toFixed(4) === b.lat.toFixed(4) &&
      a.lon.toFixed(4) === b.lon.toFixed(4) &&
      Math.round(a.radius_km) === Math.round(b.radius_km)
    );
  }

  /* Can the built view carry this fix? Unchanged numbers keep the node exactly
   * as it is. normalize() only clamps lat/lon and may raise the radius to its
   * floor, so a move is the uncommon case — and when it happens the live
   * instance is flown to the new centre rather than replaced. */
  function moveView(node, at, coordinates) {
    if (sameFix(at, coordinates)) return true;

    const map = node.__rilMap; // only the interactive tier has an instance
    if (!map || typeof map.easeTo !== "function") return false;
    try {
      // No source yet means the style is still loading, and map.js's own load
      // handler is about to draw the old ring and fit the camera to it. Nothing
      // here could stop that, so let this one be rebuilt instead.
      const source = map.getSource(RING_SOURCE);
      if (!source) return false;
      source.setData(ringFeature(coordinates.lat, coordinates.lon, coordinates.radius_km));
      map.easeTo({
        center: [coordinates.lon, coordinates.lat],
        zoom: window.RIL.zoomForRadius(coordinates.radius_km),
        duration: prefersReduced.matches ? 0 : 420,
      });
    } catch {
      return false; // a rebuilt map beats one drawing the wrong circle
    }
    return true;
  }

  /* The adopted node was built from the model's raw claim, so its footer may
   * still read the pre-floor radius or a coarser name than the answer settled
   * on. Rewriting those three stats is quieter than building a second map to say
   * the same thing differently. The globe has no such footer and skips this. */
  function retitleView(node, coordinates, headline) {
    const stats = node.querySelectorAll(
      ".map__foot .map__stat:not(.map__degraded):not(.map__stat--name)"
    );
    if (stats[0]) {
      stats[0].textContent = `${coordinates.lat.toFixed(4)}, ${coordinates.lon.toFixed(4)}`;
    }
    if (stats[1]) stats[1].textContent = `± ${Math.round(coordinates.radius_km)} KM`;

    // map.js only appends the name span when it was given a label, and the draft
    // builds its map the moment `coordinates` lands — which can be before any
    // place is nameable. Adopting that node without creating the span would lose
    // the place name for good, where the rebuild it replaced always showed it.
    let name = node.querySelector(".map__stat--name");
    if (!name && headline) {
      const foot = node.querySelector(".map__foot");
      if (foot) {
        name = el("span", "map__stat map__stat--name");
        foot.append(name);
      }
    }
    if (name) {
      name.textContent = headline || "";
      name.hidden = !headline;
    }
  }

  /* Take over the draft's map instead of building a second one. Tearing it down
   * would throw away a WebGL context and a loaded style at the exact moment the
   * answer arrives — the loudest tell in the whole handoff, and for a map that
   * has been sitting on the right place for twenty seconds. */
  function adoptLocationView(shown, coordinates, headline) {
    const node = shown.map || null;
    if (node && coordinates && shown.mapAt && moveView(node, shown.mapAt, coordinates)) {
      retitleView(node, coordinates, headline);
      return node;
    }
    // Not adopted, so the draft's instance is this render's debt to settle: it
    // is already off the tree, where clear() can no longer reach it.
    dropView(node);
    return buildLocationView(coordinates, headline);
  }

  // How the verdict is headlined depends on how far the model actually got.
  // Dictionary keys, not display text: resolved by t() wherever they surface.
  const PRECISION = {
    country: { label: "prec.country", note: "prec.country.note" },
    region: { label: "prec.region", note: "prec.region.note" },
    city: { label: "prec.city", note: "" },
    locality: { label: "prec.locality", note: "" },
  };

  // What the model writes when it could not tell — the marker, not UI copy.
  const UNKNOWN_NAME = "未确定";

  /* A partial place is the model's raw dict and carries no `known` flag —
   * normalize() adds that later — so both shapes are read the same way: a name
   * it was willing to write, that is not the one it writes for "I don't know". */
  function placeKnown(place) {
    return Boolean(
      place && place.known !== false && place.name_zh && place.name_zh !== UNKNOWN_NAME
    );
  }

  // Only the levels above the headline are worth repeating underneath it.
  const ADMIN_ABOVE = {
    locality: [["admin.country", "country"], ["admin.region", "region"], ["admin.city", "city"]],
    city: [["admin.country", "country"], ["admin.region", "region"]],
    region: [["admin.country", "country"]],
    country: [],
  };

  /* The chain under the headline. The draft and the final render both come
   * through here: two chains built to the same rule out of the same markup is
   * what keeps the handoff from changing that row's text — and its height —
   * under the reader's eye. Returns the node even when empty; the caller decides
   * whether an empty chain is hidden or never appended. */
  function buildAdmin(precision, places) {
    const admin = el("div", "verdict__admin");
    for (const [labelKey, key] of ADMIN_ABOVE[precision] || ADMIN_ABOVE.country) {
      const place = places[key];
      if (!placeKnown(place)) continue;
      const span = el("span");
      span.append(el("em", null, t(labelKey)), document.createTextNode(` ${placeName(place)}`));
      admin.append(span);
    }
    return admin;
  }

  /** The deepest place the backend published, which is what the headline shows. */
  function headlineOf(result) {
    switch (result.precision) {
      case "locality":
        return { zh: result.locality, en: result.city.name_en };
      case "city":
        return { zh: result.city.name_zh, en: result.city.name_en };
      case "region":
        return { zh: result.region.name_zh, en: result.region.name_en };
      default:
        return { zh: result.country.name_zh, en: result.country.name_en };
    }
  }

  /* `shown` is what the provisional card already had on screen: the number its
   * gauge settled on, and its live map with the fix that map was built for.
   * Both are carried over rather than rebuilt — a gauge that rewinds to 0 and a
   * map that blinks are the two loudest tells that the final render threw the
   * draft away. Empty on a restored history entry, which has no draft. */
  function buildVerdict(result, shown = {}) {
    const box = panel(t("panel.verdict"));
    const precision = PRECISION[result.precision] || PRECISION.country;
    const headline = headlineOf(result);

    const verdict = el("div", "verdict");

    const grade = el("div", "grade");
    grade.dataset.precision = result.precision;
    grade.append(el("span", "grade__dot"), el("span", null, t("verdict.precision", { level: t(precision.label) })));
    verdict.append(grade);

    // zh leads and the Latin name sits underneath; EN mode flips that, with
    // the Chinese demoted to the secondary line so no information is lost.
    const lead = placeName(headline) || t("verdict.unknown");
    const sub = i18n.lang() === "en" ? (headline.zh !== lead ? headline.zh : "") : headline.en;
    verdict.append(el("h2", "verdict__city", lead));
    if (sub) verdict.append(el("div", "verdict__latin", sub));

    const admin = buildAdmin(result.precision, result);
    if (admin.childElementCount) verdict.append(admin);

    if (precision.note) verdict.append(el("div", "verdict__locality", t(precision.note)));
    if (result.summary) verdict.append(el("p", "verdict__summary", result.summary));
    box.append(verdict);

    const row = el("div", "fixrow");
    row.append(
      result.coordinates ? buildCoords(result.coordinates) : el("div", "coords"),
      buildGauge(result.confidence, result.confidence_band, shown.gauge !== result.confidence)
    );
    box.append(row);

    const view = adoptLocationView(shown, result.coordinates, placeName(headline));
    if (view) box.append(view);

    return box;
  }

  /* One row on its own, because the stream paints these one at a time long
   * before the final result exists. Both paths call this, so the provisional
   * chain and the final one cannot drift into different markup — which is what
   * makes the swap at the end invisible. */
  /* The category is prompt.py's fixed Chinese enum — the request's `lang`
   * field changes the prose fields, never this one — so EN display maps the
   * known values here and shows anything unrecognised as the model wrote it.
   * The zh dictionary carries the enum strings verbatim, so zh is untouched. */
  const CATEGORY_KEYS = {
    "地形地貌": "cat.terrain",
    "植被": "cat.vegetation",
    "建筑风格": "cat.architecture",
    "道路与交通": "cat.road",
    "文字与标识": "cat.text",
    "车辆与车牌": "cat.vehicle",
    "气候与光照": "cat.climate",
    "基础设施": "cat.infra",
    "人文与服饰": "cat.culture",
    "其他": "cat.other",
  };

  function categoryText(raw) {
    return CATEGORY_KEYS[raw] ? t(CATEGORY_KEYS[raw]) : raw;
  }

  function evidenceRow(item) {
    const row = el("div", "ev");
    row.dataset.weight = item.weight;
    row.append(el("div", "ev__cat", categoryText(item.category)));
    const body = el("div", "ev__body");
    body.append(el("div", "ev__obs", item.observation));
    if (item.implication) body.append(el("div", "ev__imp", item.implication));
    row.append(body);
    return row;
  }

  /* `entering` is false when the draft already showed this chain: those rows are
   * on screen and under the user's eye, and fading them in again is exactly the
   * flash the progressive panel exists to avoid. */
  function buildEvidence(evidence, entering = true) {
    const box = panel(t("panel.evidence"));
    const list = el("div", "evidence");
    const rows = evidence.map((item) => evidenceRow(item));
    for (const row of rows) list.append(row);
    box.append(list);

    if (entering) {
      requestAnimationFrame(() => {
        rows.forEach((row, index) => {
          anim(row, { opacity: [0, 1], x: [-10, 0] }, { duration: 0.36, delay: 0.05 * index, ease: EASE_OUT });
        });
      });
    }
    return box;
  }

  function alternativeRow(item, entering = true) {
    const row = el("div", "alt");

    const left = el("div");
    left.append(el("div", "alt__name", item.city || item.region || item.country || t("alt.unnamed")));
    const where = [item.region, item.country].filter(Boolean).join(" · ");
    if (where) left.append(el("div", "alt__where", where));
    if (item.reason) left.append(el("div", "alt__why", item.reason));

    const score = el("div", "alt__score");
    score.append(el("div", "alt__num", `${item.likelihood}%`));
    const bar = el("div", "alt__bar");
    const fill = el("i");
    bar.append(fill);
    score.append(bar);

    // The bar is 0-wide in CSS, so the width has to be written either way —
    // only the sweep up to it is optional.
    const width = `${Math.max(0, Math.min(100, item.likelihood))}%`;
    if (entering) {
      requestAnimationFrame(() => {
        fill.style.width = width;
        anim(fill, { width: ["0%", width] }, { duration: 0.75, delay: 0.1, ease: EASE_OUT });
      });
    } else {
      fill.style.width = width;
    }

    row.append(left, score);
    return row;
  }

  function buildAlternatives(alternatives, notes, entering = true) {
    const box = panel(t("panel.alts"));
    const list = el("div", "alts");
    for (const item of alternatives) list.append(alternativeRow(item, entering));

    box.append(list);
    if (notes) box.append(el("p", "panel__foot", notes));
    return box;
  }

  function summaryText(result, meta) {
    const chain = [result.country, result.region, result.city]
      .filter((place) => place.known)
      .map((place) => placeName(place));
    if (result.locality) chain.push(result.locality);

    const precision = PRECISION[result.precision] || PRECISION.country;
    const lines = [
      t("export.verdict", { chain: chain.join(" / ") }),
      t("export.precision", { level: t(precision.label) }),
    ];
    if (result.coordinates) {
      lines.push(
        t("export.coords", {
          lat: result.coordinates.lat.toFixed(4),
          lon: result.coordinates.lon.toFixed(4),
          km: Math.round(result.coordinates.radius_km),
        })
      );
    }
    lines.push(t("export.confidence", { n: result.confidence, band: bandText(result.confidence_band) }));
    if (result.summary) lines.push("", result.summary);
    if (result.evidence.length) {
      lines.push("", t("export.evidence"));
      result.evidence.forEach((item, index) => {
        lines.push(`${index + 1}. [${categoryText(item.category)}] ${item.observation} → ${item.implication}`);
      });
    }
    if (result.alternatives.length) {
      lines.push("", t("export.alts"));
      for (const alt of result.alternatives) {
        lines.push(
          t("export.alt", {
            name: [alt.city, alt.region, alt.country].filter(Boolean).join(", "),
            pct: alt.likelihood,
            reason: alt.reason,
          })
        );
      }
    }
    if (result.notes) lines.push("", t("export.notes", { notes: result.notes }));
    lines.push("", `— ${meta.provider} / ${meta.model} · ${(meta.elapsedMs / 1000).toFixed(1)}s`);
    return lines.join("\n");
  }

  async function copyText(text, okMessage) {
    try {
      await navigator.clipboard.writeText(text);
      toast("ok", okMessage);
    } catch {
      toast("err", t("toast.clipboard"));
    }
  }

  function buildActions(payload) {
    const acts = el("div", "acts");

    const copySummary = el("button", "mini", t("act.copy"));
    copySummary.type = "button";
    copySummary.addEventListener("click", () =>
      copyText(summaryText(payload.result, payload.meta), t("act.copied"))
    );

    const downloadJson = el("button", "mini", t("act.download"));
    downloadJson.type = "button";
    downloadJson.addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = el("a");
      link.href = url;
      const slug = headlineOf(payload.result).en || "result";
      link.download = `location-${slug}.json`.replace(/\s+/g, "-");
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("ok", t("act.downloaded"));
    });

    const again = el("button", "mini", t("act.again"));
    again.type = "button";
    again.addEventListener("click", run);

    acts.append(copySummary, downloadJson, again);
    return acts;
  }

  function buildMeta(meta) {
    const row = el("div", "meta");
    for (const bit of [
      `${(meta.elapsedMs / 1000).toFixed(1)}s`,
      `${meta.provider} · ${meta.model}`,
      t("meta.sent", { w: meta.analyzedSize[0], h: meta.analyzedSize[1] }),
      t("meta.source", { w: meta.sourceSize[0], h: meta.sourceSize[1] }),
    ]) {
      row.append(el("span", null, bit));
    }
    return row;
  }

  // ── Progressive rendering ────────────────────────────────────────────
  /* The stream reports the answer as the model writes it, so the country can be
   * on screen while the evidence chain is still being composed. Three things
   * this must respect:
   *
   *   Partials are the model's raw claim. normalize() has not run, so its
   *   precision reconciliation may yet blank a city the model wrote — which is
   *   why these panels are visibly marked provisional and are thrown away whole
   *   when the real result lands.
   *
   *   Nothing streams during thinking, so this does not shorten the wait on a
   *   high-effort request; it shortens the wait after the model starts writing.
   *   That second half is most of the call: on a measured run the last coarse
   *   field lands at 8.5s and the answer at 29s, so everything below exists to
   *   keep those 20 seconds from looking like a hang.
   *
   * Two frame shapes come off the wire, and nothing else distinguishes them:
   *
   *   {field, value}          the whole field — country, precision, summary…
   *   {field, index, value}   element `index` of an array field
   *
   * An array field is only ever reported element by element; its whole value
   * never arrives as a partial, because the elements already carried it. */

  const DRAFT_WAIT = "draft.wait";

  /* The array fields, and how one element of each becomes a row. The builders
   * are the ones the final render uses — that is the whole reason they were
   * split out. `label` and `said` are dictionary keys, resolved when spoken. */
  const DRAFT_ARRAYS = {
    evidence: {
      label: "panel.evidence",
      list: "evidence",
      row: evidenceRow,
      said: "draft.said.evidence",
    },
    alternatives: {
      label: "panel.alts",
      list: "alts",
      row: alternativeRow,
      said: "draft.said.alts",
    },
  };

  const draft = {
    fields: {},
    precision: "", // the cap the model declared; a filter, never a delete
    panel: null, // the lead card: headline, admin chain, gauge, map, status line
    foot: null, // its last child; every later slot is inserted before it
    note: null, // what the model is writing now
    clock: null, // …and how long it has been at it
    // The verdict block's slots. They are built once and written in place: a
    // rebuilt headline is a headline that flashes, and it is the one thing on
    // this card the reader is actually looking at.
    wait: null,
    title: null,
    latin: null,
    admin: null,
    summary: null,
    map: null,
    mapAt: null, // the fix the map was built for, so the final render can adopt it
    gauge: null,
    gaugeValue: null, // …and the number it settled on, for the same reason
    // Per array field: {panel, list, rows}. `rows` is indexed exactly the way
    // the stream indexes it, so a re-reported element lands back on its own row
    // instead of being appended a second time.
    lists: { evidence: null, alternatives: null },
  };

  function resetDraft() {
    // The status line is repainted by an interval that writes into `note` and
    // `clock`. Those nodes go away with the panel, so the tick has to stop here
    // and not only in run()'s finally — otherwise the swap to the final render
    // leaves an interval painting into a node that has left the document.
    stopWorking();
    clearAnnounce();
    draft.fields = {};
    draft.precision = "";
    draft.panel = null;
    draft.foot = null;
    draft.note = null;
    draft.clock = null;
    draft.wait = null;
    draft.title = null;
    draft.latin = null;
    draft.admin = null;
    draft.summary = null;
    draft.map = null;
    draft.mapAt = null;
    draft.gauge = null;
    draft.gaugeValue = null;
    draft.lists = { evidence: null, alternatives: null };
  }

  /** Levels finer than the one the model declared, coarsest first. */
  const PRECISION_ORDER = ["country", "region", "city", "locality"];

  /* Every read of a place goes through here, so the declared precision acts as a
   * standing cap rather than a one-time trim. Deleting the finer fields once was
   * wrong twice over: `precision` can land after the name it caps (locality at
   * 7.8s, precision at 8.5s on the measured run — the headline was painted and
   * then walked backwards), and any later frame that re-reports the field would
   * put it straight back. An absent or unrecognised precision caps nothing. */
  function draftPlace(key) {
    const depth = PRECISION_ORDER.indexOf(draft.precision);
    if (depth >= 0 && PRECISION_ORDER.indexOf(key) > depth) return null;
    return draft.fields[key] || null;
  }

  /* The deepest place the draft has so far, mirroring headlineOf() — and saying
   * which level it came from, because the admin chain hangs off exactly that. */
  function draftHeadline() {
    const locality = draftPlace("locality");
    if (typeof locality === "string" && locality && locality !== UNKNOWN_NAME) {
      // Same as headlineOf(): a street name has no Latin form of its own, so the
      // line under it stays the city's.
      const city = draftPlace("city");
      return { level: "locality", zh: locality, en: (city && city.name_en) || "" };
    }
    for (const key of ["city", "region", "country"]) {
      const place = draftPlace(key);
      if (placeKnown(place)) return { level: key, zh: place.name_zh, en: place.name_en || "" };
    }
    return null;
  }

  /* What the model is writing right now, read as "the first thing that has not
   * arrived yet" — the fields come in schema order, so that is always true. A
   * pause under a phase name with a growing count reads as progress; the same
   * pause under a motionless card reads as a hang, which is the complaint. */
  function draftPhase() {
    const alternatives = draft.lists.alternatives;
    if (alternatives) return t("draft.phase.alts", { n: alternatives.list.childElementCount });
    const evidence = draft.lists.evidence;
    if (evidence) return t("draft.phase.evidence", { n: evidence.list.childElementCount });
    if (draft.fields.summary) return t("draft.phase.evidence0");
    if (typeof draft.fields.confidence === "number") return t("draft.phase.summary");
    return t("draft.phase.early");
  }

  function paintFoot() {
    if (!draft.note) return;
    draft.note.textContent = `${draftPhase()} · `;
    draft.clock.textContent = `${elapsed().toFixed(1)}s`;
  }

  /** The lead card, built by whichever frame arrives first. */
  function ensureDraft() {
    if (draft.panel) return;

    clear(dom.readout);
    dom.readout.setAttribute("aria-busy", "true");

    draft.panel = panel(t("panel.narrowing"));
    draft.panel.dataset.draft = "true";

    draft.note = el("span");
    draft.clock = el("span", "draft__clock");
    draft.foot = el("p", "panel__foot");
    draft.foot.append(draft.note, draft.clock);

    /* Fixed slots, written in place as the fields land, in the order the final
     * render uses. Rebuilding this block per frame is what made the headline
     * flash: its text is identical across the four frames after the city lands,
     * and re-animating settled text reads as a redraw, not as refinement. An
     * empty slot is [hidden], so it neither shows nor takes a flex gap. */
    const verdict = el("div", "verdict");
    draft.wait = el("div", "verdict__locality", t(DRAFT_WAIT));
    draft.title = el("h2", "verdict__city");
    draft.latin = el("div", "verdict__latin");
    draft.admin = el("div", "verdict__admin");
    draft.summary = el("p", "verdict__summary");
    for (const slot of [draft.title, draft.latin, draft.admin, draft.summary]) slot.hidden = true;
    verdict.append(draft.wait, draft.title, draft.latin, draft.admin, draft.summary);

    // The foot stays the last child: the gauge row and the map are inserted
    // before it as they arrive, so the status line is never stranded mid-card.
    draft.panel.append(verdict, draft.foot);
    dom.readout.append(draft.panel);
    anim(draft.panel, { opacity: [0, 1], y: [10, 0] }, { duration: 0.28, ease: EASE_OUT });

    // The working panel has just been cleared, so its rotating copy has nothing
    // left to write into. Its clock is taken over rather than restarted — the
    // elapsed seconds the user is reading must not jump back to 0.0s here.
    stopPhases();
    tickInto(paintFoot);
  }

  /* confidence and confidence_band land in the same chunk, so the gauge is built
   * from whichever of the two arrives first and the band is patched into the
   * node when it follows. Rebuilding on the second frame would restart the sweep
   * and the count-up — the same "never re-animate what is already on screen"
   * rule the evidence rows follow. A corrected confidence *number* is left to
   * the final render, which is about to overwrite this whole panel anyway. */
  function syncGauge() {
    const value = draft.fields.confidence;
    if (typeof value !== "number") return;
    const band = draft.fields.confidence_band || "";

    if (draft.gauge) {
      draft.gauge.dataset.band = band;
      const label = draft.gauge.querySelector(".gauge__label");
      if (label) label.textContent = bandText(band);
      return;
    }

    draft.gauge = buildGauge(value, band);
    draft.gaugeValue = value; // the final render checks this before re-animating
    announce(t("aria.confidence", { n: value }));
    // The same grid the final render uses, with the left cell left empty: the
    // coordinates are still unreconciled (normalize has not applied the radius
    // floor), and a "复制坐标" button on a number that is about to change is a
    // trap. The map below already says where the model thinks this is.
    const row = el("div", "fixrow");
    row.append(el("div", "coords"), draft.gauge);
    // Anchored above the map, because `coordinates` is written before
    // `confidence` and the map is therefore usually already there. The final
    // render orders it verdict → fixrow → map, and the draft has to agree or
    // the handoff swaps two blocks under the user's eye.
    draft.panel.insertBefore(row, draft.map || draft.foot);
  }

  /* Nothing here touches a node whose text has not changed. Nine whole-field
   * frames arrive after the first name, and the headline reads the same for all
   * of coordinates / confidence / confidence_band / summary — so the test for
   * "should this move" is the text itself, not which frame we are on. */
  function syncVerdict() {
    const headline = draftHeadline();
    // Same display rule as buildVerdict(): EN leads with the Latin name and
    // demotes the Chinese to the secondary line; zh is untouched.
    const lead = headline ? placeName(headline) : "";
    const sub = headline
      ? i18n.lang() === "en"
        ? headline.zh !== lead
          ? headline.zh
          : ""
        : headline.en
      : "";

    // Nothing nameable yet leaves the placeholder up — but the summary below
    // still lands, because a model that never names a place still explains why.
    //
    // "Not yet" and "not any more" both land here. The second is reachable two
    // ways: `precision` arrives and caps away the only level that had a name, or
    // the model re-reports a place as 未确定. Writing the slots in place made
    // that case silent — the old rebuild-every-frame code cleared the node, so a
    // retracted name simply vanished. Without this branch a street the app has
    // already decided not to stand behind stays on screen until the final frame.
    if (!headline) {
      if (!draft.title.hidden) announce(t("aria.unsettled"));
      draft.title.textContent = "";
      draft.title.hidden = true;
      draft.latin.textContent = "";
      draft.latin.hidden = true;
      draft.admin.hidden = true;
      draft.wait.hidden = false;
    } else {
      draft.wait.hidden = true;
      // Unconditional, not folded into the text check below: the branch above
      // may have hidden this slot while the text stayed the same, and a
      // headline that comes back must come back visible.
      draft.title.hidden = false;
      if (draft.title.textContent !== lead) {
        draft.title.textContent = lead;
        // The one motion worth keeping: the answer just got more precise.
        anim(draft.title, { opacity: [0, 1], y: [6, 0] }, { duration: 0.3, ease: EASE_OUT });
        announce(t("aria.provisional", { name: lead }));
      }

      if (draft.latin.textContent !== sub) draft.latin.textContent = sub;
      draft.latin.hidden = !sub;

      // Built by the same rule and out of the same markup as the final render's,
      // including the <em> labels — the row used to lose its city and gain those
      // labels at the swap, changing both its text and its height.
      const admin = buildAdmin(headline.level, {
        country: draftPlace("country"),
        region: draftPlace("region"),
        city: draftPlace("city"),
      });
      if (admin.textContent !== draft.admin.textContent) {
        draft.admin.replaceWith(admin);
        draft.admin = admin;
      }
      draft.admin.hidden = !draft.admin.childElementCount;
    }

    const summary = draft.fields.summary;
    if (typeof summary === "string" && summary && draft.summary.textContent !== summary) {
      draft.summary.textContent = summary;
      draft.summary.hidden = false;
      anim(draft.summary, { opacity: [0, 1], y: [6, 0] }, { duration: 0.3, ease: EASE_OUT });
    }
  }

  /* Coordinates arrive before the evidence chain, so the map can start loading
   * tiles while the model is still writing. Built once and remembered with the
   * fix it was built for: the final render adopts this node rather than standing
   * up a second WebGL context to show the same place. */
  function syncMap() {
    if (draft.map) return;
    const coords = draft.fields.coordinates;
    if (!coords || typeof coords.lat !== "number" || typeof coords.lon !== "number") return;

    const headline = draftHeadline();
    draft.mapAt = { lat: coords.lat, lon: coords.lon, radius_km: Number(coords.radius_km) || 25 };
    draft.map = buildLocationView(draft.mapAt, headline ? placeName(headline) : "");
    if (draft.map) draft.panel.insertBefore(draft.map, draft.foot);
    else draft.mapAt = null; // nothing was built, so there is nothing to adopt
  }

  function applyPartial(field, value) {
    draft.fields[field] = value;

    /* A whole-field frame for a field that streams element by element is the
     * server forwarding the reader's restart: the model opened a SECOND array
     * under a key it had already written, so every row painted from the first
     * one is about to be contradicted by the final parse. Nothing else sends a
     * whole value for these fields, so this is unambiguous. Drop the rows now
     * rather than leave the user reading entries that no longer exist. */
    const streamed = draft.lists[field];
    if (streamed && DRAFT_ARRAYS[field]) {
      clear(streamed.list);
      streamed.rows = [];
    }

    /* The model sometimes fills `locality` and then declares `precision: "city"`
     * — a street name it is not actually willing to stand behind. The server
     * sides with the more conservative claim, so the draft remembers the cap and
     * every read of a place is filtered through it. See draftPlace(). */
    if (field === "precision" && PRECISION_ORDER.includes(value)) draft.precision = value;

    ensureDraft();
    syncVerdict();
    syncGauge();
    syncMap();

    paintFoot(); // the phase just changed; do not wait up to 100ms to say so
  }

  /** The panel a streamed array lives in, built when its first element lands.
   *  Same label and same list markup as the final render, so the swap is quiet. */
  function ensureList(field, spec) {
    const existing = draft.lists[field];
    if (existing) return existing;

    const box = panel(t(spec.label));
    // Dashed like the lead card, but "more" rather than "true": only the lead
    // card breathes. Three borders pulsing out of phase reads as noise.
    box.dataset.draft = "more";
    const list = el("div", spec.list);
    box.append(list);
    dom.readout.append(box);
    anim(box, { opacity: [0, 1], y: [10, 0] }, { duration: 0.28, ease: EASE_OUT });

    const slot = { panel: box, list, rows: [] };
    draft.lists[field] = slot;
    // Once per list, not once per row: six "已写出 N 条" in nine seconds is the
    // spam that makes people turn a live region off.
    announce(t(spec.said));
    return slot;
  }

  /** One element of an array field: `{field, index, value}` off the wire. */
  function applyPartialItem(field, index, value) {
    const spec = DRAFT_ARRAYS[field];
    if (!spec || !value || typeof index !== "number" || index < 0) return;

    ensureDraft(); // in principle an element can beat every scalar field here
    const slot = ensureList(field, spec);
    const row = spec.row(value);
    const previous = slot.rows[index];

    if (previous && previous.parentNode === slot.list) {
      // A re-reported element is a correction, not a new row: swap it in place
      // and leave it alone visually, or the whole chain flickers every time the
      // model rewrites one line.
      slot.list.replaceChild(row, previous);
    } else {
      // `children[index]` is the row that currently holds this position, so an
      // element that arrives out of order still lands where it belongs.
      slot.list.insertBefore(row, slot.list.children[index] || null);
      // Only the row that just arrived animates. Re-animating the ones already
      // on screen is what makes a growing list look like it is being redrawn.
      anim(row, { opacity: [0, 1], x: [-10, 0] }, { duration: 0.36, ease: EASE_OUT });
    }

    slot.rows[index] = row;
    paintFoot(); // the count in the status line just went up
  }

  function render(payload) {
    // What the provisional card already had on screen, read before resetDraft()
    // forgets it. Those blocks must not fade in again: the final panels repaint
    // the same rows in the same place, and re-animating what the user is already
    // looking at is the one thing that would make the handoff visible.
    const shown = {
      verdict: Boolean(draft.panel),
      evidence: Boolean(draft.lists.evidence),
      alternatives: Boolean(draft.lists.alternatives),
      // The number the gauge settled on, and the live map with the fix it was
      // built for. buildVerdict() carries both over instead of rebuilding them.
      gauge: draft.gaugeValue,
      map: draft.map,
      mapAt: draft.mapAt,
    };
    // Off the tree before clear() runs: clear() reclaims every live map it can
    // find, and this one is about to be handed to the panel replacing it.
    if (shown.map) shown.map.remove();
    resetDraft();
    const { result, meta } = payload;

    clear(dom.readout);
    dom.readout.setAttribute("aria-busy", "false");

    const blocks = [[buildVerdict(result, shown), !shown.verdict]];
    if (result.evidence.length) {
      blocks.push([buildEvidence(result.evidence, !shown.evidence), !shown.evidence]);
    }
    if (result.alternatives.length) {
      const box = buildAlternatives(result.alternatives, result.notes, !shown.alternatives);
      blocks.push([box, !shown.alternatives]);
    } else if (result.notes) {
      const box = panel(t("panel.notes"));
      box.append(el("p", "panel__foot", result.notes));
      blocks.push([box, true]);
    }
    blocks.push([buildActions(payload), true], [buildMeta(meta), true]);

    // The stagger counts only the blocks that actually animate: a delay slot
    // spent on a block that was already there would read as a stall.
    let step = 0;
    for (const [block, entering] of blocks) {
      dom.readout.append(block);
      if (!entering) continue;
      anim(block, { opacity: [0, 1], y: [16, 0] }, { duration: 0.45, delay: step * 0.08, ease: EASE_OUT });
      step += 1;
    }

    dom.fix.style.opacity = "1";
    anim(dom.fix, { opacity: [0, 1], scale: [1.8, 1] }, { duration: 0.55, delay: 0.1, ease: EASE_OUT });

    if (meta.exifGps) {
      dom.exifNote.textContent = t("exif.note", {
        lat: meta.exifGps.lat.toFixed(4),
        lon: meta.exifGps.lon.toFixed(4),
      });
      dom.exifNote.hidden = false;
      anim(dom.exifNote, { opacity: [0, 1] }, { duration: 0.4, delay: 0.3 });
    } else {
      dom.exifNote.hidden = true;
    }
  }

  // ── Session rail ─────────────────────────────────────────────────────

  /* The rail is now a view of what the server has on disk, not of this tab's
   * memory. Every entry is {id, payload, media_type, size_bytes, created_at},
   * and its image comes from /api/history/<id>/image — so a reload, a second
   * tab, or a restart of the program all show the same history. */

  function markRailActive(shotId) {
    for (const item of dom.rail.children) {
      item.setAttribute("aria-current", String(item.dataset.shot === String(shotId)));
    }
  }

  function shotImageUrl(id) {
    return `/api/history/${encodeURIComponent(id)}/image`;
  }

  async function loadHistory() {
    try {
      const response = await fetch("/api/history");
      if (!response.ok) throw new Error(String(response.status));
      const body = await response.json();
      state.history = Array.isArray(body.shots) ? body.shots : [];
    } catch {
      state.history = []; // a failure here must not take the analysis flow down
    }
    state.historyCount = state.history.length;
    drawRail();
  }

  function restoreShot(shot) {
    if (state.busy || !shot.payload) return;
    // The live `state.shot` holds a File for re-analysis; a restored one only
    // has a server-side image, so re-running it means picking the photo again.
    state.shot = { id: shot.id, file: null, url: shotImageUrl(shot.id), payload: shot.payload };
    dom.photo.src = state.shot.url;
    dom.photo.hidden = false;
    dom.drop.hidden = true;
    dom.cornerFmt.textContent = FORMAT_NAMES[shot.media_type] || "IMAGE";
    dom.cornerSize.textContent = humanBytes(shot.size_bytes || 0);
    dom.cornerRead.hidden = false;
    dom.reset.hidden = false;
    dom.run.disabled = true;
    dom.runLabel.textContent = t("run.review");
    render(shot.payload);
    markRailActive(shot.id);
  }

  function drawRail() {
    clear(dom.rail);
    for (const shot of state.history) {
      if (!shot || !shot.payload || !shot.payload.result) continue;
      const item = el("button", "rail__item");
      item.type = "button";
      item.dataset.shot = String(shot.id);
      item.setAttribute("role", "listitem");

      const result = shot.payload.result;
      const where = placeName(headlineOf(result)) || t("verdict.unknown");
      item.title = `${where} · ${result.confidence}/100`;
      item.setAttribute("aria-label", t("rail.aria", { where, n: result.confidence }));

      const thumb = el("img", "rail__thumb");
      thumb.src = shotImageUrl(shot.id);
      thumb.alt = "";
      thumb.loading = "lazy";

      const badge = el("span", "rail__badge", String(result.confidence));
      badge.dataset.band = result.confidence_band;

      item.append(thumb, badge);
      item.addEventListener("click", () => restoreShot(shot));
      dom.rail.append(item);
    }

    dom.railWrap.hidden = dom.rail.childElementCount === 0;
    markRailActive(state.shot ? state.shot.id : null);

    const first = dom.rail.firstElementChild;
    if (first) anim(first, { opacity: [0, 1], scale: [0.85, 1] }, { duration: 0.35, ease: EASE_OUT });
  }

  // ── Dispatch ─────────────────────────────────────────────────────────

  function setBusy(on) {
    state.busy = on;
    dom.run.disabled = on || !state.shot;
    dom.reset.disabled = on;
    // Saving or reverting redraws the readout, and mid-analysis the readout
    // belongs to the stream. Shut the door rather than police every exit.
    dom.settingsOpen.disabled = on;
    dom.cancel.hidden = !on;
    dom.frame.classList.toggle("is-working", on);
    dom.runLabel.textContent = on
      ? t("run.busy")
      : state.shot && state.shot.payload
        ? t("run.again")
        : t("run.start");
    for (const item of dom.rail.children) item.disabled = on;
  }

  /* Read an SSE body off a fetch stream.
   *
   * EventSource cannot be used here: it is GET-only, and this request carries a
   * multipart image. Parsing the wire format by hand is a few lines — frames are
   * separated by a blank line, and a frame is `event:` plus one or more `data:`
   * lines. A chunk boundary can fall anywhere, so the tail is carried over. */
  async function* readEvents(response, signal) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let split;
        while ((split = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);

          let name = "message";
          const data = [];
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) name = line.slice(6).trim();
            else if (line.startsWith("data:")) data.push(line.slice(5).trim());
          }
          if (!data.length) continue;
          try {
            yield [name, JSON.parse(data.join("\n"))];
          } catch {
            /* a frame we cannot parse is not worth killing the stream over */
          }
        }
      }
    } finally {
      // Abort mid-stream leaves the reader open otherwise, and the request
      // stays pending until the tab is closed.
      if (signal && signal.aborted) reader.cancel().catch(() => {});
    }
  }

  async function run() {
    if (!state.shot || state.busy || !state.shot.file) return;

    const shot = state.shot;
    state.controller = new AbortController();
    setBusy(true);
    dom.fix.style.opacity = "0";
    dom.exifNote.hidden = true;
    resetDraft();
    showWorking();

    const body = new FormData();
    body.append("image", shot.file, shot.file.name || "upload.jpg");
    // The backend threads this into the prompt so the model writes its prose
    // (summary, observations, reasons, notes) in the page's current language.
    // name_zh / name_en keep their fixed semantics either way.
    body.append("lang", i18n.lang());

    const fail = (code, message) => {
      showError(code, t("err.title"), message);
      toast("err", message, 6000);
    };

    try {
      // No credential headers: the server holds the config now. The X-RIL-*
      // layer still exists for direct API callers and for the settings sheet's
      // "test connection", which probes a draft nobody has saved yet.
      const response = await fetch("/api/locate/stream", {
        method: "POST",
        body,
        signal: state.controller.signal,
      });

      if (!response.ok || !response.body) {
        fail(`http_${response.status}`, t("err.http.body", { status: response.status }));
        return;
      }

      let payload = null;
      for await (const [name, data] of readEvents(response, state.controller.signal)) {
        if (name === "partial") {
          // An `index` means this is one element of an array field; without it
          // the value is the whole field. The working panel steps aside inside
          // these two — they take its clock over rather than stop it.
          if (typeof data.index === "number") applyPartialItem(data.field, data.index, data.value);
          else applyPartial(data.field, data.value);
        } else if (name === "error") {
          // A server body: Chinese message, translated by code where possible.
          fail(data.code || "internal", errText(data.code || "internal", data.message || t("err.internal")));
          return;
        } else if (name === "result") {
          payload = data;
        }
      }

      if (!payload) {
        fail("bad_response", t("err.stream"));
        return;
      }

      shot.payload = payload;
      if (payload.meta && payload.meta.shotId) shot.id = payload.meta.shotId;
      render(payload);
      // The server just wrote this shot; re-read rather than guess what the
      // index looks like after eviction.
      loadHistory();
      toast(
        "ok",
        t("toast.done", {
          where: placeName(headlineOf(payload.result)) || t("verdict.unknown"),
          n: payload.result.confidence,
        }),
        4200
      );
    } catch (error) {
      if (error && error.name === "AbortError") {
        showIdle();
        toast("warn", t("toast.cancelled"));
        return;
      }
      showError("network", t("err.network.title"), t("err.network.body"));
      toast("err", t("toast.netfail"), 5000);
    } finally {
      stopWorking();
      resetDraft();
      state.controller = null;
      setBusy(false);
    }
  }

  dom.run.addEventListener("click", run);
  dom.cancel.addEventListener("click", () => {
    if (state.controller) state.controller.abort();
  });

  // ── Keyboard ─────────────────────────────────────────────────────────

  function typingInto(target) {
    return (
      target instanceof HTMLElement &&
      (target.isContentEditable || target.closest("input, textarea, select"))
    );
  }

  document.addEventListener("keydown", (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey || typingInto(event.target)) return;
    // While the settings sheet is open it owns the keyboard, including Escape.
    if (dom.settings.open) return;

    if (event.key === "Enter") {
      // Let a focused button handle its own Enter.
      if (event.target instanceof HTMLElement && event.target.closest("button, a")) return;
      if (state.shot && !state.busy) {
        event.preventDefault();
        run();
      }
      return;
    }
    if (event.key === "Escape" && state.busy && state.controller) {
      state.controller.abort();
      return;
    }
    const key = event.key.toLowerCase();
    if (key === "r" && !state.busy) {
      event.preventDefault();
      resetPlate();
    } else if (key === "t") {
      event.preventDefault();
      toggleTheme();
    }
  });

  // ── Language switches ────────────────────────────────────────────────

  /* i18n.apply() has already re-annotated the static chrome by the time this
   * runs (set() notifies listeners last); what is left is every line whose
   * text depends on runtime state. A finished result re-renders in the new
   * language — the model-written prose inside it keeps the language it was
   * generated in until the next run, which also sends the new `lang` field.
   * An in-flight draft card is deliberately left alone: repainting a live
   * stream would mix two languages mid-card, so it keeps its language until
   * the next run. An error panel likewise stays: there is no payload to
   * rebuild it from. */
  i18n.onChange(() => {
    refreshChip();
    applyToken();
    if (dom.settings.open) {
      fillForm(state.saved);
      updateGroups();
      setHint(dom.modelHint, describeModel(), "info");
      setHint(dom.tokenHint, describeToken(), "info");
      if (dom.historyHint) setHint(dom.historyHint, describeHistory(), "info");
      // apply() reset every reveal button to "Show"; restate the ones whose
      // input is actually revealed right now.
      for (const button of document.querySelectorAll("[data-reveal]")) {
        const input = $(button.dataset.reveal);
        if (input && input.type === "text") button.textContent = t("settings.hide");
      }
    }
    if (state.busy) return;
    dom.runLabel.textContent = state.shot
      ? state.shot.file
        ? state.shot.payload
          ? t("run.again")
          : t("run.start")
        : t("run.review")
      : t("run.start");
    drawRail();
    // …unless an error panel is on screen: repainting the stale payload would
    // silently replace the failure the user is reading about.
    if (state.shot && state.shot.payload && !dom.readout.querySelector(".alarm")) {
      render(state.shot.payload);
    }
  });

  // ── Entrance ─────────────────────────────────────────────────────────

  function entrance() {
    const groups = [
      [document.querySelector(".bar"), 0],
      [document.querySelector(".thesis"), 0.06],
      [document.querySelector(".plate"), 0.14],
      [document.querySelector(".readout"), 0.2],
      [document.querySelector(".foot"), 0.28],
    ];
    for (const [node, delay] of groups) {
      if (node) anim(node, { opacity: [0, 1], y: [14, 0] }, { duration: 0.6, delay, ease: EASE_OUT });
    }
  }

  // Only the live pick owns a blob: URL now — history entries are server URLs.
  window.addEventListener("beforeunload", () => {
    if (state.shot && state.shot.url && state.shot.url.startsWith("blob:")) {
      URL.revokeObjectURL(state.shot.url);
    }
  });

  entrance();
  // The HTML ships its button label in Chinese; i18n.apply() cannot reach it
  // because the label is runtime state everywhere else (分析中…/重新定位).
  if (i18n.lang() !== "zh") dom.runLabel.textContent = t("run.start");
  applyToken(); // reflect any stored override before the config round-trip lands
  loadConfig();
  // The rail is server-backed, so it repopulates on every load — including
  // after a restart of the program, which is the whole point of the move.
  loadHistory();
})();
