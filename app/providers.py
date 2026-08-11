"""Model providers: Anthropic Claude (official SDK) and any OpenAI-compatible gateway."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from math import isfinite
from typing import Any

import anthropic
import httpx

from .config import CLAUDE, Settings
from .imaging import PreparedImage
from .overrides import safe_url, scrub
from .prompt import PRECISION_LEVELS, RESULT_SCHEMA, system_prompt, user_instruction
from .streaming import PartialJSON

log = logging.getLogger("locator.providers")

MAX_TOKENS = 16000
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# The request parameters the Claude ladder actually strips on its next rung.
# A 400 that does not name one of these will not be fixed by degrading — the
# retry just burns two more upstream calls and buries the real reason under a
# generic "bad_request".
_DEGRADABLE = ("output_config", "fallbacks", "beta", "effort", "json_schema", "format")

# Permanent 400s worth their own message, because the generic one sends people
# looking for a bug in the request when the fix is somewhere else entirely.
_PERMANENT_400 = (
    (
        ("credit balance", "billing", "insufficient funds", "purchase credits"),
        "billing",
        "Anthropic 账户余额不足。密钥本身是好的，去 Plans & Billing 充值后即可继续。",
        402,
    ),
    (
        ("permission", "not allowed to access", "does not have access"),
        "forbidden",
        "这个密钥没有访问该模型的权限，换一个密钥或换个模型名。",
        403,
    ),
)


def _classify_400(exc: Exception) -> LocateError | None:
    """Turn a known-permanent 400 into its own error, or None to keep degrading."""
    text = str(exc).lower()
    for markers, code, message, status in _PERMANENT_400:
        if any(marker in text for marker in markers):
            return LocateError(code, message, status=status)
    return None


def _is_degradable(exc: Exception) -> bool:
    # A TypeError never reached the API — the installed SDK simply does not know
    # the keyword, which is exactly what the next rung drops.
    if isinstance(exc, TypeError):
        return True
    return any(marker in str(exc).lower() for marker in _DEGRADABLE)

UNKNOWN = "未确定"
# Everything a model reaches for when it means "I could not tell".
UNKNOWN_MARKERS = {
    "",
    "未确定",
    "未知",
    "不确定",
    "无法确定",
    "无法判断",
    "不详",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "undetermined",
    "unidentified",
    "-",
    "—",
}

# The smallest honest radius for each precision level, in km. A country-level
# answer must not arrive wearing a five-kilometre radius.
RADIUS_FLOOR = {"locality": 0.5, "city": 5.0, "region": 50.0, "country": 200.0}


class LocateError(Exception):
    """A failure worth showing the user verbatim."""

    def __init__(self, code: str, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _not_configured(settings: Settings) -> LocateError:
    """The refusal both entry points raise before any upstream call.

    Two situations share the code but differ in the fix: no usable credentials
    (add one), or credentials for both vendors with nobody having picked
    (decide). Telling the second user to "add a key" sends them off to
    re-paste keys they already saved, so the wording splits here.
    """
    if settings.needs_choice:
        message = (
            "Anthropic 和 OpenAI 网关的密钥都填了，但还没有选定用哪家。"
            "点右上角的设置，选择模型来源后保存即可。"
        )
    else:
        message = (
            "还没有配置模型。点右上角的设置，先选择模型来源，"
            "再填入对应的 API Key 保存即可，不用重启。"
        )
    return LocateError("not_configured", message, status=503)


def _extract_json(text: str) -> dict:
    cleaned = FENCE.sub("", (text or "").strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LocateError("bad_response", "模型没有返回可解析的结果，请重试。")


def _number(value: Any) -> float | None:
    """A finite float, or None for anything that cannot honestly become one.

    Every numeric field the model writes goes through here, for two reasons the
    obvious `float(value)` misses:

    OverflowError is an ArithmeticError, NOT a subclass of ValueError, so a
    `try/except (TypeError, ValueError)` does not catch it. `{"confidence": 1e999}`
    parses to `inf` (json's parse_float is plain `float`, which never consults
    parse_constant), and `int(round(inf))` then raises OverflowError out of
    normalize — turning a merely degraded answer into a 500.

    And a non-finite value that raises nothing at all is worse, because it sails
    through: `max(0.5, inf)` is `inf`, and `max(-90.0, min(90.0, nan))` is 90.0 —
    a NaN latitude silently becoming the North Pole. Both then reach the response
    body, where `Infinity` is not a token `JSON.parse` will read.
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    number = _number(value)
    if number is None:
        return default
    return max(low, min(high, int(round(number))))


def _is_unknown(text: str) -> bool:
    return text.strip().lower() in UNKNOWN_MARKERS


def _place(raw: Any) -> dict:
    """A place name plus an honest flag for whether the model actually determined it."""
    raw = raw if isinstance(raw, dict) else {}
    name_zh = str(raw.get("name_zh") or "").strip()
    name_en = str(raw.get("name_en") or "").strip()
    if _is_unknown(name_zh):
        return {"name_zh": UNKNOWN, "name_en": "", "known": False}
    return {"name_zh": name_zh, "name_en": "" if _is_unknown(name_en) else name_en, "known": True}


def _blank_place() -> dict:
    return {"name_zh": UNKNOWN, "name_en": "", "known": False}


def _resolve_precision(declared: str, levels: dict[str, bool]) -> str:
    """Settle on the finest level we will actually publish.

    The model states how far it got, and separately fills in names. Those two can
    disagree, so we take whichever is coarser: a model that fills a city while
    admitting it only reached country level does not get to keep the city.
    """
    deepest = "country"
    for level in PRECISION_LEVELS:
        if levels.get(level):
            deepest = level

    declared = declared.strip().lower()
    if declared not in PRECISION_LEVELS:
        return deepest

    return PRECISION_LEVELS[min(PRECISION_LEVELS.index(declared), PRECISION_LEVELS.index(deepest))]


def normalize(raw: dict) -> dict:
    """Coerce a model answer into exactly the shape the frontend renders."""
    coords = raw.get("coordinates") if isinstance(raw.get("coordinates"), dict) else {}
    lat, lon = _number(coords.get("lat")), _number(coords.get("lon"))
    if lat is None or lon is None:
        # Half a coordinate is no coordinate: a lone latitude would put the pin
        # on the prime meridian.
        lat = lon = None
    else:
        lat = max(-90.0, min(90.0, lat))
        lon = max(-180.0, min(180.0, lon))

    radius = _number(coords.get("radius_km"))
    if radius is not None:
        radius = max(0.5, radius)

    # ── Precision: publish only the levels the evidence was said to support ──
    country = _place(raw.get("country"))
    region = _place(raw.get("region"))
    city = _place(raw.get("city"))
    locality_text = str(raw.get("locality") or "").strip()
    if _is_unknown(locality_text):
        locality_text = ""

    declared = str(raw.get("precision") or "")
    precision = _resolve_precision(
        declared,
        {
            "country": country["known"],
            "region": region["known"],
            "city": city["known"],
            "locality": bool(locality_text),
        },
    )
    depth = PRECISION_LEVELS.index(precision)

    # Drop anything finer than the settled precision — an under-supported city
    # name is worse than no city name at all.
    if depth < PRECISION_LEVELS.index("region"):
        region = _blank_place()
    if depth < PRECISION_LEVELS.index("city"):
        city = _blank_place()
    if depth < PRECISION_LEVELS.index("locality"):
        locality_text = ""

    if declared.strip().lower() != precision:
        log.info("precision reconciled: model said %r, publishing %r", declared, precision)

    # A coarse answer may not wear a fine radius.
    if radius is not None:
        radius = max(radius, RADIUS_FLOOR[precision])

    confidence = _clamp(raw.get("confidence"), 0, 100, 0)
    band = str(raw.get("confidence_band") or "").lower()
    if band not in {"high", "medium", "low"}:
        band = "high" if confidence >= 70 else "medium" if confidence >= 40 else "low"

    evidence = []
    for item in raw.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        weight = str(item.get("weight") or "").lower()
        evidence.append(
            {
                "category": str(item.get("category") or "其他").strip(),
                "observation": str(item.get("observation") or "").strip(),
                "implication": str(item.get("implication") or "").strip(),
                "weight": weight if weight in {"high", "medium", "low"} else "medium",
            }
        )

    alternatives = []
    for item in raw.get("alternatives") or []:
        if not isinstance(item, dict):
            continue
        alternatives.append(
            {
                "country": str(item.get("country") or "").strip(),
                "region": str(item.get("region") or "").strip(),
                "city": str(item.get("city") or "").strip(),
                "likelihood": _clamp(item.get("likelihood"), 0, 100, 0),
                "reason": str(item.get("reason") or "").strip(),
            }
        )
    alternatives.sort(key=lambda item: item["likelihood"], reverse=True)

    return {
        "country": country,
        "region": region,
        "city": city,
        "locality": locality_text,
        "precision": precision,
        "coordinates": None
        if lat is None or lon is None
        else {"lat": lat, "lon": lon, "radius_km": radius or RADIUS_FLOOR[precision]},
        "confidence": confidence,
        "confidence_band": band,
        "summary": str(raw.get("summary") or "").strip(),
        "evidence": evidence,
        "alternatives": alternatives,
        "notes": str(raw.get("notes") or "").strip(),
    }


# --------------------------------------------------------------------------- Claude


def _claude_blocks(image: PreparedImage, include_schema: bool, lang: str = "zh") -> list[dict]:
    instruction = user_instruction(lang)
    if include_schema:
        instruction += "\n\n严格按以下 JSON schema 输出，只输出 JSON 本身：\n" + json.dumps(
            RESULT_SCHEMA, ensure_ascii=False
        )
    return [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": image.media_type, "data": image.data_b64},
        },
        {"type": "text", "text": instruction},
    ]


def _claude_text(response: Any) -> str:
    return "".join(block.text for block in response.content if getattr(block, "type", "") == "text")


SERVER_SIDE_FALLBACK = "server-side-fallback-2026-07-01"


def _structured_kwargs(image: PreparedImage, settings: Settings, lang: str = "zh") -> dict:
    """The request both Claude paths make, streaming or not.

    Built in one place so the two ladders cannot drift apart — they already did
    once: the streaming path grew its own copy of this dict, and with it silently
    lost the refusal fallback rung below that the plain call still had.
    """
    return {
        "model": settings.anthropic_model,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt(lang),
        "messages": [{"role": "user", "content": _claude_blocks(image, include_schema=False, lang=lang)}],
        "output_config": {
            "effort": settings.anthropic_effort,
            "format": {"type": "json_schema", "schema": RESULT_SCHEMA},
        },
    }


def _with_refusal_fallback(structured: dict) -> dict:
    """The first rung of both ladders, when `refusal_fallback` is on — and it is
    on by default. Server-side fallback re-runs a policy-declined request on
    Anthropic's recommended substitute model inside the same call, so the user
    gets an answer instead of a refusal without a second round trip."""
    return {**structured, "betas": [SERVER_SIDE_FALLBACK], "fallbacks": "default"}


async def _call_claude(image: PreparedImage, settings: Settings, lang: str = "zh") -> dict:
    async with anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.request_timeout,
    ) as client:
        return await _claude_attempts(client, image, settings, lang)


async def _claude_attempts(
    client: Any, image: PreparedImage, settings: Settings, lang: str = "zh"
) -> dict:
    """The retry ladder, split out so the client above is always closed.

    Left inline it leaked one httpx connection pool per request, because every
    exit from this function is either a raise or a return.
    """
    structured = _structured_kwargs(image, settings, lang)

    attempts: list[tuple[str, dict]] = []
    if settings.refusal_fallback:
        attempts.append(("beta", _with_refusal_fallback(structured)))
    attempts.append(("stable", structured))
    # Last resort for older SDKs that don't know `output_config`: ask for JSON in the prompt.
    prompt_only = {k: v for k, v in structured.items() if k != "output_config"}
    prompt_only["messages"] = [
        {"role": "user", "content": _claude_blocks(image, include_schema=True, lang=lang)}
    ]
    attempts.append(("prompt-only", prompt_only))

    last_error: Exception | None = None
    for index, (label, kwargs) in enumerate(attempts):
        endpoint = client.beta.messages if label == "beta" else client.messages
        try:
            response = await endpoint.create(**kwargs)
        except (TypeError, anthropic.BadRequestError) as exc:
            last_error = exc
            detail = scrub(str(exc), settings.anthropic_api_key)

            # Stop the ladder dead on anything degrading cannot fix. Retrying a
            # billing or permission failure two more times only delays a message
            # the caller could have acted on immediately.
            known = _classify_400(exc)
            if known is not None:
                log.warning("Claude attempt %r failed permanently [%s]: %s", label, known.code, detail)
                raise known from exc

            if _is_degradable(exc) and index < len(attempts) - 1:
                log.warning("Claude attempt %r rejected, falling back: %s", label, detail)
                continue

            raise LocateError("bad_request", f"调用 Claude 失败：{detail}", status=502) from exc
        except anthropic.AuthenticationError as exc:
            raise LocateError("auth", "ANTHROPIC_API_KEY 无效或已过期。", status=502) from exc
        except anthropic.RateLimitError as exc:
            raise LocateError("rate_limited", "上游模型限流了，请稍后再试。", status=503) from exc
        except anthropic.APIConnectionError as exc:
            raise LocateError("network", "连不上 Anthropic API，请检查网络或代理。", status=502) from exc
        except anthropic.APIStatusError as exc:
            raise LocateError("upstream", f"Anthropic API 返回错误 {exc.status_code}。", status=502) from exc

        if response.stop_reason == "refusal":
            raise LocateError(
                "refused",
                "模型基于安全策略拒绝分析这张图片，请换一张。",
                status=422,
            )
        if response.stop_reason == "max_tokens":
            raise LocateError("truncated", "模型输出被截断了，请重试。", status=502)

        return _extract_json(_claude_text(response))

    raise LocateError(
        "bad_request",
        f"调用 Claude 失败：{scrub(str(last_error), settings.anthropic_api_key)}",
        status=502,
    )


# ------------------------------------------------------------ OpenAI-compatible


def _openai_messages(image: PreparedImage, include_schema: bool, lang: str = "zh") -> list[dict]:
    instruction = user_instruction(lang)
    if include_schema:
        instruction += "\n\n严格按以下 JSON schema 输出，只输出 JSON 本身：\n" + json.dumps(
            RESULT_SCHEMA, ensure_ascii=False
        )
    return [
        {"role": "system", "content": system_prompt(lang)},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image.media_type};base64,{image.data_b64}"},
                },
                {"type": "text", "text": instruction},
            ],
        },
    ]


async def _call_openai(image: PreparedImage, settings: Settings, lang: str = "zh") -> dict:
    url = f"{settings.openai_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    structured = {
        "model": settings.openai_model,
        "max_tokens": 4096,
        "messages": _openai_messages(image, include_schema=False, lang=lang),
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "photo_location", "strict": True, "schema": RESULT_SCHEMA},
        },
    }
    # Not every gateway implements json_schema; json_object and plain prompting are the fallbacks.
    loose = {
        "model": settings.openai_model,
        "max_tokens": 4096,
        "messages": _openai_messages(image, include_schema=True, lang=lang),
        "response_format": {"type": "json_object"},
    }
    bare = {k: v for k, v in loose.items() if k != "response_format"}

    # Every upstream string below is scrubbed before it reaches a log line or the
    # browser. Gateways routinely echo the submitted Authorization header back in
    # their error bodies, and when a caller overrode only the address, the key in
    # that echo is the operator's — so the raw text can never be forwarded.
    def clean(text: str) -> str:
        return scrub(text, settings.openai_api_key)

    where = safe_url(settings.openai_base_url)

    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        last_detail = ""
        for index, payload in enumerate((structured, loose, bare)):
            try:
                response = await client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException as exc:
                raise LocateError("timeout", "上游模型响应超时，请重试。", status=504) from exc
            except httpx.HTTPError as exc:
                raise LocateError("network", f"连不上 {where}。", status=502) from exc

            if response.status_code == 200:
                break

            last_detail = clean(response.text)
            if response.status_code == 401:
                raise LocateError("auth", "OPENAI_API_KEY 无效。", status=502)
            if response.status_code == 429:
                raise LocateError("rate_limited", "上游模型限流了，请稍后再试。", status=503)
            if response.status_code == 400 and index < 2:
                log.warning("Gateway rejected response_format, retrying looser: %s", last_detail)
                continue
            raise LocateError("upstream", f"上游返回 {response.status_code}：{last_detail}", status=502)
        else:
            raise LocateError("upstream", f"上游返回错误：{last_detail}", status=502)

    body = response.json()
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LocateError("bad_response", "上游返回了预期之外的结构。", status=502) from exc

    if isinstance(content, list):  # some gateways return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return _extract_json(content or "")


# --------------------------------------------------------------------------- entry


async def locate(image: PreparedImage, settings: Settings, *, lang: str = "zh") -> dict:
    # `lang` selects the prompt text and nothing else — "en" asks for English
    # prose in the narrative fields; every other branch is language-blind.
    if not settings.configured:
        raise _not_configured(settings)
    raw = await (
        _call_claude(image, settings, lang)
        if settings.provider == CLAUDE
        else _call_openai(image, settings, lang)
    )
    return normalize(raw)


# --------------------------------------------------------------- streaming


# Everything worth showing before the answer is finished, in the order the
# schema emits them — constrained decoding follows RESULT_SCHEMA's property
# order, and `precision` now leads it, so the cap on the answer arrives with the
# very first field instead of three fields after the names it governs.
#
# On a measured run the coarse fields are all on screen by 8.5s and the answer
# lands at 29s — so stopping at `coordinates` left the screen motionless for
# 20.6s, 71% of the call, which is exactly the "the model is still writing but
# nothing updates" complaint. Everything below is written in that window, so all
# of it is reported.
#
# `notes` is deliberately absent: it closes the object, so a partial for it
# would beat the final result by milliseconds and buy nothing.
PROGRESSIVE_FIELDS = (
    "precision",
    "country",
    "region",
    "city",
    "locality",
    "coordinates",
    "confidence",
    "confidence_band",
    "summary",
)

# The long fields, reported one element at a time instead of one lump at the
# end. These are the two that take the 20 seconds: evidence entries arrive
# roughly every 2s from 13.5s onward, and each one is worth a row on screen the
# moment it closes. The whole-array value is never sent — the elements already
# carried it, and evidence alone is ~4KB the browser would parse and discard.
PROGRESSIVE_ARRAYS = ("evidence", "alternatives")


async def locate_stream(
    image: PreparedImage, settings: Settings, *, lang: str = "zh"
) -> AsyncIterator[tuple[str, Any]]:
    """Yield ("partial", payload) as the answer is written, then ("final", result).

    A partial payload is one of exactly two shapes, and nothing but the presence
    of "index" distinguishes them:

        {"field": "country",  "value": {...}}             the whole field
        {"field": "evidence", "index": 0, "value": {...}}  one element of it

    A field in PROGRESSIVE_ARRAYS only ever arrives element by element; its
    whole value is never sent, so a client can render `index` as a row slot and
    replace whatever sits there.

    The point is to keep the page moving while the model is still writing the
    evidence chain. Two honest limits on how much that buys:

    thinking happens before any output, so nothing streams during it — on a
    high-effort request that is most of the wait. And a partial field is the
    model's raw claim: `normalize` has not run, so its precision reconciliation
    and radius floors have not been applied yet. Callers must treat partials as
    provisional and let the final result overwrite them.

    Only the Claude path streams. A gateway request yields nothing until it is
    finished and then a single ("final", ...) — the shape is identical, so the
    caller needs no branch.

    `lang` selects the prompt text and nothing else, exactly as in locate().
    """
    if not settings.configured:
        raise _not_configured(settings)

    if settings.provider != CLAUDE:
        yield "final", normalize(await _call_openai(image, settings, lang))
        return

    async for event in _stream_claude(image, settings, lang):
        yield event


async def _stream_claude(
    image: PreparedImage, settings: Settings, lang: str = "zh"
) -> AsyncIterator[tuple[str, Any]]:
    """Stream one Claude answer, over the same rungs the plain call would use.

    The rungs are `_claude_attempts`' first two, built from the same helpers, so
    a stream gets the server-side refusal fallback whenever the plain call would
    — the UI only ever streams, so a rung missing here is a feature nobody has.
    Its third rung, prompt-only, is deliberately absent: an SDK too old for
    `output_config` cannot be rescued mid-stream, and the downgrade to
    `_call_claude` below runs that rung anyway.
    """
    structured = _structured_kwargs(image, settings, lang)
    ladder: list[tuple[str, dict]] = []
    if settings.refusal_fallback:
        ladder.append(("beta", _with_refusal_fallback(structured)))
    ladder.append(("stable", structured))

    async with anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.request_timeout,
    ) as client:
        for rung, (label, kwargs) in enumerate(ladder):
            endpoint = client.beta.messages if label == "beta" else client.messages
            # Per rung, not per call: a retried attempt reads a brand new
            # document, so it must not resume the abandoned one's scanner.
            reader = PartialJSON(arrays=PROGRESSIVE_ARRAYS)
            # Keyed by (field, index) — on `field` alone, evidence element 1 would
            # be suppressed whenever it happened to equal element 0.
            sent: dict[tuple[str, int | None], Any] = {}
            partials = elements = 0

            try:
                async with endpoint.stream(**kwargs) as stream:
                    async for chunk in stream.text_stream:
                        for report in reader.feed(chunk):
                            field, index, value = report.field, report.index, report.value
                            if index is None:
                                # The reader reports a named array whole as well,
                                # after its elements, so `dict(reports)` still
                                # works for everyone else. Dropping it is ours to
                                # do: the elements already carried every byte.
                                #
                                # Except a restart. That one is synthetic: the
                                # model opened a SECOND array under a key it had
                                # already streamed, and the reader is telling us
                                # to throw away the rows we sent for the first —
                                # rows `json.loads` will say never existed. Drop
                                # it too and they stay on screen forever.
                                if report.restart:
                                    # The dedupe below remembers the abandoned
                                    # array's values per slot. Left in place it
                                    # would swallow any element of the new array
                                    # that happens to match, so the browser would
                                    # clear that row and never get it back — a
                                    # missing real row, worse than the stale one.
                                    for key in [k for k in sent if k[0] == field]:
                                        del sent[key]
                                    partials += 1
                                    yield "partial", {"field": field, "value": value}
                                    continue
                                if field in PROGRESSIVE_ARRAYS or field not in PROGRESSIVE_FIELDS:
                                    continue
                            elif field not in PROGRESSIVE_ARRAYS:
                                continue

                            # A repeated key is a duplicate in the model's own
                            # JSON: the reader re-reports it because json.loads
                            # would take the later value, so we forward the
                            # correction rather than leave the browser showing the
                            # value the final parse is about to discard. Per slot,
                            # not per field — an element only corrects the row it
                            # already painted.
                            slot = (field, index)
                            if slot in sent and sent[slot] == value:
                                continue
                            sent[slot] = value

                            payload: dict[str, Any] = {"field": field}
                            if index is not None:
                                payload["index"] = index
                                elements += 1
                            payload["value"] = value
                            partials += 1
                            yield "partial", payload
                    response = await stream.get_final_message()
            except (TypeError, anthropic.BadRequestError) as exc:
                detail = scrub(str(exc), settings.anthropic_api_key)

                # Same rule as the plain ladder: a billing or permission failure
                # is not a parameter problem, and retrying it only delays a
                # message the caller could already have acted on.
                known = _classify_400(exc)
                if known is not None:
                    log.warning(
                        "Claude stream %r failed permanently [%s]: %s", label, known.code, detail
                    )
                    raise known from exc

                # A rung the SDK or the model does not know costs us that rung,
                # not the stream. Only before anything was painted, though —
                # re-running a stream that already reached the browser would
                # repaint it from a second, differently-worded answer.
                if _is_degradable(exc) and partials == 0 and rung < len(ladder) - 1:
                    log.warning("Claude stream %r rejected, falling back: %s", label, detail)
                    continue

                # Streaming is an optimisation, never a reason to fail: fall back
                # to the non-streaming ladder, which knows how to degrade further.
                log.warning("Claude stream rejected, falling back to the plain call: %s", detail)
                yield "final", normalize(await _call_claude(image, settings, lang))
                return
            except anthropic.AuthenticationError as exc:
                raise LocateError("auth", "ANTHROPIC_API_KEY 无效或已过期。", status=502) from exc
            except anthropic.RateLimitError as exc:
                raise LocateError("rate_limited", "上游模型限流了，请稍后再试。", status=503) from exc
            except anthropic.APIConnectionError as exc:
                raise LocateError("network", "连不上 Anthropic API，请检查网络或代理。", status=502) from exc
            except anthropic.APIStatusError as exc:
                raise LocateError("upstream", f"Anthropic API 返回错误 {exc.status_code}。", status=502) from exc

            # How much of the answer actually reached the browser, which is the
            # one thing a "the page never updated" report needs and the one thing
            # the logs used to record nowhere: a 0-partial run and a 6-partial run
            # were byte-identical here. No credential goes near this line.
            log.info(
                "stream %s: %s partial(s), %s array element(s), reader done=%s broken=%s",
                label,
                partials,
                elements,
                reader.done,
                reader.broken,
            )
            if reader.broken or not reader.done:
                log.warning(
                    "the streamed JSON never closed cleanly, so partials stopped early "
                    "(%s sent); the final parse below is what the user gets",
                    partials,
                )
            break
        else:  # pragma: no cover - the last rung always breaks, returns or raises
            raise LocateError("bad_request", "调用 Claude 失败。", status=502)

    if response.stop_reason == "refusal":
        raise LocateError("refused", "模型基于安全策略拒绝分析这张图片，请换一张。", status=422)
    if response.stop_reason == "max_tokens":
        raise LocateError("truncated", "模型输出被截断了，请重试。", status=502)

    # The authoritative answer is always the fully parsed, normalised one — the
    # partials above are a preview of an unreconciled draft.
    yield "final", normalize(_extract_json(_claude_text(response)))
