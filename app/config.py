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


def infer_provider(anthropic_key: str, openai_base: str, openai_key: str) -> str:
    """The provider the credentials alone imply, or "" when they do not decide.

    Inference, never preference: exactly one usable credential family names its
    provider. Both present, or neither, names nobody — guessing here is how a
    fresh install ends up claiming Claude, or a two-key .env silently picks a
    vendor the operator never chose.
    """
    claude_ready = bool(anthropic_key)
    openai_ready = bool(openai_base and openai_key)  # half a pair is no family
    if claude_ready == openai_ready:  # both or neither: undecidable either way
        return ""
    return CLAUDE if claude_ready else OPENAI


@dataclass(frozen=True)
class Settings:
    # "claude", "openai", or "" — "" means nobody chose and the credentials do
    # not decide it either (none present, or both families present). It is a
    # real, servable state: /api/config reports it unconfigured and the locate
    # routes refuse with a message saying what to do, rather than any code path
    # quietly assuming a vendor the user never picked.
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

    # Whether the provider was named outright (stored config or LLM_PROVIDER),
    # as opposed to inferred from which credentials exist. Once resolved the two
    # are indistinguishable in `provider`, but they must behave differently when
    # a browser later supplies gateway credentials: an explicit pin is the
    # operator's decision and stands, while an inferred value has to be worked
    # out again. Defaulting to False is the safe direction — it permits
    # re-inference rather than silently freezing a provider nobody chose.
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
        if self.provider == CLAUDE:
            return self.anthropic_model
        if self.provider == OPENAI:
            return self.openai_model
        # No provider chosen means no model to name. Anything else here is how
        # a default model id ends up on screen as if the user had picked it.
        return ""

    @property
    def configured(self) -> bool:
        if self.provider == CLAUDE:
            return bool(self.anthropic_api_key)
        if self.provider == OPENAI:
            return bool(self.openai_base_url and self.openai_api_key)
        return False

    @property
    def needs_choice(self) -> bool:
        """Both credential families are usable but nobody picked a provider.

        The one unconfigured state that adding a key cannot fix — the fix is a
        decision, so /api/config and the locate error word it differently.
        """
        return (
            not self.provider
            and bool(self.anthropic_api_key)
            and bool(self.openai_base_url and self.openai_api_key)
        )


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

    provider = pick("provider", "LLM_PROVIDER").lower()
    if provider == "auto":
        # Legacy spelling of "unset": pre-0.3 clients and .env files wrote it,
        # and a stored config may still say it. Accepted forever, offered nowhere.
        provider = ""
    provider_pinned = provider in {CLAUDE, OPENAI}
    if not provider_pinned:
        # Nothing explicit (unset, "auto", or an unknown value): infer from the
        # credentials, which may honestly conclude "" — see infer_provider.
        provider = infer_provider(anthropic_api_key, openai_base_url, openai_api_key)

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


if __name__ == "__main__":
    # Self-check: python -m app.config
    #
    # Pins the provider resolution table: explicit wins; ""/legacy "auto" mean
    # inference; exactly one credential family names its provider; both demand
    # a choice; neither is unconfigured. Runs through the real load_settings —
    # load_dotenv already folded the developer's .env into os.environ at import,
    # so every variable the table depends on is overwritten per case, and no
    # value from the environment is ever printed.
    A_KEY = "sk-ant-selfcheck-aaaaaaaaaaaa"  # bogus by construction
    O_KEY = "sk-oai-selfcheck-bbbbbbbbbbbb"
    GATEWAY = "https://gw.example/v1"

    def _case(env_provider: str, anthropic: str, base: str, key: str, stored=None) -> Settings:
        os.environ["LLM_PROVIDER"] = env_provider
        os.environ["ANTHROPIC_API_KEY"] = anthropic
        os.environ["OPENAI_BASE_URL"] = base
        os.environ["OPENAI_API_KEY"] = key
        os.environ["ANTHROPIC_MODEL"] = "claude-opus-5"
        os.environ["OPENAI_MODEL"] = "gpt-4o"
        return load_settings(stored)

    # (env LLM_PROVIDER, anthropic key?, gateway base?, gateway key?, stored)
    #   -> (provider, pinned, configured, needs_choice, model)
    TABLE = [
        # explicit always wins, even against the other family's credentials
        ("explicit claude", ("claude", A_KEY, GATEWAY, O_KEY, None), (CLAUDE, True, True, False, "claude-opus-5")),
        ("explicit openai", ("openai", A_KEY, GATEWAY, O_KEY, None), (OPENAI, True, True, False, "gpt-4o")),
        # an explicit pin whose key is missing is unconfigured, never re-inferred
        ("explicit claude, no key", ("claude", "", GATEWAY, O_KEY, None), (CLAUDE, True, False, False, "claude-opus-5")),
        # one family present: inference names it — legacy "auto" and "" identical
        ("auto + anthropic key", ("auto", A_KEY, "", "", None), (CLAUDE, False, True, False, "claude-opus-5")),
        ("unset + anthropic key", ("", A_KEY, "", "", None), (CLAUDE, False, True, False, "claude-opus-5")),
        ("auto + gateway pair", ("auto", "", GATEWAY, O_KEY, None), (OPENAI, False, True, False, "gpt-4o")),
        # half a gateway pair is no family
        ("unset + gateway base only", ("", "", GATEWAY, "", None), ("", False, False, False, "")),
        ("unset + key & half pair", ("", A_KEY, GATEWAY, "", None), (CLAUDE, False, True, False, "claude-opus-5")),
        # both families with no explicit choice: nobody may pick
        ("auto + both families", ("auto", A_KEY, GATEWAY, O_KEY, None), ("", False, False, True, "")),
        # neither: plain unconfigured, and still no vendor or model named
        ("unset + nothing", ("", "", "", "", None), ("", False, False, False, "")),
        # the stored (UI) layer beats .env, including a legacy stored "auto"
        ("stored openai over env claude", ("claude", A_KEY, GATEWAY, O_KEY, {"provider": "openai"}), (OPENAI, True, True, False, "gpt-4o")),
        ("stored legacy auto, both", ("", A_KEY, GATEWAY, O_KEY, {"provider": "auto"}), ("", False, False, True, "")),
    ]

    failures = []
    for name, args, want in TABLE:
        s = _case(*args)
        got = (s.provider, s.provider_pinned, s.configured, s.needs_choice, s.model)
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'} {name:<30} -> provider={s.provider or '(none)':<8} "
              f"pinned={s.provider_pinned!s:<5} configured={s.configured!s:<5} "
              f"needs_choice={s.needs_choice!s:<5} model={s.model or '(none)'}")
        if not ok:
            failures.append(f"{name}: {got} != {want}")

    # The inference helper itself, since overrides.py re-runs it per request.
    assert infer_provider(A_KEY, "", "") == CLAUDE
    assert infer_provider("", GATEWAY, O_KEY) == OPENAI
    assert infer_provider(A_KEY, GATEWAY, O_KEY) == ""
    assert infer_provider("", "", "") == ""
    assert infer_provider("", GATEWAY, "") == ""  # half a pair decides nothing
    assert infer_provider(A_KEY, "", O_KEY) == CLAUDE  # keyless gateway is no family

    if failures:
        raise SystemExit("resolution table failed:\n  " + "\n  ".join(failures))
    print("self-check ok — explicit wins, one family infers, both ask, none stays empty")
