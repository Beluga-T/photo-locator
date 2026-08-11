"""Runtime configuration, read from environment variables (or a .env file)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

CLAUDE = "claude"
OPENAI = "openai"

# Anthropic's effort ladder, coarsest first. It is the main latency and cost
# lever on Claude: it governs how long the model thinks before answering, and
# on Opus 5 the lower rungs stay surprisingly strong. Claude-only — the
# OpenAI-compatible path has no equivalent and ignores it.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# Anthropic's own default is "high". This app ships one rung lower on purpose:
# a single vision inference is not the long-horizon agentic work "high" is
# tuned for, and on Opus 5 the lower rungs hold up unusually well — "medium"
# answers noticeably faster for a quality difference that is hard to see here.
# It also keeps thinking well clear of MAX_TOKENS, which caps thinking and
# response text together. Raise it in the UI or via ANTHROPIC_EFFORT.
DEFAULT_EFFORT = "medium"


def _text(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _int(name: str, default: int) -> int:
    raw = _text(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _effort(name: str) -> str:
    """An effort level, falling back to the default rather than erroring.

    A typo here should not take the service down at import time — the request
    path validates browser-supplied values strictly, but .env gets the same
    forgiving treatment as every other setting in this file.
    """
    raw = _text(name).lower()
    return raw if raw in EFFORT_LEVELS else DEFAULT_EFFORT


def _bool(name: str, default: bool) -> bool:
    raw = _text(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    provider: str
    anthropic_api_key: str
    anthropic_model: str
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    mapbox_token: str
    max_upload_bytes: int
    max_image_edge: int
    requests_per_hour: int
    refusal_fallback: bool
    request_timeout: float

    # Deployment-shaped fields, kept last and defaulted. Every test and module
    # self-check builds a Settings by hand, so a new mandatory field silently
    # kills them all at import — which is exactly how the earlier redaction
    # self-check stopped running without anyone noticing. Defaults keep those
    # constructors valid; load_settings always passes both explicitly.

    # Whether LLM_PROVIDER named a provider outright, as opposed to "auto"
    # resolving to one. Once resolved the two are indistinguishable in
    # `provider`, but they must behave differently when a browser later supplies
    # gateway credentials: an explicit pin is the operator's decision and stands,
    # while an auto-resolved value has to be worked out again. Defaulting to
    # False is the safe direction — it permits re-resolution rather than
    # silently freezing a provider nobody chose.
    provider_pinned: bool = False

    # Client addresses whose X-Forwarded-For header may be believed. Empty means
    # nobody's: the header is trivially forged, and trusting it unconditionally
    # lets one caller mint an unlimited number of rate-limit buckets.
    trusted_proxies: frozenset[str] = frozenset()

    # How hard Claude thinks before answering. Sits here with the defaulted
    # fields for dataclass ordering reasons, not because it is deployment-shaped
    # — it is a per-request model parameter the browser can override.
    anthropic_effort: str = DEFAULT_EFFORT

    @property
    def model(self) -> str:
        return self.anthropic_model if self.provider == CLAUDE else self.openai_model

    @property
    def configured(self) -> bool:
        if self.provider == CLAUDE:
            return bool(self.anthropic_api_key)
        return bool(self.openai_base_url and self.openai_api_key)


def load_settings(stored: Mapping[str, str] | None = None) -> Settings:
    """Build the effective settings.

    Three layers, coarsest last: what the user saved in the UI (`stored`, read
    from data/config.json) beats .env, which beats the defaults written here.
    The UI layer exists because a released build has no .env for anyone to edit
    — the app has to be configurable through its own interface and remember the
    answer across restarts.

    `stored` is passed in rather than read here so this module keeps knowing
    nothing about the filesystem, and so callers can build a Settings for a
    single request without touching disk.
    """
    saved = {key: str(value).strip() for key, value in (stored or {}).items() if str(value).strip()}

    def pick(field: str, env: str, default: str = "") -> str:
        return saved.get(field) or _text(env, default)

    anthropic_api_key = pick("anthropic_api_key", "ANTHROPIC_API_KEY")
    openai_base_url = pick("openai_base_url", "OPENAI_BASE_URL").rstrip("/")
    openai_api_key = pick("openai_api_key", "OPENAI_API_KEY")

    effort = saved.get("anthropic_effort", "").lower()
    if effort not in EFFORT_LEVELS:
        effort = _effort("ANTHROPIC_EFFORT")

    provider = pick("provider", "LLM_PROVIDER", "auto").lower()
    provider_pinned = provider in {CLAUDE, OPENAI}
    if not provider_pinned:
        # auto: an explicitly configured OpenAI-compatible gateway wins, else Claude.
        provider = OPENAI if (openai_base_url and openai_api_key) else CLAUDE

    return Settings(
        provider=provider,
        provider_pinned=provider_pinned,
        anthropic_api_key=anthropic_api_key,
        anthropic_model=pick("anthropic_model", "ANTHROPIC_MODEL", "claude-opus-5"),
        anthropic_effort=effort,
        openai_base_url=openai_base_url,
        openai_api_key=openai_api_key,
        openai_model=pick("openai_model", "OPENAI_MODEL", "gpt-4o"),
        # Sent to the browser so the map can render, so this must be a public
        # (pk.*) token with URL restrictions — never a secret sk.* one.
        mapbox_token=pick("mapbox_token", "MAPBOX_TOKEN"),
        trusted_proxies=frozenset(
            part.strip() for part in _text("TRUSTED_PROXIES").split(",") if part.strip()
        ),
        max_upload_bytes=_int("MAX_UPLOAD_MB", 12) * 1024 * 1024,
        max_image_edge=_int("MAX_IMAGE_EDGE", 2000),
        requests_per_hour=_int("REQUESTS_PER_HOUR", 40),
        refusal_fallback=_bool("REFUSAL_FALLBACK", True),
        request_timeout=float(_int("REQUEST_TIMEOUT_SECONDS", 240)),
    )
