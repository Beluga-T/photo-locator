"""Per-request credential overrides carried on X-RIL-* headers.

The layer underneath this one is the real credential store: `PUT /api/settings`
writes provider, keys, base URL and model names to `data/config.json`, and
load_settings folds that over .env at startup. This module is the "for this one
request only" channel on top of it, and it has exactly two users:

  * direct API callers — curl, a script, another program — that want to point
    one /api/locate at a different key or gateway without touching the saved
    configuration or restarting anything;
  * the settings sheet's "test connection" button, which is the one thing that
    genuinely cannot use the stored config: it has to probe a draft the user
    has typed but not yet saved, which by definition the server knows nothing
    about (see draftHeaders in web/app.js — its only caller).

Nothing about this is the browser's normal path. The settings sheet stores no
credentials of its own; the ordinary upload sends no X-RIL-* header at all, and
the stored config answers for it.

What has always been true and still is: the backend treats these headers as
request-scoped input and nothing else. Nothing here writes to data/config.json
or .env, no mutable global holds a value from a header, and no key from a header
is logged — apply_overrides returns a new Settings for the caller to use and
discard. That is a statement about this module only. It is NOT a claim that the
service keeps secrets off disk: the saved configuration is plaintext JSON in
data/, which is the whole point of it surviving a restart.

Precedence is header > data/config.json > .env > unset. A missing header means
"no opinion" and never clears what the layers underneath supplied.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from urllib.parse import urlparse

from .config import CLAUDE, EFFORT_LEVELS, OPENAI, Settings

HEADER_PREFIX = "x-ril-"
MAX_VALUE_LEN = 500

# Bearer-token shapes, used to redact keys we were never handed a copy of —
# an upstream error body echoing *its own* view of the credential, or a key
# belonging to the operator rather than the caller.
_KEYISH = re.compile(
    r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{12,}|\bBearer\s+[A-Za-z0-9._-]{12,}",
    re.IGNORECASE,
)

# Canonical wire name -> Settings field. Declared once, in the casing we echo
# back in error messages; lookup lowercases it.
_FIELDS: dict[str, str] = {
    "X-RIL-Provider": "provider",
    "X-RIL-Anthropic-Key": "anthropic_api_key",
    "X-RIL-Anthropic-Model": "anthropic_model",
    "X-RIL-Anthropic-Effort": "anthropic_effort",
    "X-RIL-OpenAI-Base": "openai_base_url",
    "X-RIL-OpenAI-Key": "openai_api_key",
    "X-RIL-OpenAI-Model": "openai_model",
}

# "auto" is not a provider, it is a request to re-resolve one — see apply_overrides.
_PROVIDERS = {"auto", CLAUDE, OPENAI}


class OverrideError(ValueError):
    """A header the caller sent is unusable. The message is shown to the user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def scrub(text: str, *secrets: str, limit: int = 200) -> str:
    """Make upstream-controlled text fit to log or hand back to the browser.

    Order matters. Whitespace is collapsed *first*: a gateway that echoes a key
    wrapped across lines would otherwise slip past an exact-substring match and
    then be reassembled by the collapse, handing the reader the key with one
    space to delete. Redaction is case-insensitive for the same reason — an
    upstream that upper-cases its error text should not defeat it.

    Truncation runs last so a key straddling the cut is redacted before the cut
    exists. The generic patterns catch keys we were never told about, including
    the operator's own when a caller-supplied address is in play.
    """
    cleaned = " ".join((text or "").split())

    # An upstream that scatters whitespace through the key defeats any
    # substring match while staying trivially readable. If the secret is in
    # there at all once whitespace is ignored, the text is not salvageable by
    # editing — discard it whole. Diagnostics are worth less than the key.
    squeezed = re.sub(r"\s+", "", cleaned).lower()
    for secret in secrets:
        if secret and len(secret) >= 8 and secret.lower() in squeezed:
            return "(上游回显了密钥，内容已丢弃)"

    for secret in secrets:
        if not secret or len(secret) < 8:
            continue
        cleaned = re.sub(re.escape(secret), mask(secret), cleaned, flags=re.IGNORECASE)

    # Anything shaped like a bearer token, whether or not we hold a copy of it.
    cleaned = _KEYISH.sub("[redacted]", cleaned)

    return cleaned[: limit - 1] + "…" if len(cleaned) > limit else cleaned


def safe_url(url: str) -> str:
    """A base URL with everything secret removed.

    Relays that carry the key in the path or in userinfo are common enough that
    echoing a URL back verbatim is its own leak, so only scheme and host survive.
    """
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return "(地址无效)"
    if not parsed.scheme or not parsed.hostname:
        return "(地址无效)"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def mask(secret: str) -> str:
    """Render a credential safe to log: enough to recognise, never enough to use.

    Short secrets would leak a disproportionate share of themselves, so they
    collapse entirely. The revealed window is 10 characters against a 14
    character floor, so the full input can never be reconstructed from the mask.
    """
    secret = secret or ""
    if len(secret) <= 14:
        return "***"
    return f"{secret[:6]}…{secret[-4:]}"


def _clean(name: str, raw: str) -> str:
    """Strip a header value and refuse anything that is not printable ASCII.

    Whitespace is a paste artifact and is forgiven; everything else is not.
    Validating after the strip is what matters — it is the returned value that
    reaches an HTTP client, and that value is guaranteed 0x20-0x7E.
    """
    value = str(raw or "").strip()
    if len(value) > MAX_VALUE_LEN:
        raise OverrideError(f"{name} 超过 {MAX_VALUE_LEN} 个字符，请确认粘贴的内容是否正确。")
    # Headers are latin-1 on the wire, so a control byte here is either an
    # attack or a mangled paste — neither is worth guessing at.
    if any(not ("\x20" <= char <= "\x7e") for char in value):
        raise OverrideError(f"{name} 含有不可打印或非 ASCII 字符，请重新复制一次。")
    return value


def _base_url(name: str, value: str) -> str:
    """Validate an OpenAI-compatible gateway root and drop its trailing slash."""
    # NOTE: this endpoint will make a server-side request to a URL the caller
    # supplied, so the service must not be exposed to an untrusted network.
    # Deliberately no private-range blocking: this is a local tool whose
    # operator already controls .env, and a blocklist here would only break
    # the self-hosted gateways it exists to support.
    try:
        parsed = urlparse(value)
    except ValueError as exc:  # malformed IPv6 literal, and little else
        raise OverrideError(f"{name} 不是一个合法的地址。") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OverrideError(f"{name} 必须是 http:// 或 https:// 开头的完整地址，填到 /v1 为止。")
    return value.rstrip("/")


def parse_overrides(headers: Mapping[str, str]) -> dict[str, str]:
    """Read the X-RIL-* headers into Settings field names.

    Only fields that were actually sent and are non-empty appear in the result.
    """
    # Starlette's Headers already folds case; a plain dict does not, so normalise
    # rather than trust the caller's type. Filtering by prefix keeps this to a
    # handful of entries — usually none.
    sent = {
        str(key).lower(): value
        for key, value in headers.items()
        if str(key).lower().startswith(HEADER_PREFIX)
    }
    if not sent:
        return {}

    changes: dict[str, str] = {}
    for name, field in _FIELDS.items():
        value = _clean(name, sent.get(name.lower(), ""))
        if not value:
            continue
        if field == "provider":
            value = value.lower()
            if value not in _PROVIDERS:
                raise OverrideError(f"{name} 只能填 auto、claude 或 openai。")
        elif field == "anthropic_effort":
            value = value.lower()
            if value not in EFFORT_LEVELS:
                raise OverrideError(f"{name} 只能填 {'、'.join(EFFORT_LEVELS)}。")
        elif field == "openai_base_url":
            value = _base_url(name, value)
        changes[field] = value

    # A caller-chosen address must never be paired with the operator's secret.
    # Otherwise `X-RIL-OpenAI-Base: https://attacker.example/v1` alone is enough
    # to make this server send its own .env OPENAI_API_KEY to that host — the
    # caller supplies the destination and we supply a credential they never had.
    # Requiring the key in the same request costs the settings sheet nothing (it
    # always sends both) and closes the hole without any address blocklist.
    if "openai_base_url" in changes and "openai_api_key" not in changes:
        raise OverrideError(
            "覆盖网关地址时必须同时提供该网关的 API Key，"
            "否则服务端会把自己 .env 里的密钥发到你指定的地址上。"
        )

    return changes


def apply_overrides(base: Settings, headers: Mapping[str, str]) -> Settings:
    """Derive the Settings for one request. `base` is never mutated."""
    changes = parse_overrides(headers)
    if not changes:
        return base  # the common path allocates nothing

    sent_provider = "provider" in changes
    merged = replace(base, **changes)

    # Whose decision the provider is, and therefore whether it may be revisited:
    #
    #   header said claude/openai   -> the user just chose; honour it
    #   header said auto            -> the user asked us to work it out
    #   no header, LLM_PROVIDER pin -> the operator chose; honour it
    #   no header, .env was auto    -> nobody chose, and the browser may have
    #                                  just supplied gateway credentials that
    #                                  change the answer, so resolve again
    #
    # Without the last case a user who fills in a gateway and leaves the
    # provider on "follow the server" silently keeps hitting Claude, because
    # load_settings already collapsed "auto" into a concrete provider at startup.
    provider = merged.provider.lower()
    explicit = provider in {CLAUDE, OPENAI} and (sent_provider or base.provider_pinned)
    if not explicit:
        provider = OPENAI if (merged.openai_base_url and merged.openai_api_key) else CLAUDE

    # An override never converts a resolution into an operator pin.
    pinned = base.provider_pinned and not sent_provider
    if provider == merged.provider and pinned == merged.provider_pinned:
        return merged
    return replace(merged, provider=provider, provider_pinned=pinned)


if __name__ == "__main__":
    # Self-check: python -m app.overrides
    def _settings(**kwargs) -> Settings:
        fields = {
            "provider": CLAUDE,
            "provider_pinned": False,
            "anthropic_api_key": "sk-ant-env-key-000000",
            "anthropic_model": "claude-opus-5",
            "openai_base_url": "",
            "openai_api_key": "",
            "openai_model": "gpt-4o",
            "mapbox_token": "pk.env",
            "max_upload_bytes": 12 * 1024 * 1024,
            "max_image_edge": 2000,
            "requests_per_hour": 40,
            "refusal_fallback": True,
            "request_timeout": 240.0,
        }
        fields.update(kwargs)
        return Settings(**fields)

    def _rejects(headers, because: str) -> str:
        try:
            parse_overrides(headers)
        except OverrideError as exc:
            assert exc.message and isinstance(exc, ValueError)
            return exc.message
        raise AssertionError(f"expected OverrideError for {because}")

    base = _settings()

    # ── mask ───────────────────────────────────────────────────────────────
    long_secret = "sk-ant-api03-ABCDEFGHIJKLMNOP"
    assert mask(long_secret) == "sk-ant…MNOP", mask(long_secret)
    assert long_secret not in mask(long_secret)
    assert mask("x" * 15) == "xxxxxx…xxxx"
    assert mask("x" * 14) == "***"  # boundary: only *longer than* 14 is revealed
    assert mask("short") == "***"
    assert mask("") == "***"
    print("mask       ", mask(long_secret), mask("x" * 14), mask(""))

    # ── parse_overrides: presence ──────────────────────────────────────────
    assert parse_overrides({}) == {}
    assert parse_overrides({"content-type": "image/jpeg"}) == {}
    assert parse_overrides({"X-RIL-OpenAI-Key": "   "}) == {}  # blank is "no opinion"
    assert parse_overrides({"x-ril-anthropic-key": "  sk-ant-pasted  "}) == {
        "anthropic_api_key": "sk-ant-pasted"
    }
    full = parse_overrides(
        {
            "X-RIL-Provider": "OpenAI",
            "X-RIL-Anthropic-Key": "sk-ant-browser",
            "X-RIL-Anthropic-Model": "claude-haiku-5",
            "X-RIL-OpenAI-Base": "https://gw.example.com/v1/",
            "X-RIL-OpenAI-Key": "sk-oai-browser",
            "X-RIL-OpenAI-Model": "qwen-vl-max",
        }
    )
    assert full == {
        "provider": OPENAI,
        "anthropic_api_key": "sk-ant-browser",
        "anthropic_model": "claude-haiku-5",
        "openai_base_url": "https://gw.example.com/v1",  # trailing / stripped
        "openai_api_key": "sk-oai-browser",
        "openai_model": "qwen-vl-max",
    }, full
    print("parse full ", full["provider"], full["openai_base_url"])

    # ── parse_overrides: rejections ────────────────────────────────────────
    print("reject len ", _rejects({"X-RIL-OpenAI-Key": "k" * (MAX_VALUE_LEN + 1)}, "too long"))
    print("reject ctrl", _rejects({"X-RIL-OpenAI-Key": "sk-a\x00b"}, "control char"))
    print("reject utf8", _rejects({"X-RIL-Anthropic-Model": "克劳德"}, "non-ascii"))
    print("reject prov", _rejects({"X-RIL-Provider": "gemini"}, "unknown provider"))
    print("reject sch ", _rejects({"X-RIL-OpenAI-Base": "ftp://gw.example.com/v1"}, "scheme"))
    print("reject bare", _rejects({"X-RIL-OpenAI-Base": "gw.example.com/v1"}, "no scheme"))
    print("reject host", _rejects({"X-RIL-OpenAI-Base": "https:///v1"}, "no netloc"))
    assert parse_overrides({"X-RIL-OpenAI-Key": "k" * MAX_VALUE_LEN})  # at the limit is fine

    # A base URL without its own key is refused: pairing a caller-chosen address
    # with the operator's .env secret would hand that secret to the address.
    print("reject solo", _rejects({"X-RIL-OpenAI-Base": "https://gw.example.com/v1"}, "base w/o key"))
    paired = parse_overrides(
        {"X-RIL-OpenAI-Base": "http://127.0.0.1:8000/v1", "X-RIL-OpenAI-Key": "sk-oai-browser"}
    )
    assert paired["openai_base_url"] == "http://127.0.0.1:8000/v1"  # private addresses allowed
    assert paired["openai_api_key"] == "sk-oai-browser"

    # ── scrub / safe_url ───────────────────────────────────────────────────
    SECRET = "sk-ant-api03-" + "s3cret" * 8
    assert SECRET not in scrub(f"bad key: {SECRET}", SECRET)
    assert SECRET.upper() not in scrub(f"bad key: {SECRET.upper()}", SECRET)
    assert scrub(f"bad key: {SECRET[:20]}\n  {SECRET[20:]}", SECRET).startswith("(上游回显")
    assert "sk-proj-AAAABBBBCCCCDDDD" not in scrub("invalid sk-proj-AAAABBBBCCCCDDDD", "")
    assert "Bearer abcdefghijklmnop" not in scrub("sent Bearer abcdefghijklmnop", "")
    assert len(scrub("f" * 9000, "", limit=200)) == 200
    assert safe_url("https://relay.example/sk-Xk3ABCDEFGH9fQ/v1") == "https://relay.example"
    assert safe_url("https://user:pw@10.0.0.5:8080/v1") == "https://10.0.0.5:8080"
    assert safe_url("not a url") == "(地址无效)"
    print("scrub       ok")

    # ── apply_overrides ────────────────────────────────────────────────────
    assert apply_overrides(base, {}) is base  # identity, not a copy
    assert apply_overrides(base, {"user-agent": "curl"}) is base

    one = apply_overrides(base, {"X-RIL-Anthropic-Key": "sk-ant-browser-key"})
    assert one is not base and one.anthropic_api_key == "sk-ant-browser-key"
    assert one.anthropic_model == base.anthropic_model  # untouched fields survive
    assert one.mapbox_token == base.mapbox_token and one.requests_per_hour == 40
    assert base.anthropic_api_key == "sk-ant-env-key-000000"  # base never mutated

    # auto + a complete OpenAI pair resolves to openai
    auto_openai = apply_overrides(
        base,
        {
            "X-RIL-Provider": "auto",
            "X-RIL-OpenAI-Base": "https://gw.example.com/v1",
            "X-RIL-OpenAI-Key": "sk-oai-browser",
        },
    )
    assert auto_openai.provider == OPENAI and auto_openai.configured
    assert auto_openai.model == "gpt-4o"

    # auto with only half a pair falls back to claude
    auto_claude = apply_overrides(
        base, {"X-RIL-Provider": "auto", "X-RIL-OpenAI-Key": "sk-oai-browser"}
    )
    assert auto_claude.provider == CLAUDE and auto_claude.model == "claude-opus-5"

    # an explicit provider is never second-guessed
    pinned = apply_overrides(
        base,
        {
            "X-RIL-Provider": "claude",
            "X-RIL-OpenAI-Base": "https://gw.example.com/v1",
            "X-RIL-OpenAI-Key": "sk-oai-browser",
        },
    )
    assert pinned.provider == CLAUDE

    # a base that was never resolved (provider unset) still lands somewhere valid
    unset = apply_overrides(_settings(provider=""), {"X-RIL-Anthropic-Key": "sk-ant-x"})
    assert unset.provider == CLAUDE
    unset_openai = apply_overrides(
        _settings(provider="", openai_base_url="https://gw.example.com/v1"),
        {"X-RIL-OpenAI-Key": "sk-oai-x"},
    )
    assert unset_openai.provider == OPENAI

    # the browser can rescue a server that has no key at all
    empty = _settings(anthropic_api_key="")
    assert not empty.configured
    assert apply_overrides(empty, {"X-RIL-Anthropic-Key": "sk-ant-browser"}).configured

    print("apply      ", auto_openai.provider, auto_claude.provider, pinned.provider)
    print("self-check ok")
