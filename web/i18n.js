/* ═══════════════════════════════════════════════════════════════════
   Reverse Image Location — i18n

   The page ships in Chinese; this file is what makes English a first-
   class citizen. Two flat dictionaries carry every user-facing string,
   t() resolves one key with {name} interpolation, and apply() walks the
   data-i18n / data-i18n-attr annotations in the static HTML. Scripts
   loaded after this one call t() for everything they build at runtime;
   map.js and settings.js register their own namespaced strings through
   extend() as they load.

   Loaded after motion.min.js and before every other script, so the API
   exists by the time anyone asks for a string. The document itself is
   the zh source of truth: in Chinese nothing is rewritten on load, so
   the default look stays exactly what it always was. (An English-first
   visitor sees one Chinese paint before apply() runs at the end of the
   body — accepted; avoiding it would take an inlined dictionary.)
   ═══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  // A language name is not a secret; localStorage is exactly right for it.
  const STORE_KEY = "ril-lang";

  /* Chinese dictionary. Values are the exact strings the HTML and app.js
   * shipped with, so re-applying zh after a round-trip through English
   * reproduces the original page character for character. */
  const ZH = {
    // Chrome: title, header, skip link
    "app.title": "照片定位",
    "app.desc": "上传一张照片，模型只看画面本身，推断它拍摄于哪个国家、哪个州省、哪个城市，并给出完整的推理依据。",
    "a11y.skip": "跳到主要内容",
    "brand.name": "照片定位",
    "chip.title": "当前后端连接的模型",
    "chip.connecting": "连接中…",
    "chip.unset": "未配置",
    "chip.detail": "模型来源 {provider} · 模型 {model} · 思考深度 {effort}",
    "chip.nokey": "还没有配置模型：点右上角设置选择模型来源并填好密钥",
    "chip.offline": "后端未连接",
    "chip.offline.title": "取不到 /api/config，后端可能没有启动",
    "settings.open.aria": "打开设置",
    "settings.open.title": "设置 · 更换模型密钥与地图令牌",
    "theme.aria": "切换深浅主题",
    // The toggle names the language you switch TO, so its label is written
    // in that target language — English text in the zh dictionary is intended.
    "lang.toggle": "Switch to English",

    // Thesis
    "thesis.eyebrow": "视觉推断 · 无需 GPS 元数据",
    "thesis.title": "这张照片，拍在哪里？",
    "thesis.lede": "上传一张照片。系统会剥掉它的 EXIF 信息，只把画面交给模型，从地形、文字、路面标线、电线杆、车牌这些细节一路收敛，给出国家、州省、城市的判断，以及每一条推理依据。",

    // Plate & intake
    "plate.label": "图版",
    "plate.aria": "图片工作区",
    "drop.title": "把照片拖进来",
    "drop.hint": "或点击选择 · 也可以直接 Ctrl + V 粘贴",
    "photo.alt": "待分析的照片",
    "run.start": "开始定位",
    "run.busy": "分析中…",
    "run.again": "重新定位",
    "run.review": "回看中",
    "run.cancel": "取消",
    "run.reset": "换一张",
    "rail.label": "历史",
    "veil.title": "把照片放在这里",
    "veil.sub": "松手即可载入",

    // Keyboard hints
    "hints.run": "开始定位",
    "hints.paste": "粘贴",
    "hints.reset": "换一张",
    "hints.theme": "切换主题",

    // Idle panel
    "idle.label": "分析维度",
    "idle.terrain": "地形与植被",
    "idle.terrain.d": "山形、海岸线、树种与季相，先把范围收到气候带",
    "idle.text": "文字与标识",
    "idle.text.d": "招牌、路牌、域名后缀、电话区号——单条最强的线索",
    "idle.road": "道路与交通",
    "idle.road.d": "靠左还是靠右、车道线颜色、护栏与防撞柱造型",
    "idle.infra": "基础设施",
    "idle.infra.d": "电线杆横担、路灯灯头、井盖、消防栓，各国高度定型",
    "idle.light": "光照与阴影",
    "idle.light.d": "阴影方向与长度反推半球、纬度和大致时刻",
    "idle.foot": "结果给到城市一级，附带 0–100 的置信度与 2–3 个备选地点。 EXIF 中的 GPS 不会送进模型，也不会跟着照片一起存下来。",

    // Footer
    "foot.store": "分析过的照片和结论会保存在运行这个服务的机器上，用于回看，可在设置里一键清空。",
    "foot.map.on": "地图由 Mapbox 渲染，浏览器会把推断出的坐标发给它。",
    "foot.map.off": "未配置 Mapbox 令牌，结果页使用内置示意地球，全程零外部请求。",
    "foot.caveat": "推断结果为概率判断，请勿作为唯一依据。",

    // Settings sheet — static chrome
    "settings.title": "设置",
    "settings.close.aria": "关闭设置",
    "settings.tab.model": "模型",
    "settings.tab.map": "地图",
    "settings.tab.data": "数据",
    "settings.provider.label": "模型来源",
    "settings.provider.none": "— 请选择 —",
    "settings.provider.openai": "OpenAI 兼容网关",
    "settings.key.label": "API 密钥",
    "settings.model.label": "模型名",
    "settings.base.label": "网关地址",
    "settings.mapbox.label": "Mapbox 令牌",
    "settings.effort.label": "思考深度",
    "settings.effort.low": "low · 最快，够用就行",
    "settings.effort.medium": "medium · 提速首选",
    "settings.effort.high": "high · Anthropic 默认",
    "settings.effort.xhigh": "xhigh · 更细的推理",
    "settings.effort.max": "max · 最慢，正确性优先",
    "settings.openai.legend": "OPENAI 兼容网关",
    "settings.reveal": "显示",
    "settings.hide": "隐藏",
    "settings.history.label": "已保存的历史",
    "settings.history.loading": "读取中…",
    "settings.history.clear": "清空历史",
    "settings.save": "保存并生效",
    "settings.test": "测试连接",
    "settings.revert": "清除已保存的配置",

    // Settings sheet — the data pane's storage note, split around <code>/<b>
    "settings.data.f1": "每次分析成功后，送进模型的那张 JPEG 和它的结论会存在运行这个服务的机器上（",
    "settings.data.and": " 与 ",
    "settings.data.f2": "），保留最近 20 张，超出的连图片一起删除。存的是缩放并",
    "settings.data.strip": "剥掉 EXIF 之后",
    "settings.data.f3": "的那张——原图里的 GPS 既不进模型，也不落盘。",

    // Settings sheet — the closing security note, split around <code>/<b>
    "settings.foot.t0": "这里填的内容",
    "settings.foot.b1": "保存在运行这个服务的机器上",
    "settings.foot.t1": "（",
    "settings.foot.t2": "，仅属主可读），这样换浏览器、重启程序都还在——发版时没有 ",
    "settings.foot.t3": " 可改，配置得由界面自己记住。密钥不会回显：读出来只有掩码，日志里也只有掩码。留空的输入框表示“沿用服务端已有的值”，清空并保存则是删掉它。",
    "settings.foot.b2": "这个端口没有鉴权",
    "settings.foot.t4": "，所以只能绑在本机回环上——详见 README 的「安全边界」。 Mapbox 只填公开令牌（",
    "settings.foot.t5": " 开头），",
    "settings.foot.t6": " 开头的私密令牌绝不能放进浏览器。这套做法适合本机自用；把服务暴露到公网前请先看 README 的「边界与隐私」。",

    // Settings — runtime strings app.js composes
    "settings.secret.saved": "已保存 {mask} · 留空则不改动",
    "settings.effortnote.low": "最快。单张照片的推断通常仍然可用，是最直接的提速手段。",
    "settings.effortnote.medium": "明显快于默认，质量损失很小 —— 想提速优先试这一档。",
    "settings.effortnote.high": "Anthropic 的默认值。思考最久的一档之下，也是最慢的常用档。",
    "settings.effortnote.xhigh": "比默认更细的推理，更慢更贵；这类单次视觉判断通常收益有限。",
    "settings.effortnote.max": "最慢。正确性压倒成本时才用，容易在简单图上过度思考。",
    "settings.effortnote.na": "当前走的是 OpenAI 兼容网关，这一项不生效。",
    "settings.token.set": "已配置，保存在服务端。清空并保存即可移除，结果页会退回内置示意地球。",
    "settings.token.unset": "没有配置令牌，结果页使用内置示意地球，全程零外部请求。填一个公开令牌即可启用真实地图。",
    "settings.token.sk": "这是 sk. 开头的私密令牌，不能放进浏览器。请改用 pk. 开头的公开令牌。",
    "settings.token.pk": "Mapbox 公开令牌通常以 pk. 开头，请确认没有填错。",
    "settings.model.none": "还没有可用的模型配置：先在上面选择模型来源，再填好对应密钥。配置保存在服务端，重启也还在。",
    "settings.model.keysaved": "密钥来自这里保存的配置（{mask}）",
    "settings.model.keyenv": "密钥来自服务端环境变量",
    "settings.model.using": "将使用 {provider} · {model}，{where}。",
    "settings.history.some": "已保存 {n} 张分析过的照片和它们的结论。清空后无法恢复。",
    "settings.history.none": "还没有保存任何历史。分析成功后会自动记录，最多保留 20 张。",
    "settings.history.confirm": "清空所有已保存的照片和分析结果？此操作无法撤销。",
    "settings.history.cleared": "已清空 {n} 张历史。",
    "settings.history.offline": "连不上后端，历史没有清空。",
    "settings.save.ok": "设置已保存到服务端，重启也还在。",
    "settings.save.offline": "连不上后端，设置没有保存。",
    "settings.revert.ok": "已清除保存的配置，回到环境变量与默认值。",
    "settings.revert.offline": "连不上后端，配置没有清除。",
    "settings.testing": "测试中…",
    "settings.connecting": "正在连接…",
    "settings.test.bad": "后端没有返回可解析的结果。",
    "settings.test.invalid": "配置有误。",
    "settings.test.unsaved": " 记得点「保存并生效」，否则分析仍用旧配置。",
    "settings.test.detail": "（{detail}）",
    "settings.test.offline": "连不上本地后端，请确认服务仍在运行。",

    // /api/verify verdicts, by code. zh mode shows the server's own message,
    // so these mirror it only approximately; EN mode is where they matter.
    "verify.ok": "密钥可用，将使用 {model}。",
    "verify.not_configured": "还没有填齐这个通道的密钥。",
    "verify.auth": "密钥无效或已过期，请检查后重新填写。",
    "verify.rate_limited": "上游限流了，请稍后再验证。",
    "verify.timeout": "连接超时，请检查网络或代理。",
    "verify.network": "连不上上游，请检查网络或代理。",
    "verify.upstream": "上游返回了错误，请稍后再试。",
    "verify.unconfirmed": "网关不支持 /models，密钥未能确认，但地址可达。",

    // Server error codes ({code, message} bodies). Same story: zh mode shows
    // the server message verbatim, these are the EN mapping's zh anchors.
    "err.rate_limited": "请求太频繁了，请过一会儿再试。",
    "err.empty": "没有收到图片内容。",
    "err.too_large": "图片超过 {mb} MB，请压缩后再上传。",
    "err.bad_image": "图片无法解码或格式不支持，请换成 JPG、PNG 或 WebP。",
    "err.not_configured": "还没有选好模型来源或密钥不完整：请在设置里选择模型来源并填好对应密钥。",
    "err.auth": "API 密钥无效或已过期。",
    "err.network": "连不上上游模型 API，请检查网络或代理。",
    "err.upstream": "上游模型服务返回了错误，请查看后端日志。",
    "err.timeout": "上游模型响应超时，请重试。",
    "err.refused": "模型基于安全策略拒绝分析这张图片，请换一张。",
    "err.truncated": "模型输出被截断了，请重试。",
    "err.billing": "Anthropic 账户余额不足，请前往充值。",
    "err.forbidden": "密钥没有访问该模型的权限。",
    "err.bad_response": "模型没有返回可解析的结果，请重试。",
    "err.internal": "服务端出错了，请查看后端日志。",

    // Client-side failures around the request itself
    "err.title": "定位失败",
    "err.http": "服务端返回 {status}",
    "err.http.body": "服务端返回 {status}，请查看后端日志。",
    "err.stream": "连接中断，没有收到完整结果。",
    "err.network.title": "连不上后端",
    "err.network.body": "请确认服务仍在运行，然后重试。",
    "act.retry": "重试",

    // Toasts
    "toast.nokey": "还没有配置模型。点右上角的设置选择模型来源，填好对应密钥就能用。",
    "toast.offline": "连不上后端 /api/config，请确认服务已启动。",
    "toast.notimage": "这不是图片文件，请选择 JPG、PNG 或 WebP。",
    "toast.toolarge": "图片 {size}，超过 {max} MB 上限，请先压缩。",
    "toast.cancelled": "已取消这次分析。",
    "toast.netfail": "网络请求失败。",
    "toast.clipboard": "浏览器拒绝了剪贴板访问，请手动复制。",
    "toast.done": "{where} · 置信度 {n}/100",

    // Panel labels. The language-purity contract retired the old decorative
    // bilingual pairs ("判定 / VERDICT"): each mode shows its own half only.
    "panel.error": "出错了",
    "panel.reading": "分析中",
    "panel.verdict": "判定",
    "panel.evidence": "证据链",
    "panel.alts": "备选",
    "panel.notes": "补充说明",
    "panel.narrowing": "正在收敛",

    // Working-panel phase copy
    "phase.terrain": "读取地形、海岸线与植被，先把范围收进气候带……",
    "phase.text": "搜索画面里的一切文字：招牌、路牌、车身、涂鸦……",
    "phase.road": "比对道路规则：靠左还是靠右、车道线、护栏与防撞柱……",
    "phase.infra": "核对基础设施：电线杆横担、路灯灯头、井盖、消防栓……",
    "phase.shadow": "用阴影方向反推半球与纬度，收敛到城市一级……",
    "phase.chain": "整理证据链，排出备选地点……",

    // Verdict: bands, precision, coordinates
    "band.high": "高置信",
    "band.medium": "中置信",
    "band.low": "低置信",
    "prec.country": "国家",
    "prec.region": "一级行政区",
    "prec.city": "城市",
    "prec.locality": "街区 / 地标",
    "prec.country.note": "证据只支撑到国家一级，未给出更细的判断。",
    "prec.region.note": "证据只支撑到一级行政区，未给出城市判断。",
    "verdict.precision": "精确到 {level}",
    "verdict.unknown": "未确定",
    "admin.country": "国家",
    "admin.region": "行政区",
    "admin.city": "城市",
    "coords.label": "坐标",
    "coords.radius": "± {km} KM 可信半径",
    "coords.copy": "复制坐标",
    "coords.copied": "坐标已复制",
    "globe.cap": "正射投影 · 视心即判定点",
    "alt.unnamed": "未命名",

    // Result actions and meta strip
    "act.copy": "复制结论",
    "act.copied": "结论已复制到剪贴板",
    "act.download": "下载 JSON",
    "act.downloaded": "已导出 JSON",
    "act.again": "重新分析",
    "meta.sent": "送模型 {w}×{h}",
    "meta.source": "原图 {w}×{h}",
    "exif.note": "注意：这张照片的 EXIF 自带 GPS {lat}, {lon}。该坐标在上传后已被剥离，没有送进模型 —— 上面的判断完全来自画面本身。",

    // The copied text summary
    "export.verdict": "判定：{chain}",
    "export.precision": "精度：只能确定到{level}一级",
    "export.coords": "坐标：{lat}, {lon}（± {km} km）",
    "export.confidence": "置信度：{n}/100（{band}）",
    "export.evidence": "证据链：",
    "export.alts": "备选：",
    "export.alt": "- {name}（{pct}%）{reason}",
    "export.notes": "补充：{notes}",

    // The provisional (streaming) card
    "draft.wait": "正在读取画面…",
    "draft.said.evidence": "模型开始写证据链",
    "draft.said.alts": "模型开始列备选地点",
    "draft.phase.alts": "模型还在列备选… 已列出 {n} 个",
    "draft.phase.evidence": "模型还在写证据链… 已写出 {n} 条",
    "draft.phase.evidence0": "模型还在写证据链…",
    "draft.phase.summary": "模型还在写概述…",
    "draft.phase.early": "模型还在写，以下是初步判断",

    // The off-screen live region
    "aria.confidence": "置信度 {n}/100",
    "aria.unsettled": "正在收敛，尚未确定地点",
    "aria.provisional": "初步判断 {name}",
    "rail.aria": "回看：{where}，置信度 {n}",

    // Evidence categories — prompt.py's fixed enum, mapped for EN display
    "cat.terrain": "地形地貌",
    "cat.vegetation": "植被",
    "cat.architecture": "建筑风格",
    "cat.road": "道路与交通",
    "cat.text": "文字与标识",
    "cat.vehicle": "车辆与车牌",
    "cat.climate": "气候与光照",
    "cat.infra": "基础设施",
    "cat.culture": "人文与服饰",
    "cat.other": "其他",
  };

  /* English dictionary. Language purity holds in both directions: the EN page
   * carries no Chinese UI chrome at all — the old bilingual accent pairs
   * ("VERDICT / 判定") render one half per language now. */
  const EN = {
    // Chrome: title, header, skip link
    "app.title": "Reverse Image Location",
    "app.desc": "Upload a photo and a vision model infers, from the pixels alone, which country, region and city it was taken in — with the full chain of reasoning.",
    "a11y.skip": "Skip to main content",
    "brand.name": "Reverse Image Location",
    "chip.title": "The model the backend is connected to",
    "chip.connecting": "Connecting…",
    "chip.unset": "Not configured",
    "chip.detail": "provider {provider} · model {model} · effort {effort}",
    "chip.nokey": "No model configured yet — open Settings (top right) to choose a provider and add its key",
    "chip.offline": "Backend offline",
    "chip.offline.title": "Could not fetch /api/config — the backend may not be running",
    "settings.open.aria": "Open settings",
    "settings.open.title": "Settings · model keys and map token",
    "theme.aria": "Toggle light / dark theme",
    // Target-language label again: on the English page it offers Chinese.
    "lang.toggle": "切换到中文",

    // Thesis
    "thesis.eyebrow": "Visual inference · no GPS metadata",
    "thesis.title": "Where was this photo taken?",
    "thesis.lede": "Upload a photo. The system strips its EXIF data and hands the model nothing but the picture, narrowing down from terrain, text, lane markings, utility poles and licence plates to a country, region and city — with every step of the reasoning laid out.",

    // Plate & intake
    "plate.label": "PLATE",
    "plate.aria": "Image workspace",
    "drop.title": "Drop a photo here",
    "drop.hint": "or click to browse · Ctrl + V pastes too",
    "photo.alt": "The photo being analysed",
    "run.start": "Locate",
    "run.busy": "Analysing…",
    "run.again": "Locate again",
    "run.review": "Reviewing",
    "run.cancel": "Cancel",
    "run.reset": "New photo",
    "rail.label": "HISTORY",
    "veil.title": "Drop the photo here",
    "veil.sub": "Release to load",

    // Keyboard hints
    "hints.run": "locate",
    "hints.paste": "paste",
    "hints.reset": "new photo",
    "hints.theme": "theme",

    // Idle panel
    "idle.label": "SIGNALS READ",
    "idle.terrain": "Terrain & vegetation",
    "idle.terrain.d": "Mountain profiles, coastlines, tree species and season — narrowing to a climate zone first",
    "idle.text": "Text & signage",
    "idle.text.d": "Shop signs, road signs, domain suffixes, phone codes — the strongest single clue",
    "idle.road": "Roads & traffic",
    "idle.road.d": "Left- or right-hand traffic, lane-line colours, guardrail and bollard shapes",
    "idle.infra": "Infrastructure",
    "idle.infra.d": "Pole crossarms, lamp heads, manhole covers, hydrants — highly standardised per country",
    "idle.light": "Light & shadows",
    "idle.light.d": "Shadow direction and length back out the hemisphere, latitude and rough time of day",
    "idle.foot": "Results go down to city level, with a 0–100 confidence score and 2–3 alternative locations. GPS in the EXIF is never sent to the model, and is not stored with the photo either.",

    // Footer
    "foot.store": "Analysed photos and their verdicts are kept on the machine running this service for review, and can be cleared in Settings.",
    "foot.map.on": "The map is rendered by Mapbox; your browser sends it the inferred coordinates.",
    "foot.map.off": "No Mapbox token configured — results use the built-in schematic globe, with zero external requests.",
    "foot.caveat": "Inferences are probabilistic — never treat them as sole evidence.",

    // Settings sheet — static chrome
    "settings.title": "Settings",
    "settings.close.aria": "Close settings",
    "settings.tab.model": "Model",
    "settings.tab.map": "Map",
    "settings.tab.data": "Data",
    "settings.provider.label": "PROVIDER",
    "settings.provider.none": "— choose —",
    "settings.provider.openai": "OpenAI-compatible gateway",
    "settings.key.label": "API KEY",
    "settings.model.label": "MODEL",
    "settings.base.label": "BASE URL",
    "settings.mapbox.label": "MAPBOX TOKEN",
    "settings.effort.label": "EFFORT · thinking depth",
    "settings.effort.low": "low · fastest, good enough",
    "settings.effort.medium": "medium · first pick for speed",
    "settings.effort.high": "high · Anthropic's default",
    "settings.effort.xhigh": "xhigh · finer reasoning",
    "settings.effort.max": "max · slowest, correctness first",
    "settings.openai.legend": "OPENAI-COMPATIBLE GATEWAY",
    "settings.reveal": "Show",
    "settings.hide": "Hide",
    "settings.history.label": "Saved history",
    "settings.history.loading": "Loading…",
    "settings.history.clear": "Clear history",
    "settings.save": "Save & apply",
    "settings.test": "Test connection",
    "settings.revert": "Clear saved config",

    // Settings sheet — the data pane's storage note, split around <code>/<b>
    "settings.data.f1": "After each successful analysis, the JPEG that went to the model and its verdict are stored on the machine running this service (",
    "settings.data.and": " and ",
    "settings.data.f2": "), keeping the latest 20 — older entries are deleted, image and all. What is stored is the resized copy ",
    "settings.data.strip": "with EXIF already stripped",
    "settings.data.f3": " — the original's GPS neither reaches the model nor touches the disk.",

    // Settings sheet — the closing security note, split around <code>/<b>
    "settings.foot.t0": "Everything entered here is ",
    "settings.foot.b1": "stored on the machine running this service",
    "settings.foot.t1": " (",
    "settings.foot.t2": ", owner-readable only), so it survives a browser switch or a restart — a packaged release has no ",
    "settings.foot.t3": " to edit, so the UI has to remember the config itself. Keys are never echoed back: reads return only a mask, and the logs carry only the mask. A blank input means “keep the server's current value”; clearing it and saving deletes it. ",
    "settings.foot.b2": "This port has no authentication",
    "settings.foot.t4": ", so it must stay bound to the local loopback — see the README's security-boundary section. Give Mapbox a public token only (starting with ",
    "settings.foot.t5": "); a secret token starting with ",
    "settings.foot.t6": " must never go into a browser. This setup is meant for personal on-machine use; read the README's boundaries-and-privacy section before exposing the service to the internet.",

    // Settings — runtime strings app.js composes
    "settings.secret.saved": "Saved: {mask} · leave blank to keep it",
    "settings.effortnote.low": "Fastest. Single-photo inference usually still holds up — the most direct speed lever.",
    "settings.effortnote.medium": "Clearly faster than the default with little quality loss — try this first for speed.",
    "settings.effortnote.high": "Anthropic's default. The slowest of the everyday settings, short of the deepest two.",
    "settings.effortnote.xhigh": "Finer reasoning than the default, slower and pricier; a one-shot visual call rarely benefits.",
    "settings.effortnote.max": "Slowest. For when correctness beats cost — prone to overthinking simple images.",
    "settings.effortnote.na": "The OpenAI-compatible gateway is in force; this setting has no effect there.",
    "settings.token.set": "Configured and stored server-side. Clear the field and save to remove it; results fall back to the schematic globe.",
    "settings.token.unset": "No token configured — results use the built-in schematic globe with zero external requests. Add a public token to enable the real map.",
    "settings.token.sk": "That is a secret token (sk.) and must not go into a browser. Use a public pk. token instead.",
    "settings.token.pk": "Mapbox public tokens normally start with pk. — double-check the value.",
    "settings.model.none": "No usable model configuration yet — choose a provider above and add its key. It is stored server-side and survives restarts.",
    "settings.model.keysaved": "the key comes from the config saved here ({mask})",
    "settings.model.keyenv": "the key comes from the server's environment variables",
    "settings.model.using": "Will use {provider} · {model}; {where}.",
    "settings.history.some": "{n} analysed photo(s) and their verdicts are saved. Clearing cannot be undone.",
    "settings.history.none": "No history saved yet. Successful analyses are recorded automatically, keeping at most 20.",
    "settings.history.confirm": "Clear every saved photo and result? This cannot be undone.",
    "settings.history.cleared": "Cleared {n} saved shot(s).",
    "settings.history.offline": "Could not reach the backend — history was not cleared.",
    "settings.save.ok": "Settings saved server-side; they survive restarts.",
    "settings.save.offline": "Could not reach the backend — settings were not saved.",
    "settings.revert.ok": "Saved config cleared — back to environment variables and defaults.",
    "settings.revert.offline": "Could not reach the backend — config was not cleared.",
    "settings.testing": "Testing…",
    "settings.connecting": "Connecting…",
    "settings.test.bad": "The backend returned nothing parseable.",
    "settings.test.invalid": "The configuration is invalid.",
    "settings.test.unsaved": " Remember to press “Save & apply” — analyses keep using the old config until you do.",
    "settings.test.detail": " ({detail})",
    "settings.test.offline": "Could not reach the local backend — make sure the service is still running.",

    // /api/verify verdicts, by code
    "verify.ok": "The key works. Will use {model}.",
    "verify.not_configured": "This channel's credentials are not filled in yet.",
    "verify.auth": "The key is invalid or expired — check it and enter it again.",
    "verify.rate_limited": "The upstream is rate-limiting — verify again in a moment.",
    "verify.timeout": "The connection timed out — check your network or proxy.",
    "verify.network": "Could not reach the upstream — check your network or proxy.",
    "verify.upstream": "The upstream returned an error — try again later.",
    "verify.unconfirmed": "The gateway does not support /models, so the key could not be confirmed — but the address is reachable.",

    // Server error codes
    "err.rate_limited": "Too many requests — wait a moment and try again.",
    "err.empty": "No image data was received.",
    "err.too_large": "The image exceeds {mb} MB — compress it and upload again.",
    "err.bad_image": "The image could not be decoded — use a JPG, PNG or WebP.",
    "err.not_configured": "No provider is fully set up — choose one in Settings and add its key.",
    "err.auth": "The API key is invalid or expired.",
    "err.network": "Could not reach the upstream model API — check your network or proxy.",
    "err.upstream": "The upstream model service returned an error — check the backend log.",
    "err.timeout": "The upstream model timed out — try again.",
    "err.refused": "The model declined to analyse this image on safety grounds — try a different one.",
    "err.truncated": "The model's output was truncated — try again.",
    "err.billing": "The Anthropic account is out of credit — top up under Plans & Billing.",
    "err.forbidden": "This key has no access to that model — switch keys, or pick a model it can use.",
    "err.bad_response": "The model returned nothing parseable — try again.",
    "err.internal": "The server hit an internal error — check the backend log.",

    // Client-side failures around the request itself
    "err.title": "Locating failed",
    "err.http": "The server returned {status}",
    "err.http.body": "The server returned {status} — check the backend log.",
    "err.stream": "The connection dropped before a complete result arrived.",
    "err.network.title": "Backend unreachable",
    "err.network.body": "Make sure the service is still running, then retry.",
    "act.retry": "Retry",

    // Toasts
    "toast.nokey": "No model configured yet. Open Settings (top right), choose a provider and add its key to get going.",
    "toast.offline": "Could not reach the backend at /api/config — make sure the service is running.",
    "toast.notimage": "That is not an image file — pick a JPG, PNG or WebP.",
    "toast.toolarge": "The image is {size}, over the {max} MB limit — compress it first.",
    "toast.cancelled": "Analysis cancelled.",
    "toast.netfail": "The network request failed.",
    "toast.clipboard": "The browser refused clipboard access — copy it manually.",
    "toast.done": "{where} · confidence {n}/100",

    // Panel labels — English half only; see the note on the zh table.
    "panel.error": "ERROR",
    "panel.reading": "READING",
    "panel.verdict": "VERDICT",
    "panel.evidence": "EVIDENCE",
    "panel.alts": "ALTERNATIVES",
    "panel.notes": "NOTES",
    "panel.narrowing": "NARROWING",

    // Working-panel phase copy
    "phase.terrain": "Reading terrain, coastline and vegetation, narrowing to a climate zone…",
    "phase.text": "Scanning for any text in frame: shop signs, road signs, vehicles, graffiti…",
    "phase.road": "Comparing road rules: left or right traffic, lane lines, guardrails, bollards…",
    "phase.infra": "Checking infrastructure: pole crossarms, lamp heads, manhole covers, hydrants…",
    "phase.shadow": "Using shadow direction to back out hemisphere and latitude, converging on a city…",
    "phase.chain": "Assembling the evidence chain and ranking the alternatives…",

    // Verdict: bands, precision, coordinates
    "band.high": "high confidence",
    "band.medium": "medium confidence",
    "band.low": "low confidence",
    "prec.country": "country",
    "prec.region": "region",
    "prec.city": "city",
    "prec.locality": "street / landmark",
    "prec.country.note": "The evidence only supports a country-level call; nothing finer was claimed.",
    "prec.region.note": "The evidence only supports a region-level call; no city was claimed.",
    "verdict.precision": "precise to {level}",
    "verdict.unknown": "Undetermined",
    "admin.country": "Country",
    "admin.region": "Region",
    "admin.city": "City",
    "coords.label": "FIX",
    "coords.radius": "± {km} KM confidence radius",
    "coords.copy": "Copy coordinates",
    "coords.copied": "Coordinates copied",
    "globe.cap": "Orthographic projection · view centred on the fix",
    "alt.unnamed": "Unnamed",

    // Result actions and meta strip
    "act.copy": "Copy summary",
    "act.copied": "Summary copied to the clipboard",
    "act.download": "Download JSON",
    "act.downloaded": "JSON exported",
    "act.again": "Analyse again",
    "meta.sent": "sent to model {w}×{h}",
    "meta.source": "original {w}×{h}",
    "exif.note": "Note: this photo's EXIF carried GPS {lat}, {lon}. It was stripped after upload and never reached the model — the verdict above comes from the picture alone.",

    // The copied text summary
    "export.verdict": "Verdict: {chain}",
    "export.precision": "Precision: settled only to the {level} level",
    "export.coords": "Coordinates: {lat}, {lon} (± {km} km)",
    "export.confidence": "Confidence: {n}/100 ({band})",
    "export.evidence": "Evidence:",
    "export.alts": "Alternatives:",
    "export.alt": "- {name} ({pct}%) {reason}",
    "export.notes": "Notes: {notes}",

    // The provisional (streaming) card
    "draft.wait": "Reading the image…",
    "draft.said.evidence": "The model is writing the evidence chain",
    "draft.said.alts": "The model is listing alternative locations",
    "draft.phase.alts": "Still listing alternatives… {n} so far",
    "draft.phase.evidence": "Still writing evidence… {n} so far",
    "draft.phase.evidence0": "Still writing the evidence chain…",
    "draft.phase.summary": "Still writing the summary…",
    "draft.phase.early": "The model is still writing — this is its provisional call",

    // The off-screen live region
    "aria.confidence": "Confidence {n}/100",
    "aria.unsettled": "Narrowing — no place settled yet",
    "aria.provisional": "Provisional call: {name}",
    "rail.aria": "Review: {where}, confidence {n}",

    // Evidence categories — prompt.py's fixed enum, mapped for EN display
    "cat.terrain": "Terrain",
    "cat.vegetation": "Vegetation",
    "cat.architecture": "Architecture",
    "cat.road": "Roads & traffic",
    "cat.text": "Text & signage",
    "cat.vehicle": "Vehicles & plates",
    "cat.climate": "Climate & light",
    "cat.infra": "Infrastructure",
    "cat.culture": "People & dress",
    "cat.other": "Other",
  };

  // ── Language resolution ──────────────────────────────────────────────

  /** Browser default: Chinese UIs get zh, everyone else gets en. */
  function detect() {
    return (navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en";
  }

  let current = detect();
  try {
    const saved = localStorage.getItem(STORE_KEY);
    if (saved === "zh" || saved === "en") current = saved;
  } catch {
    /* private browsing — detection stands for this session */
  }

  // ── t() ──────────────────────────────────────────────────────────────

  const warned = new Set();

  function t(key, params) {
    const dict = current === "en" ? EN : ZH;
    let text = dict[key];
    if (text == null) {
      // A key missing from one dictionary is a bug in this file. Fall back to
      // the Chinese string so the screen never shows a raw key, and say so —
      // once per key, not once per repaint of a 100ms status line.
      text = ZH[key] != null ? ZH[key] : key;
      if (!warned.has(key)) {
        warned.add(key);
        console.warn(`[i18n] missing key "${key}" in "${current}"`);
      }
    }
    if (params) {
      text = text.replace(/\{(\w+)\}/g, (whole, name) => (name in params ? String(params[name]) : whole));
    }
    return text;
  }

  // ── apply(): the static HTML annotations ─────────────────────────────

  /* data-i18n="key"                     -> textContent
   * data-i18n-attr="title:key;alt:key2" -> attributes
   * querySelectorAll never matches the scope itself, so an annotated root
   * passed in explicitly is handled on its own first. */
  function apply(root) {
    const scope = root || document;
    const nodes = [];
    if (scope instanceof Element && (scope.dataset.i18n || scope.dataset.i18nAttr)) nodes.push(scope);
    nodes.push(...scope.querySelectorAll("[data-i18n], [data-i18n-attr]"));

    for (const node of nodes) {
      if (node.dataset.i18n) node.textContent = t(node.dataset.i18n);
      if (!node.dataset.i18nAttr) continue;
      for (const pair of node.dataset.i18nAttr.split(";")) {
        const colon = pair.indexOf(":");
        if (colon < 1) continue;
        node.setAttribute(pair.slice(0, colon).trim(), t(pair.slice(colon + 1).trim()));
      }
    }
  }

  // ── extend(): satellite dictionaries ─────────────────────────────────

  /* map.js and settings.js each carry their own {zh, en} table under their
   * namespace ("map.", "settings.") and hand it over here at load time —
   * they keep a local copy only so a missing i18n.js degrades to correct-
   * language text. Merging into the same two dictionaries makes t(), apply()
   * and the missing-key warning treat their keys exactly like native ones. */
  function extend(strings) {
    if (!strings) return;
    Object.assign(ZH, strings.zh);
    Object.assign(EN, strings.en);
  }

  // ── set() and the change feed ────────────────────────────────────────

  const listeners = [];

  function onChange(fn) {
    if (typeof fn === "function") listeners.push(fn);
  }

  function set(lang) {
    current = lang === "en" ? "en" : "zh";
    try {
      localStorage.setItem(STORE_KEY, current);
    } catch {
      /* private browsing — the switch still holds for this session */
    }
    document.documentElement.lang = current === "zh" ? "zh-CN" : "en";
    apply();
    syncToggle();
    // Listeners run after apply() so they can overwrite annotated nodes whose
    // real text depends on runtime state (the model chip, the map footer).
    for (const fn of listeners) {
      try {
        fn(current);
      } catch {
        /* one broken listener must not mute the rest */
      }
    }
  }

  window.RIL = window.RIL || {};
  window.RIL.i18n = { lang: () => current, set, t, onChange, apply, extend };

  // ── The header toggle ────────────────────────────────────────────────

  const toggle = document.getElementById("lang-toggle");

  /** The button names what you switch TO — "EN" on the Chinese page, "中" on
   *  the English one — and its label is written in that target language. */
  function syncToggle() {
    if (!toggle) return;
    toggle.textContent = current === "zh" ? "EN" : "中";
    const label = t("lang.toggle");
    toggle.setAttribute("aria-label", label);
    toggle.title = label;
  }

  if (toggle) {
    toggle.addEventListener("click", () => set(current === "zh" ? "en" : "zh"));
  }

  // ── First paint ──────────────────────────────────────────────────────
  // The document ships in Chinese, so zh needs no rewrite — which is exactly
  // what keeps the default look identical to the pre-i18n page.
  document.documentElement.lang = current === "zh" ? "zh-CN" : "en";
  if (current === "en") apply();
  syncToggle();
})();
