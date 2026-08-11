"""FastAPI application: static frontend, /api/locate, and the credential plumbing.

Configuration arrives in three layers, coarsest last:

  1. X-RIL-* request headers — one request only, never stored.
  2. data/config.json — what a user saved in the settings sheet. This is the
     layer that makes a released build usable: it has no .env for anyone to
     edit, so the app has to be configurable through its own UI and remember
     the answer across restarts.
  3. .env, then the defaults in config.py.

`settings` is the module-level effective view of layers 2 and 3. It is rebuilt
whenever the stored config changes, and never mutated in place — request paths
derive their own Settings and write nothing back.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import CLAUDE, load_settings
from .imaging import ImageError, prepare
from .overrides import OverrideError, apply_overrides, mask
from .providers import LocateError, locate, locate_stream
from .store import CONFIG_FIELDS, Store
from .verify import verify

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s")
log = logging.getLogger("locator")

store = Store()
settings = load_settings(store.read_config())
WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


def _reload_settings() -> None:
    """Rebuild the effective settings after the stored config changed.

    Rebinding the module global is enough: every reader looks it up at call
    time, so no request can be holding a stale copy.
    """
    global settings
    settings = load_settings(store.read_config())

app = FastAPI(title="Reverse Image Location", docs_url=None, redoc_url=None)

_hits: dict[str, deque[float]] = defaultdict(deque)

# Above this many tracked clients the table is swept for expired buckets. It is
# a memory backstop, not a limit: a real deployment never approaches it, and a
# forged-header flood is what makes it necessary.
_HITS_SWEEP_AT = 4096


def _sweep(window_start: float) -> None:
    """Drop buckets whose hits have all aged out. Without this, every distinct
    client address ever seen keeps a dict entry and a deque forever."""
    stale = [key for key, hits in _hits.items() if not hits or hits[-1] < window_start]
    for key in stale:
        _hits.pop(key, None)


def _rate_limited(client_ip: str) -> bool:
    if settings.requests_per_hour <= 0:
        return False
    now = time.monotonic()
    window_start = now - 3600

    if len(_hits) > _HITS_SWEEP_AT:
        _sweep(window_start)

    hits = _hits[client_ip]
    while hits and hits[0] < window_start:
        hits.popleft()
    if len(hits) >= settings.requests_per_hour:
        return True
    hits.append(now)
    return False


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _sse(event: str, data: Any) -> str:
    """One Server-Sent Event, or "" for a frame that could not be encoded.

    `ensure_ascii` because the payload is Chinese and a proxy that mangles UTF-8
    mid-frame would corrupt the stream.

    `allow_nan=False` because its default, True, lets `json.dumps` emit bare
    `NaN` / `Infinity` / `-Infinity` — tokens that are not JSON and that the
    browser's `JSON.parse` throws on, losing the whole frame rather than the one
    number. streaming.py refuses those *literal* tokens as it reads the model's
    output, but that is not the only way one arrives: an overflowing numeric
    literal like `1e999` goes through `parse_float=float`, never consults
    `parse_constant`, and lands as `inf` — `json.loads("1e999")` returns `inf`
    today. Whatever the route, it stops here.

    An unencodable *partial* is dropped rather than raised: the alternative is a
    ValueError out of the generator, which ends the entire stream. Partials are
    provisional and the authoritative result frame overwrites them, so losing one
    costs a repaint.

    That reasoning does not extend to `result`, and treating it the same way was
    a real bug: the client waits for a `result` or an `error` and gets neither,
    so the page sits on its provisional card forever with nothing to overwrite it
    and nothing to fail on. So an unencodable non-partial raises, and the route's
    handler turns it into an `error` frame the page can actually show.
    """
    try:
        body = json.dumps(data, ensure_ascii=True, allow_nan=False)
    except ValueError:
        # No payload in the log line: it is model-shaped text, and the reason is
        # structural rather than interesting.
        log.warning("unencodable %r SSE frame (a non-finite number)", event)
        if event == "partial":
            return ""
        raise
    return f"event: {event}\ndata: {body}\n\n"


def _sse_error(code: str, message: str) -> Response:
    """Refuse a stream request in the stream's own language.

    Answering with a plain 4xx JSON body would work, but the client is an
    EventSource-shaped reader; giving it one `error` event keeps both failure
    paths identical on the page.
    """
    return StreamingResponse(
        iter([_sse("error", {"code": code, "message": message})]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def _locate_payload(
    result: dict, prepared: Any, effective: Any, elapsed_ms: int
) -> dict[str, Any]:
    """The response body both /api/locate and its streaming twin return."""
    return {
        "result": result,
        "meta": {
            "elapsedMs": elapsed_ms,
            # What actually ran, which may be a per-request override rather
            # than the server's stored configuration.
            "provider": effective.provider,
            "model": effective.model,
            "analyzedSize": [prepared.width, prepared.height],
            "sourceSize": [prepared.source_width, prepared.source_height],
            "exifGps": prepared.exif_gps,
        },
    }


def _log_located(result: dict, effective: Any, elapsed_ms: int, progress: str = "") -> None:
    """The one line per completed request. `progress` records how much of the
    answer was streamed before it — without it a run that painted six partials
    and a run that painted none write byte-identical logs, so "the page never
    updated" arrives with no evidence at all. It is counts only: `mask` is the
    only way a credential is ever allowed near the log."""
    headline = result[result["precision"]] if result["precision"] != "locality" else None
    credential = (
        effective.anthropic_api_key if effective.provider == CLAUDE else effective.openai_api_key
    )
    log.info(
        "located in %sms  precision=%s  place=%s  confidence=%s  via %s/%s effort=%s key=%s%s",
        elapsed_ms,
        result["precision"],
        headline["name_zh"] if headline else result["locality"],
        result["confidence"],
        effective.provider,
        effective.model,
        effective.anthropic_effort if effective.provider == CLAUDE else "n/a",
        mask(credential),
        progress,
    )


def _client_ip(request: Request) -> str:
    """Who to charge for this request.

    X-Forwarded-For is believed only from an address the operator listed in
    TRUSTED_PROXIES. Anyone can set the header, so trusting it unconditionally
    turns the per-IP rate limit into no limit at all: a caller just varies the
    value and gets a fresh quota each time.

    This check is necessary but not sufficient, and the reason is easy to miss.
    uvicorn enables --proxy-headers by default, and its own middleware rewrites
    request.client from X-Forwarded-For *before* any of this runs — so for peers
    uvicorn already trusts (its default is 127.0.0.1) `peer` below is the header
    value, not the socket. Run with --no-proxy-headers unless a real proxy sits
    in front; startup logs a warning about this.
    """
    peer = request.client.host if request.client else "unknown"
    if peer in settings.trusted_proxies:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return peer


@app.get("/api/config")
async def read_config() -> dict:
    """What the server itself is holding. Never includes a model credential —
    only whether one exists, so the UI can say who is supplying it."""
    return {
        "provider": settings.provider,
        # Whether LLM_PROVIDER pinned that provider or "auto" merely resolved to
        # it. The browser needs the difference to predict which provider a
        # request will use, or the chip in the bar can contradict the backend.
        "providerPinned": settings.provider_pinned,
        "model": settings.model,
        # The server's default thinking depth. The browser may override it per
        # request; publishing it lets the settings sheet say what "follow the
        # server" actually resolves to.
        "effort": settings.anthropic_effort,
        "configured": settings.configured,
        "maxUploadMb": round(settings.max_upload_bytes / (1024 * 1024)),
        # Which credentials .env holds — presence only, never a value. The
        # browser needs this to predict which provider a request will resolve
        # to; without it, a half-filled .env (say a key but no base URL, or a
        # credential for the provider that did not win) makes the chip in the
        # bar name one provider while the request uses the other.
        "hasAnthropicKey": bool(settings.anthropic_api_key),
        "hasOpenaiBase": bool(settings.openai_base_url),
        "hasOpenaiKey": bool(settings.openai_api_key),
        # Public Mapbox token; absent means the frontend falls back to its
        # schematic globe instead of a real map. Public pk.* tokens are meant
        # to reach the browser — model keys are not, and never appear here.
        # A secret sk.* token would be a real leak, so it is withheld even
        # though .env is the operator's own file.
        "mapboxToken": "" if settings.mapbox_token.startswith("sk.") else settings.mapbox_token,
    }


# ── Saved settings ────────────────────────────────────────────────────
# These read and write data/config.json, which is what makes a released build
# usable without a .env. Note what that costs: the port has no authentication,
# so anyone who can reach it can rewrite the operator's credentials. That is
# acceptable for a loopback-only tool and unacceptable for anything else — see
# the security section of the README.


@app.get("/api/settings")
async def read_settings() -> dict:
    """What the user saved, with every secret masked.

    Deliberately not `store.read_config()`: that returns keys in the clear and
    exists only for the server's own request path.
    """
    return {"config": store.public_config(), "historyCount": len(store.list_shots())}


@app.put("/api/settings")
async def write_settings(request: Request) -> JSONResponse:
    try:
        patch = await request.json()
    except Exception:  # noqa: BLE001 - any malformed body is the same answer
        return _error("bad_json", "请求体不是合法的 JSON。", 400)
    if not isinstance(patch, dict):
        return _error("bad_json", "请求体必须是一个 JSON 对象。", 400)

    # Same confused-deputy rule the header layer enforces: a caller who changes
    # the gateway address must supply that gateway's own key in the same
    # request. Otherwise setting only the address points the operator's stored
    # key at an address the caller chose.
    new_base = str(patch.get("openai_base_url", "") or "").strip()
    if new_base and new_base != store.read_config().get("openai_base_url", ""):
        if not str(patch.get("openai_api_key", "") or "").strip():
            return _error(
                "bad_override",
                "改网关地址时必须同时填该网关的 API Key，否则服务端会把已保存的密钥发到新地址上。",
                400,
            )

    store.write_config(patch)
    _reload_settings()
    # Field names only — never a value.
    touched = sorted(key for key in patch if key in CONFIG_FIELDS)
    log.info("settings updated: %s", ", ".join(touched) or "(nothing recognised)")
    return JSONResponse({"config": store.public_config()})


@app.delete("/api/settings")
async def clear_settings() -> dict:
    store.clear_config()
    _reload_settings()
    log.info("saved settings cleared; falling back to .env and defaults")
    return {"config": store.public_config()}


# ── Saved history ─────────────────────────────────────────────────────


@app.get("/api/history")
async def read_history() -> dict:
    return {"shots": store.list_shots()}


@app.get("/api/history/{shot_id}/image")
async def read_history_image(shot_id: str) -> Response:
    found = store.read_shot(shot_id)
    if found is None:
        return _error("not_found", "这张照片已经不在历史里了。", 404)
    image, media_type = found
    # Private by definition: it is the user's own photo, and a shared cache
    # between browser profiles is not something to invite.
    return Response(image, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})


@app.delete("/api/history/{shot_id}")
async def delete_history_shot(shot_id: str) -> dict:
    return {"deleted": store.delete_shot(shot_id)}


@app.delete("/api/history")
async def clear_history() -> dict:
    removed = store.clear_shots()
    log.info("history cleared: %s shot(s) removed", removed)
    return {"removed": removed}


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/verify")
async def api_verify(request: Request) -> JSONResponse:
    """Confirm a credential works before the user commits to it.

    Rate limited alongside /api/locate: it makes an outbound request per call,
    so leaving it open would turn the service into a traffic amplifier.
    """
    if _rate_limited(_client_ip(request)):
        return _error("rate_limited", "请求太频繁了，请过一会儿再试。", 429)

    try:
        effective = apply_overrides(settings, request.headers)
    except OverrideError as exc:
        return _error("bad_override", exc.message, 400)

    return JSONResponse(await verify(effective))


@app.post("/api/locate/stream")
async def api_locate_stream(request: Request, image: UploadFile) -> Response:
    """Same job as /api/locate, but reported as it happens.

    Emits Server-Sent Events so the page keeps moving while the model is still
    writing the evidence chain:

        event: partial   {"field": "precision", "value": "city"}  provisional
        event: partial   {"field": "country", "value": {...}}
        event: partial   {"field": "evidence", "index": 0, "value": {...}}
        event: result    {"result": {...}, "meta": {...}}         authoritative
        event: error     {"code": "...", "message": "..."}

    An `index` on a partial means the value is that one element of the named
    array field, to be rendered at that position; without it the value is the
    whole field. An array field never arrives whole as a partial — the elements
    already carried it.

    `precision` leads, because RESULT_SCHEMA declares it first: the client knows
    the cap on the answer before the first name it governs arrives.

    A `partial` is the model's raw claim with none of normalize()'s
    reconciliation applied, so the client must let `result` overwrite it.
    Neither shape needs anything of `_sse` beyond `json.dumps`: the payload is
    already a plain dict, and the extra key rides along with it.
    """
    if _rate_limited(_client_ip(request)):
        return _sse_error("rate_limited", "请求太频繁了，请过一会儿再试。")

    try:
        effective = apply_overrides(settings, request.headers)
    except OverrideError as exc:
        return _sse_error("bad_override", exc.message)

    raw = await image.read()
    if not raw:
        return _sse_error("empty", "没有收到图片内容。")
    if len(raw) > settings.max_upload_bytes:
        limit = round(settings.max_upload_bytes / (1024 * 1024))
        return _sse_error("too_large", f"图片超过 {limit} MB，请压缩后再上传。")

    try:
        prepared = prepare(raw, settings.max_image_edge)
    except ImageError as exc:
        return _sse_error("bad_image", str(exc))

    async def events() -> AsyncIterator[str]:
        started = time.monotonic()
        # What actually reached the browser, counted here rather than taken on
        # trust from the provider: this is the number a "nothing updated on the
        # page" report needs, and 0 is a perfectly ordinary value — the gateway
        # path streams no partials at all, and a Claude call that degraded to the
        # plain ladder streams none either.
        partials = elements = 0
        try:
            async for kind, data in locate_stream(prepared, effective):
                if kind == "partial":
                    partials += 1
                    if isinstance(data, dict) and "index" in data:
                        elements += 1
                    yield _sse("partial", data)
                    continue

                result = data
                elapsed_ms = round((time.monotonic() - started) * 1000)
                payload = _locate_payload(result, prepared, effective, elapsed_ms)
                saved = store.add_shot(prepared.data, prepared.media_type, payload)
                if saved is not None:
                    payload["meta"]["shotId"] = saved["id"]
                _log_located(
                    result,
                    effective,
                    elapsed_ms,
                    f"  streamed={partials} partial(s) incl. {elements} array element(s)",
                )
                yield _sse("result", payload)
        except LocateError as exc:
            log.warning(
                "locate failed [%s] %s  (after %s streamed partial(s))",
                exc.code,
                exc.message,
                partials,
            )
            yield _sse("error", {"code": exc.code, "message": exc.message})
        except Exception:  # noqa: BLE001 - never leak a stack trace to the browser
            log.exception("unexpected failure during streaming locate after %s partial(s)", partials)
            yield _sse("error", {"code": "internal", "message": "服务端出错了，请查看后端日志。"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # Without this an nginx in front buffers the whole response and the
            # progressive rendering silently becomes a slow single update.
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/locate")
async def api_locate(request: Request, image: UploadFile) -> JSONResponse:
    if _rate_limited(_client_ip(request)):
        return _error("rate_limited", "请求太频繁了，请过一会儿再试。", 429)

    # Browser-supplied credentials apply to this request only. The operator's
    # limits below deliberately keep reading `settings`, never `effective` —
    # a header must not be able to lift a cap the operator set in .env.
    try:
        effective = apply_overrides(settings, request.headers)
    except OverrideError as exc:
        return _error("bad_override", exc.message, 400)

    raw = await image.read()
    if not raw:
        return _error("empty", "没有收到图片内容。", 400)
    if len(raw) > settings.max_upload_bytes:
        limit = round(settings.max_upload_bytes / (1024 * 1024))
        return _error("too_large", f"图片超过 {limit} MB，请压缩后再上传。", 413)

    try:
        prepared = prepare(raw, settings.max_image_edge)
    except ImageError as exc:
        return _error("bad_image", str(exc), 400)

    started = time.monotonic()
    try:
        result = await locate(prepared, effective)
    except LocateError as exc:
        log.warning("locate failed [%s] %s", exc.code, exc.message)
        return _error(exc.code, exc.message, exc.status)
    except Exception:  # noqa: BLE001 - never leak a stack trace to the browser
        log.exception("unexpected failure during locate")
        return _error("internal", "服务端出错了，请查看后端日志。", 500)

    elapsed_ms = round((time.monotonic() - started) * 1000)
    payload = _locate_payload(result, prepared, effective, elapsed_ms)

    # Keep the shot so the rail survives a restart. The downscaled JPEG is
    # stored rather than the upload: it is what the model actually saw, it is
    # smaller, and imaging.prepare has already stripped the EXIF — so the GPS
    # the original may have carried does not end up on disk either.
    saved = store.add_shot(prepared.data, prepared.media_type, payload)
    if saved is not None:
        payload["meta"]["shotId"] = saved["id"]

    _log_located(result, effective, elapsed_ms)
    return JSONResponse(payload)


app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="web")


@app.on_event("startup")
async def announce() -> None:
    if settings.mapbox_token.startswith("sk."):
        log.warning(
            "MAPBOX_TOKEN looks like a secret token (sk.*) — it is withheld from "
            "the browser, so the map will not render. Use a public pk.* token."
        )
    if not settings.configured:
        missing = "ANTHROPIC_API_KEY" if settings.provider == CLAUDE else "OPENAI_BASE_URL / OPENAI_API_KEY"
        log.warning(
            "Model provider not configured — open the settings sheet in the "
            "page (top right) and paste your key there, or set %s in .env",
            missing,
        )
    else:
        log.info("Provider %s  model %s", settings.provider, settings.model)
    log.info(
        "Rate limit %s req/hour per client; X-Forwarded-For trusted from %s",
        settings.requests_per_hour or "off",
        ", ".join(sorted(settings.trusted_proxies)) or "nobody",
    )
    if settings.requests_per_hour > 0 and not settings.trusted_proxies:
        # uvicorn's own --proxy-headers is on by default and rewrites the client
        # address from X-Forwarded-For for peers it trusts, which happens before
        # this app sees the request. Left on, a caller can vary that header and
        # mint a fresh rate-limit bucket per value.
        log.warning(
            "If this was not started with --no-proxy-headers, uvicorn trusts "
            "X-Forwarded-For from loopback and the per-IP rate limit can be "
            "bypassed by forging it. Pass the flag unless a trusted proxy is in front."
        )
