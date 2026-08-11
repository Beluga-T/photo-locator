"""Credential pre-flight: prove a key works before the user commits it.

This lives apart from providers.py for one reason. Everything here runs against a
secret the browser just typed in, and upstream error bodies routinely echo the
submitted key straight back — so every string that leaves this module is passed
through mask() and a hard length cap first. Nothing here is ever logged, and the
probes chosen below are free, so a user can retry as often as they like.
"""

from __future__ import annotations

import anthropic
import httpx

from .config import CLAUDE, OPENAI, Settings
from .overrides import safe_url, scrub

# The user is watching a spinner in the settings panel, not waiting on a vision
# call, so this deliberately ignores settings.request_timeout (240s).
PROBE_TIMEOUT = 20.0

# Enough upstream text to be diagnostic, little enough that a hostile gateway
# cannot use our own response as an amplifier.
MAX_DETAIL = 200


def _safe(text: str, secret: str) -> str:
    """Make upstream-controlled text fit to hand back to the browser.

    Delegates to overrides.scrub so this module and providers.py cannot drift:
    an earlier local copy collapsed whitespace *after* redacting, which let a
    gateway defeat it by echoing the key across a line break.
    """
    return scrub(text, secret, limit=MAX_DETAIL)


def _result(provider: str, model: str, code: str, message: str, detail: str = "") -> dict:
    # `ok` is derived rather than passed so "unconfirmed" can never be mistaken
    # for success just because nothing actually failed.
    return {
        "ok": code == "ok",
        "provider": provider,
        "model": model,
        "code": code,
        "message": message,
        "detail": detail,
    }


# --------------------------------------------------------------------------- Claude


async def _verify_claude(settings: Settings) -> dict:
    key = settings.anthropic_api_key
    model = settings.anthropic_model
    if not key:
        return _result(CLAUDE, model, "not_configured", "还没有填 Anthropic 密钥。")

    # max_retries=0: a probe should report the first failure, not spend 20s
    # silently retrying one the user is waiting to hear about.
    async with anthropic.AsyncAnthropic(api_key=key, timeout=PROBE_TIMEOUT, max_retries=0) as client:
        try:
            # GET /v1/models is unmetered — it proves the key is live without
            # spending a token. list() only builds the paginator; the request,
            # and therefore every error below, happens at the await.
            await client.models.list(limit=1)
        except anthropic.AuthenticationError:
            return _result(CLAUDE, model, "auth", "密钥无效或已过期，请检查后重新填写。")
        except anthropic.RateLimitError:
            return _result(CLAUDE, model, "rate_limited", "Anthropic 限流了，请稍后再验证。")
        except anthropic.APITimeoutError:
            # A subclass of APIConnectionError, so it has to be caught first.
            return _result(
                CLAUDE, model, "timeout", f"连接 Anthropic API 超时（{PROBE_TIMEOUT:.0f} 秒），请检查网络或代理。"
            )
        except anthropic.APIConnectionError as exc:
            return _result(
                CLAUDE, model, "network", "连不上 Anthropic API，请检查网络或代理。", _safe(str(exc), key)
            )
        except anthropic.APIStatusError as exc:
            return _result(
                CLAUDE,
                model,
                "upstream",
                f"Anthropic API 返回错误 {exc.status_code}，请稍后再试。",
                _safe(getattr(exc.response, "text", ""), key),
            )
        except Exception:  # noqa: BLE001 - an unfamiliar failure must not become a 500
            # str(exc) is withheld here: an unknown exception can carry a request
            # dump, and a request dump carries the Authorization header.
            return _result(CLAUDE, model, "upstream", "验证 Anthropic 密钥时出错了，请重试。")

    return _result(CLAUDE, model, "ok", f"密钥可用，将使用 {model}。")


# ------------------------------------------------------------ OpenAI-compatible


async def _verify_openai(settings: Settings) -> dict:
    base = settings.openai_base_url.rstrip("/")
    key = settings.openai_api_key
    model = settings.openai_model
    if not base or not key:
        return _result(OPENAI, model, "not_configured", "还没有填网关地址和密钥。")

    # Some relays carry credentials in the path or in userinfo, so the address is
    # reduced to scheme and host before it goes into a user-facing message.
    shown = safe_url(base)
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
            response = await client.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
    except httpx.TimeoutException:
        return _result(OPENAI, model, "timeout", f"连接 {shown} 超时（{PROBE_TIMEOUT:.0f} 秒），请检查网络或代理。")
    except httpx.HTTPError as exc:
        return _result(OPENAI, model, "network", f"连不上 {shown}，请检查网络或代理。", _safe(str(exc), key))
    except Exception:  # noqa: BLE001 - a malformed base_url reaches httpx as anything
        return _result(OPENAI, model, "upstream", "网关地址无效，请填到 /v1 为止，不要带 /chat/completions。")

    detail = _safe(response.text, key)
    if response.status_code == 200:
        return _result(OPENAI, model, "ok", f"网关可用，将使用 {model}。")
    if response.status_code in {404, 405}:
        # Plenty of relays proxy only /chat/completions. The host answered, so the
        # address is right; nothing here says anything about the key either way.
        return _result(OPENAI, model, "unconfirmed", "网关不支持 /models，密钥未能确认，但地址可达。", detail)
    if response.status_code in {401, 403}:
        return _result(OPENAI, model, "auth", "密钥无效或已过期，请检查后重新填写。", detail)
    if response.status_code == 429:
        return _result(OPENAI, model, "rate_limited", "网关限流了，请稍后再验证。", detail)
    return _result(OPENAI, model, "upstream", f"网关返回 {response.status_code}，请检查地址和密钥。", detail)


# --------------------------------------------------------------------------- entry


async def verify(settings: Settings) -> dict:
    """Probe the credential in `settings` without spending tokens. Never raises."""
    # No provider, no probe. Guessing which family to test would report on a
    # credential the user never asked about — and name a vendor nobody chose.
    if settings.provider not in (CLAUDE, OPENAI):
        message = (
            "Anthropic 和网关的密钥都在，但还没有选定用哪家，请先在设置里选择模型来源。"
            if settings.needs_choice
            else "还没有选择模型来源，请先在设置里选择并填好对应的密钥。"
        )
        return _result("", "", "not_configured", message)
    try:
        return await (_verify_claude(settings) if settings.provider == CLAUDE else _verify_openai(settings))
    except Exception:  # noqa: BLE001 - the settings panel gets a verdict, never a traceback
        return _result(settings.provider, settings.model, "upstream", "验证时出现未知错误，请重试。")


if __name__ == "__main__":
    import asyncio
    import json
    from dataclasses import replace

    # Shaped like a real key so a gateway would happily echo it back at us.
    BOGUS = "sk-ant-api03-" + "b0gus" * 12
    PROBE = Settings(
        provider=CLAUDE,
        provider_pinned=True,
        anthropic_api_key=BOGUS,
        anthropic_model="claude-opus-5",
        openai_base_url="http://127.0.0.1:9/v1",  # discard port: refuses instantly
        openai_api_key=BOGUS,
        openai_model="gpt-4o",
        mapbox_token="",
        max_upload_bytes=0,
        max_image_edge=0,
        requests_per_hour=0,
        refusal_fallback=False,
        request_timeout=240.0,
    )

    async def _selfcheck() -> None:
        # Neither live probe below happens to echo the key back, so the redaction
        # path is exercised directly — it is the one thing here that must hold.
        echoed = _safe(f'{{"error":"invalid api key: {BOGUS}"}}', BOGUS)
        assert BOGUS not in echoed, echoed
        straddle = _safe("x" * (MAX_DETAIL - 10) + BOGUS, BOGUS)
        assert BOGUS[13:] not in straddle and len(straddle) <= MAX_DETAIL, straddle
        assert len(_safe("f" * 10_000, BOGUS)) == MAX_DETAIL
        assert _safe("", BOGUS) == "" and _safe("plain", "") == "plain"

        # The three ways a hostile gateway defeats an exact-substring redactor.
        upper = _safe(f"bad key: {BOGUS.upper()}", BOGUS)
        assert BOGUS.upper() not in upper, upper
        wrapped = _safe(f"bad key: {BOGUS[:20]}\n   {BOGUS[20:]}", BOGUS)
        assert BOGUS not in " ".join(wrapped.split()), wrapped
        # A key we were never handed: the operator's, echoed by a relay the
        # caller chose. Only the shape gives it away.
        unknown = _safe('{"error":"invalid api key sk-proj-AAAABBBBCCCCDDDD"}', "")
        assert "sk-proj-AAAABBBBCCCCDDDD" not in unknown, unknown

        # A base URL that carries the credential in its path or userinfo.
        assert safe_url("https://relay.example/sk-Xk3ABCDEFGH9fQ/v1") == "https://relay.example"
        assert safe_url("https://user:pw@10.0.0.5:8080/v1") == "https://10.0.0.5:8080"

        # No provider chosen: no probe, no guess, and never a vendor name in
        # the verdict. PROBE holds both credential families, so with the
        # provider blanked this is the ask-for-a-decision case…
        undecided = await verify(replace(PROBE, provider="", provider_pinned=False))
        assert undecided["code"] == "not_configured" and not undecided["ok"], undecided
        assert undecided["provider"] == "" and undecided["model"] == "", undecided
        assert "选" in undecided["message"], undecided
        # …and with every credential blanked too, the plain unconfigured one.
        bare = await verify(
            replace(PROBE, provider="", provider_pinned=False, anthropic_api_key="", openai_api_key="")
        )
        assert bare["code"] == "not_configured" and bare["provider"] == "", bare
        assert bare["message"] != undecided["message"], "the two unconfigured cases must read differently"

        print(f"--- redaction\n{echoed}\n{straddle}\n{upper}\n{wrapped}\n{unknown}\n")

        for label, outcome in (
            ("bogus anthropic key", await verify(PROBE)),
            ("unreachable base_url", await verify(replace(PROBE, provider=OPENAI))),
        ):
            print(f"--- {label}")
            print(json.dumps(outcome, ensure_ascii=False, indent=2))
            exposed = outcome["message"] + outcome["detail"]
            assert BOGUS not in exposed, f"{label}: whole key leaked"
            assert BOGUS[13:] not in exposed, f"{label}: key body leaked"
            assert len(outcome["detail"]) <= MAX_DETAIL, f"{label}: detail exceeds cap"
        print("\nself-check ok — no key material in message/detail, detail within cap")

    asyncio.run(_selfcheck())
