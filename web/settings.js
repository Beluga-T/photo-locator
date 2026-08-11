/* ═══════════════════════════════════════════════════════════════════
   Reverse Image Location — validating what the settings sheet typed

   This module used to BE the credential store: provider, keys, base URL
   and model names lived in this browser's localStorage and rode along as
   X-RIL-* headers on every request. That is gone. Configuration is now
   server-side — `PUT /api/settings` writes it to `data/config.json` on
   the machine running the service, so it survives a restart and a
   different browser, and `GET /api/config` reports what is in force.

   Deliberately nothing here reads localStorage any more. A leftover
   `ril-model-config` from the old build would otherwise make the model
   chip announce a browser override that no request actually sends.

   What is left is the part that stayed true: check a draft before it is
   sent, and say in one sentence what the next request will run on.

   ONE NAMING RULE HOLDS THIS TOGETHER. A draft is keyed the way the SERVER
   keys it — snake_case: the same seven names as app/store.py's CONFIG_FIELDS,
   app.js's MODEL_FIELDS, and app.js's X-RIL-* header map. This file used to
   spell them in camelCase instead, and since both callers only ever pass a
   server-keyed draft, the two sets intersected at "provider" alone. Every
   check below matched nothing, and validate() returned [] for every possible
   input for as long as it existed. Keep the names identical to the server's
   or the whole file silently goes dead again without a single error.

   Pure state and logic: no DOM, no fetch, no storage, no imports.
   app.js owns every pixel; this module only answers whether a draft is
   sane and what the server says is configured. Its sentences resolve
   through i18n.js AT CALL TIME (falling back to the local table below
   when that is missing), so an answer arrives in whatever language the
   page speaks when it is asked — re-rendering after a live language
   switch stays the caller's job, same as every other pixel.
   ═══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  // ── i18n ─────────────────────────────────────────────────────────────

  /* Every sentence this module can produce, in both languages, keyed under
   * "settings.". Handed to i18n.js at load time: extend() when the loaded
   * copy provides it, else the documented window.RIL.i18nExtra side-channel
   * that i18n.js merges. The local copy is kept because the worst failure of
   * a missing or mismatched i18n.js must be today's Chinese sentences, never
   * a raw key surfacing in a validation toast. */
  const STRINGS = {
    zh: {
      "settings.label.provider": "模型来源",
      "settings.label.anthropic_api_key": "Anthropic API Key",
      "settings.label.anthropic_model": "Anthropic 模型名",
      "settings.label.anthropic_effort": "思考深度",
      "settings.label.openai_base_url": "Base URL",
      "settings.label.openai_api_key": "OpenAI API Key",
      "settings.label.openai_model": "OpenAI 模型名",
      "settings.list_join": "、",
      "settings.err.too_long": "{label}超过 {max} 个字符，多半是粘贴错了内容。",
      "settings.err.whitespace": "{label}中间不能有空格或换行，请检查是不是粘贴多了。",
      "settings.err.unsendable":
        "{label}含有中文或不可打印字符，保存下来也用不了（“测试连接”更是发不出去）。",
      "settings.err.provider": "模型来源只能填 auto、claude 或 openai。",
      "settings.err.effort": "思考深度只能填 {levels}。",
      "settings.warn.key_prefix": "Anthropic 密钥通常以 sk-ant- 开头，请确认没有填错。",
      "settings.err.base_needs_key":
        "填了网关地址就必须同时填该网关的 API Key，否则请求会被后端拒绝。",
      "settings.err.base_scheme": "Base URL 必须以 http:// 或 https:// 开头。",
      "settings.err.base_path": "Base URL 只填到 /v1 为止，不要带 /chat/completions。",
      "settings.gateway_name": "OpenAI 兼容网关",
      "settings.note.server_creds": "当前使用服务端保存的 {name} 凭据，在设置里可以随时换一份。",
      "settings.note.missing_key": "服务端还没有 {name} 的 API Key，定位会返回 not_configured。",
      "settings.note.missing_piece":
        "服务端的 {name} 配置还差 {missing}，定位会返回 not_configured。",
    },
    en: {
      "settings.label.provider": "Model provider",
      "settings.label.anthropic_api_key": "Anthropic API Key",
      "settings.label.anthropic_model": "Anthropic model name",
      "settings.label.anthropic_effort": "Thinking effort",
      "settings.label.openai_base_url": "Base URL",
      "settings.label.openai_api_key": "OpenAI API Key",
      "settings.label.openai_model": "OpenAI model name",
      "settings.list_join": ", ",
      "settings.err.too_long":
        "{label} is over {max} characters — most likely the paste grabbed the wrong thing.",
      "settings.err.whitespace":
        "{label} cannot contain spaces or line breaks — check whether the paste picked up extra.",
      "settings.err.unsendable":
        "{label} contains Chinese or non-printable characters — it will not work even if saved (and \"Test connection\" cannot send it at all).",
      "settings.err.provider": "Model provider must be auto, claude or openai.",
      "settings.err.effort": "Thinking effort must be one of {levels}.",
      "settings.warn.key_prefix": "Anthropic keys usually start with sk-ant- — double-check this one.",
      "settings.err.base_needs_key":
        "A gateway Base URL must come with that gateway's own API Key, or the backend will refuse the request.",
      "settings.err.base_scheme": "Base URL must start with http:// or https://.",
      "settings.err.base_path": "Fill in the Base URL only up to /v1 — leave off /chat/completions.",
      "settings.gateway_name": "OpenAI-compatible gateway",
      "settings.note.server_creds":
        "Using the {name} credentials saved on the server — swap them in Settings at any time.",
      "settings.note.missing_key":
        "The server has no API Key for {name} yet, so locating will return not_configured.",
      "settings.note.missing_piece":
        "The server's {name} setup is still missing its {missing}, so locating will return not_configured.",
    },
  };

  window.RIL = window.RIL || {};
  if (window.RIL.i18n && typeof window.RIL.i18n.extend === "function") {
    window.RIL.i18n.extend(STRINGS);
  } else {
    const extra = (window.RIL.i18nExtra = window.RIL.i18nExtra || {});
    extra.zh = Object.assign(extra.zh || {}, STRINGS.zh);
    extra.en = Object.assign(extra.en || {}, STRINGS.en);
  }

  /* Prefer i18n.js — it knows the page's current language — and fall back to
   * the table above when it is absent or never learned these keys, applying
   * the same {name} placeholder rules the contract gives i18n.js. Resolved at
   * every call, never cached: validate() must answer in the language of the
   * moment it is asked, not the language of page load. */
  function t(key, params) {
    const i18n = window.RIL.i18n;
    if (i18n && typeof i18n.t === "function") {
      const hit = i18n.t(key, params);
      if (hit && hit !== key) return hit;
    }
    const lang = i18n && typeof i18n.lang === "function" && i18n.lang() === "en" ? "en" : "zh";
    const raw = STRINGS[lang][key] || STRINGS.zh[key] || key;
    return params
      ? raw.replace(/\{(\w+)\}/g, (hit, name) => (params[name] == null ? hit : String(params[name])))
      : raw;
  }

  // Canonical order — every loop, and therefore every error list, follows it.
  // These are the server's own field names; see the naming rule up top.
  const FIELDS = [
    "provider",
    "anthropic_api_key",
    "anthropic_model",
    "anthropic_effort",
    "openai_base_url",
    "openai_api_key",
    "openai_model",
  ];

  // Field → i18n key of its display name. The KEYS are the server's names and
  // must stay that way (see the naming rule up top); only the display strings
  // moved into STRINGS so they can follow the page language.
  const LABELS = {
    provider: "settings.label.provider",
    anthropic_api_key: "settings.label.anthropic_api_key",
    anthropic_model: "settings.label.anthropic_model",
    anthropic_effort: "settings.label.anthropic_effort",
    openai_base_url: "settings.label.openai_base_url",
    openai_api_key: "settings.label.openai_api_key",
    openai_model: "settings.label.openai_model",
  };

  const PROVIDERS = ["auto", "claude", "openai"];

  // Mirrors EFFORT_LEVELS in app/config.py, coarsest first. Claude-only: the
  // OpenAI-compatible path has no equivalent parameter and ignores it.
  const EFFORTS = ["low", "medium", "high", "xhigh", "max"];

  // Model names are the one place an inner space is legitimate — gateways do
  // expose things like "qwen vl max". Everything else is a token or a URL, and
  // a space in one of those is always a paste that grabbed too much.
  const SPACE_OK = ["anthropic_model", "openai_model"];

  // app/overrides.py MAX_VALUE_LEN, which app/store.py imports rather than
  // redeclares. The two backend paths part ways past the limit: a header is
  // refused, but store._coerce TRUNCATES to 500 and saves the stump, which
  // reads later as "the provider rejected my key". Refusing here is the only
  // place the user finds out they pasted the wrong thing.
  const MAX_LEN = 500;
  const WHITESPACE = /\s/;
  // Printable ASCII. The two backend entry points genuinely disagree here, and
  // that disagreement is the reason this check has to exist:
  //   X-RIL-* header  -> refused outright (overrides._clean)
  //   PUT /api/settings -> ACCEPTED. store._coerce only refuses control
  //                        characters, so a Chinese model name lands in
  //                        data/config.json verbatim under a green "已保存"
  //                        toast, and only fails later at the provider.
  // So this is not a nicety that front-runs the backend — for a saved value it
  // is the only thing standing in the way.
  const SENDABLE = /^[\x20-\x7e]+$/;

  // ── Shape ────────────────────────────────────────────────────────────

  function text(value) {
    return typeof value === "string" ? value.trim() : "";
  }

  /** Any object → the exact seven trimmed strings, so callers never see undefined. */
  function shape(draft) {
    const source = draft && typeof draft === "object" ? draft : {};
    const config = {};
    for (const field of FIELDS) config[field] = text(source[field]);
    config.provider = config.provider.toLowerCase();
    return config;
  }

  // ── Validation ───────────────────────────────────────────────────────

  function issue(field, message, level) {
    return { field, message, level };
  }

  /** Every complaint about a draft; empty means it is safe to send. */
  function validate(draft) {
    const config = shape(draft);
    const issues = [];

    for (const field of FIELDS) {
      const value = config[field];
      if (!value) continue; // blank is a valid answer: leave the stored value alone

      if (value.length > MAX_LEN) {
        issues.push(
          issue(
            field,
            t("settings.err.too_long", { label: t(LABELS[field]), max: MAX_LEN }),
            "error"
          )
        );
        continue; // one clear complaint per field; the rest would be noise
      }

      if (!SPACE_OK.includes(field) && WHITESPACE.test(value)) {
        issues.push(
          issue(field, t("settings.err.whitespace", { label: t(LABELS[field]) }), "error")
        );
        continue;
      }

      if (!SENDABLE.test(value)) {
        issues.push(
          issue(field, t("settings.err.unsendable", { label: t(LABELS[field]) }), "error")
        );
        continue;
      }

      if (field === "provider" && !PROVIDERS.includes(value)) {
        issues.push(issue(field, t("settings.err.provider"), "error"));
      }

      if (field === "anthropic_effort" && !EFFORTS.includes(value)) {
        // The list joiner is itself translated: enumeration commas differ
        // between the two languages ("、" vs ", ").
        issues.push(
          issue(
            field,
            t("settings.err.effort", { levels: EFFORTS.join(t("settings.list_join")) }),
            "error"
          )
        );
      }

      if (field === "anthropic_api_key" && !value.startsWith("sk-ant-")) {
        // A warning, not an error: key formats change, and a self-hosted relay
        // may well hand out Anthropic-shaped keys under its own prefix. Both
        // callers drop warn-level issues before picking one to show, so this
        // never blocks a save — it is advisory only, and invisible until
        // someone decides to render it.
        issues.push(issue(field, t("settings.warn.key_prefix"), "warn"));
      }

      if (field === "openai_base_url") {
        // The backend refuses a base URL that arrives without its own key, on
        // both paths (main.py write_settings, overrides.parse_overrides): it
        // would otherwise pair this caller's address with the stored secret.
        // The backend only applies it to a CHANGED address, but this form
        // cannot tell changed from retyped — /api/settings masks the stored
        // address down to scheme+host — so it asks for the key either way.
        // Say so here rather than letting the save 400.
        if (!config.openai_api_key) {
          issues.push(issue(field, t("settings.err.base_needs_key"), "error"));
        }
        if (!/^https?:\/\//i.test(value)) {
          issues.push(issue(field, t("settings.err.base_scheme"), "error"));
        }
        // The single most common way to get this wrong: providers.py builds
        // `${openai_base_url}/chat/completions` unconditionally and nothing
        // strips a pasted one, so the endpoint doubles and every call 404s.
        // Trailing slashes are tolerated because config.py rstrips them off
        // the stored value before any request is built — ".../v1/" and
        // ".../v1" are the same setup, and refusing one would only block a
        // save that works. That is also why the match ignores them: the
        // backend will see ".../chat/completions" either way.
        if (/\/chat\/completions\/*$/i.test(value)) {
          issues.push(issue(field, t("settings.err.base_path"), "error"));
        }
      }
    }

    return issues;
  }

  // ── Derived view ─────────────────────────────────────────────────────

  /**
   * What the next request will run on, from the `/api/config` body alone.
   *
   * The camelCase below is deliberate and must NOT be snake_cased to match
   * FIELDS: this reads a RESPONSE BODY, and main.py spells that body
   * `hasAnthropicKey`/`providerPinned`/`mapboxToken`. Draft keys and wire keys
   * are two different vocabularies that happen to meet in this one file.
   *
   * /api/config reports per-field presence, never values, so "is there a
   * usable credential for the provider that will actually be picked" can be
   * answered field by field. Inferring it from the resolved provider instead
   * was lossy in two supported setups — a half-filled OpenAI pair, and a
   * credential for the provider the server did NOT settle on — and made the
   * chip name a provider the request would not use.
   */
  function describe(serverConfig) {
    const server = serverConfig && typeof serverConfig === "object" ? serverConfig : {};
    const serverProvider = text(server.provider).toLowerCase();
    const serverModel = text(server.model);

    // Fall back to the old lossy inference only if the backend predates these
    // fields, so a version skew degrades rather than reporting "no credentials".
    const known = typeof server.hasAnthropicKey === "boolean";
    const ready = server.configured === true;
    const hasAnthropicKey = known ? server.hasAnthropicKey : serverProvider === "claude" && ready;
    const hasBase = known ? server.hasOpenaiBase === true : serverProvider === "openai" && ready;
    const hasOpenaiKey = known ? server.hasOpenaiKey === true : serverProvider === "openai" && ready;

    // Mirrors app/config.py: an explicit provider wins, otherwise a complete
    // gateway pair decides, otherwise Claude.
    const pinned = serverProvider === "claude" || serverProvider === "openai";
    const provider = pinned ? serverProvider : hasBase && hasOpenaiKey ? "openai" : "claude";
    const claude = provider === "claude";

    const configured = claude ? hasAnthropicKey : hasBase && hasOpenaiKey;
    // The server only reports the model for the provider IT chose; against a
    // different endpoint that name describes something else, so it is dropped.
    const model = serverProvider === provider ? serverModel : "";

    // "Claude" and the field names are proper nouns in both languages; only
    // the gateway's description and the sentence around them translate.
    const name = claude ? "Claude" : t("settings.gateway_name");
    const note = configured
      ? t("settings.note.server_creds", { name })
      : claude
        ? t("settings.note.missing_key", { name })
        : t("settings.note.missing_piece", { name, missing: hasBase ? "API Key" : "Base URL" });

    return { provider, model, configured, source: configured ? "server" : "none", note };
  }

  /** Enough of a key to recognise it, never enough to use it. */
  function maskKey(secret) {
    const value = text(secret);
    if (!value) return ""; // nothing stored — "***" would imply there is
    if (value.length <= 14) return "***";
    return `${value.slice(0, 6)}…${value.slice(-4)}`;
  }

  // ── Public API ───────────────────────────────────────────────────────

  window.RIL = window.RIL || {};

  window.RIL.settings = { validate, describe, maskKey, FIELDS, EFFORTS, PROVIDERS };
})();
