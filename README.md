# Reverse Image Location · 照片定位

English | [简体中文](README.zh-CN.md)

Upload a photo and a vision model infers where on Earth it was taken from the **picture alone** (EXIF is stripped before anything reaches the model), returning coordinates, a confidence radius, and a full "observation → implication" evidence chain.

## Quick start

```bash
git clone https://github.com/Beluga-T/photo-locator.git
cd photo-locator
python run.py        # usually python3 run.py on macOS / Linux; py -3 run.py also works on Windows
```

Your browser opens <http://127.0.0.1:8000/> by itself. `run.py` uses only the standard library; on first run it builds `.venv`, installs the 7 dependencies from `requirements.txt`, and starts the server with the right flags. Every later run re-checks that the environment is still intact — that check measures at 0.029 seconds and never re-runs pip. It needs **Python 3.11 or newer** (`app/store.py` uses `datetime.UTC`, which is new in 3.11) and tells you plainly if yours is too old. Port taken? `python run.py --port 8010`. Don't want the browser opened? `--no-browser`.

You can also download a Release archive and unpack it — then it's the same `python run.py`. Unpack the **whole** archive; cherry-picking a few files makes it tell you what's missing.

### Prerequisites

All you need is Python 3.11+; everything else is installed into a project-local `.venv` automatically.

- **Windows** — `winget install Python.Python.3.12`, or the installer from [python.org](https://www.python.org/downloads/). Beware: on a fresh Windows, typing a bare `python` may open the **Microsoft Store** instead of running anything (it's a shopping alias, not an interpreter) — use `py -3 run.py`, which finds the real installation.
- **macOS** — `brew install python`, or the installer from python.org. The interpreter is then `python3`.
- **Debian / Ubuntu** — `sudo apt install python3 python3-venv`. On Debian-family systems `venv` is a **separate package**, and `run.py`'s virtual-environment creation fails without it.
- **Fedora** — `sudo dnf install python3`.

### Where the API key comes from, and what a run costs

**You use your own API key, pasted into the web page — no `.env` needed.** Gear icon at the top right → "Model" panel → paste your Anthropic API key → "Save & apply". It is stored **server-side** in `data/config.json` (gitignored) and survives browser switches and restarts.

An Anthropic key comes from [console.anthropic.com](https://console.anthropic.com/) → API Keys. The account must have a **positive credit balance** — a key from an unfunded account authenticates fine and then fails at request time with a billing error.

**What one location run costs**: the default is Claude Opus 5, list-priced at $5 / million input tokens and $25 / million output tokens. A photo scaled down to 2000 px is about 4,000 input tokens; with the system prompt and schema the input totals about 8,000 tokens (≈ $0.04). The output is the thinking plus that JSON, usually a few thousand tokens. **It works out to roughly $0.1–0.2 per run**, and `MAX_TOKENS = 16000` is a hard ceiling, so even an absurdly long output caps at $0.40. If that's too slow or too expensive, first turn the **thinking effort** in the settings card from `medium` down to `low` — the single most direct knob in this app (see [Configuration](#configuration)).

### Troubleshooting

- **Port 8000 already in use** → `python run.py --port 8010`.
- **pip is crawling** → point it at a nearby mirror; pip inherits the environment:

  ```bash
  PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple python run.py   # macOS / Linux
  ```

  ```powershell
  $env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"; py -3 run.py   # Windows PowerShell
  ```

- **Python too old** → `run.py` exits before touching anything and prints `This project needs Python 3.11 or newer. You started it with Python 3.x (...)`, followed by per-OS install commands. Install a newer Python and start the script **with that interpreter** — the venv is built from whichever interpreter runs `run.py`.

> ### ⚠️ It should only ever run on 127.0.0.1
>
> **None of the endpoints have any authentication** — no login, no token, no origin check. Anyone who can reach this port can run analyses on your key (spending your money), browse every photo you've analyzed and where each was taken, use `PUT /api/settings` to rewrite your saved configuration (including pointing the gateway address at their own machine), or wipe your entire history with one request.
>
> The default bind is `127.0.0.1` — **keep it that way**. If you really type `python run.py --host 0.0.0.0`, it prints this same warning, in full, to the terminal before the server starts. That is not politeness — exposing it requires a reverse proxy in front that does its own authentication. `compose.yaml` likewise publishes the port to `127.0.0.1` only. Details in [Security boundary](#security-boundary).

## What it does

The backend first uses Pillow to decode, re-orient, scale and re-encode the upload as JPEG — a step that incidentally **strips all EXIF**, so only pixels reach the vision model. The model plays an OSINT imagery geolocation analyst, converging from large clues to small — terrain and vegetation, architectural styles, road markings and driving side, signage text and domain suffixes, licence-plate proportions, utility-pole crossarms, shadow direction — and returns a verdict at **whatever level the evidence supports** (country / first-level region / city / neighborhood), center coordinates with a confidence radius, a complete chain of 4–8 "observation → implication" evidence items, 2–3 alternative locations, and a 0–100 confidence score. If the photo carried GPS, those coordinates are shown only to you and never reach the model — so what's on screen is genuine visual inference, not metadata reading.

## Interface language (中 / EN)

The UI is bilingual, Chinese and English:

- **The toggle** sits in the header next to the theme toggle. It shows **"EN"** while the page is in Chinese and **"中"** while it's in English — it names what you switch **to**. Switching is instant, no reload.
- **The choice persists** in the browser's `localStorage` (key `ril-lang`). First visit defaults by browser language: `navigator.language` starting with `zh` → Chinese, anything else → English.
- **Analysis results come back in the interface language.** The frontend sends its current language as the `lang` form field on the locate request (see [`POST /api/locate`](#post-apilocate)); the backend threads it into the prompt, so the prose fields — `summary`, evidence `observation` / `implication`, alternatives' `reason`, `notes` — arrive in that language. `name_zh` / `name_en` keep their fixed semantics in both languages; in English mode the headline prefers `name_en` when it is non-empty.
- **Server error messages are Chinese on the wire** (`{code, message}`). In English mode the frontend shows its own translation keyed on `code` when it has one, and the server's message otherwise — see [Error codes](#error-codes).

## How it works

1. **Upload**: the frontend POSTs the file as multipart field `image` to `/api/locate/stream`, along with its interface language in the optional `lang` field; anything over `MAX_UPLOAD_MB` is rejected outright. To get the complete result in one shot (scripts, curl), use `/api/locate` with the same parameters.
2. **Decode and normalize**: `app/imaging.py` opens the image with Pillow, validates the format (JPEG / PNG / WEBP / GIF / BMP / TIFF), corrects orientation via `ImageOps.exif_transpose`, scales proportionally with LANCZOS when the longest edge exceeds `MAX_IMAGE_EDGE`, then encodes everything to a quality-88 JPEG and base64.
3. **EXIF is read, never forwarded**: decoding parses GPSInfo out of the EXIF, converts degrees-minutes-seconds to decimal latitude/longitude, and returns it alongside the result as `meta.exifGps` **for you to see**. The re-encoded JPEG carries no metadata; the model receives pixels only. **The reported location is therefore pure visual inference.**
4. **Model inference**: `app/providers.py` constrains the output with `RESULT_SCHEMA` from `app/prompt.py`. Claude goes through the official SDK's `output_config.format = json_schema`; OpenAI-compatible gateways use `response_format.json_schema`, degrading automatically to `json_object` where unsupported, and failing that, writing the schema straight into the prompt.
5. **Report while writing**: the model's output is streamed, and `app/streaming.py` watches the unfinished stream with an incremental JSON scanner that extracts each top-level field the moment it closes — and for the **`evidence` / `alternatives` arrays, reports every element as it completes**. `RESULT_SCHEMA`'s field order is deliberate: `precision` comes first (it is the ceiling on "how deep the model is willing to commit" — knowing it first keeps the frontend from painting a street name it would immediately retract), then `country` → `region` → `city` → `locality` → `coordinates` → `confidence` → `summary`, with the bulky evidence chain last. A measured 24-second run (opus-5 / effort=medium): place names on screen at 3.7 s, coordinates at 5.9 s with map tiles starting to load, summary at 8.0 s, six evidence items from 9.4 s at one every 1.5–2 s, alternatives from 18.8 s — **across the whole wait the screen is never still for more than 2.5 s**.
6. **Backend normalization**: `providers.normalize` reduces the model's JSON to the one shape the frontend understands — latitude/longitude clamped to legal ranges, **precision reconciled** with radius floors applied per final precision (locality 0.5 / city 5 / region 50 / country 200 km, see the next section), confidence clamped to 0–100, `confidence_band` recomputed at the 70 / 40 thresholds when missing or invalid, evidence `weight` demoted to `medium` when invalid, alternatives sorted by `likelihood` descending.
7. **Frontend rendering**: `web/app.js` first paints a provisional verdict card marked "converging" from the fields as they stream in, re-arranging as they sharpen; when the complete result lands it replaces the whole block with the verdict headline, confidence gauge, evidence chain and alternatives list, and hangs a map underneath — an interactive Mapbox map with an uncertainty-radius circle if `MAPBOX_TOKEN` is configured, otherwise the built-in schematic globe. The plotting side supports full-page drag-and-drop, `Ctrl+V` paste, cancellable requests, and the `Enter` / `R` / `T` / `Esc` shortcuts. Photos analyzed this session stay in a thumbnail rail for review; results can be copied as a one-click conclusion or downloaded as JSON, with a bottom-right toast either way.
8. **Persistence**: `app/store.py` writes the JPEG the model saw into `data/shots/` and the entire response body into `data/history.json`, keeping the 20 most recent. Configuration saved in the UI lives in `config.json` in the same directory. See [What the server stores](#what-the-server-stores-data).

## Precision discipline

This is the most important behavior in the project right now, pinned down by `app/prompt.py` and `app/providers.py` working front and back:

- **Answer only at the level the evidence supports.** The system prompt makes the model converge downward from country, asking at each step "is there something concrete in the frame that supports this level"; when there isn't, it must fill `name_zh` with 「未确定」 (undetermined), leave `name_en` empty, and is **not allowed to write a "most likely" guess**. Better to give only a country than to invent a city.
- **The one floor is country.** Answering "cannot determine" or "insufficient information" outright is not allowed; even when unsure of the country it still names the most likely one, pushes `confidence` below 30, and puts the other candidate countries in `alternatives`. So this app always gives you an answer — it just says plainly which level it actually reached.
- **The model self-reports the level it reached.** `RESULT_SCHEMA`'s `precision` field takes one of `country` / `region` / `city` / `locality`, and a level filled with 「未确定」 may not appear there.
- **The backend doesn't trust the self-report — it reconciles on the spot.** `providers._resolve_precision` puts the declared `precision` next to the deepest level the model actually named and **publishes the coarser of the two** (when the declaration is missing or not a legal value, the actual filling wins outright). `normalize` then blanks every level finer than that to 「未确定」 + `known: false`, and `locality` to the empty string. So an answer that says "country only" out loud while quietly filling in a city never gets that city to the frontend; conversely, declaring `city` while leaving the city blank gets demoted to `region` or `country`. On any mismatch the backend logs `precision reconciled: model said ... publishing ...`.
- **Radius floors come last.** A coarse verdict may not wear a fine radius: `RADIUS_FLOOR` sets the minimum credible radius per reconciled precision, and a smaller model-reported radius is raised to it.

| `precision` | Level | Radius floor |
| --- | --- | --- |
| `country` | Country | 200 km |
| `region` | First-level division (state / province / region) | 50 km |
| `city` | City | 5 km |
| `locality` | Neighborhood / road / landmark | 0.5 km |

The prompt separately asks the model to self-report a `radius_km` commensurate with the precision (locality 1–5, city 10–50, region 100–400, country several hundred to two thousand km); the table above is only the backend's hard floor. The frontend picks the headline level from the final precision and, when it only reaches country or first-level region, says so: "the evidence only supports …".

## Three ways to run it

The `python run.py` from [Quick start](#quick-start) is the first one below. All three start the same app; pick one.

### `python run.py` (recommended)

```bash
python run.py                     # build .venv, install deps, start server, open browser
python run.py --port 8010         # 8000 is taken
python run.py --no-browser        # don't open a browser
python run.py --reload            # restart on changes under app/ (development)
python run.py --recreate-venv     # .venv is broken; delete and rebuild
python run.py --help              # all flags
```

Everything it does is idempotent: `.venv` isn't rebuilt if present, and pip doesn't run if the dependencies haven't changed (it compares a sha256 of `requirements.txt` plus the interpreter version, then confirms with `importlib.util.find_spec` that the 7 packages actually import). When it fails, it prints prose rather than a traceback — port in use, missing interpreter inside `.venv`, pip unable to reach PyPI, Windows' 260-character path limit (`anthropic` has module names over 100 characters; clone into a deep directory and pip throws an `[Errno 2]` that looks like a bug in this project) — each with its own explanation and fix.

### Manual venv

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --no-proxy-headers --reload
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --no-proxy-headers --reload
```

**`--no-proxy-headers` is not optional.** uvicorn ships with `--proxy-headers` on by default, rewriting the client address from `X-Forwarded-For` before the app ever sees the request — so anyone can mint themselves a fresh rate-limit allowance with each forged XFF value, and that allowance protects your money. Measured demonstration in [Security boundary](#security-boundary). `run.py` and the `Dockerfile` both hard-code this flag; only a hand-typed command line needs to remember it.

The key still goes into the web page; `.env` is optional — if you want one, `cp .env.example .env` (changes to `.env` need a process restart; changes made in the web UI don't). The server starts fine with no key configured: the startup log prints a warning, the status dot at the top right turns red, and "Locate" returns `not_configured`.

### Docker

```bash
docker compose up --build
```

Same <http://127.0.0.1:8000>, and the key is still entered in the page — it is written into the named volume below and outlives container rebuilds. Prefer `.env`? Also fine (`cp .env.example .env`, then `docker compose up -d --force-recreate` — no image rebuild needed).

`compose.yaml` freezes this project's security posture into container properties rather than README promises:

- **The port is published to `127.0.0.1` only.** The most important line in the file. Writing `"8000:8000"` binds every interface — this app has no authentication whatsoever, and `X-RIL-OpenAI-Base` makes it issue server-side requests to caller-chosen addresses; see [Security boundary](#security-boundary).
- **Read-only root filesystem** (`read_only: true`) with a small tmpfs on `/tmp`. What this now means: the app has **exactly one** writable place, the volume below; code, venv and `/etc` are immutable at runtime.
- **One writable named volume**: `locator-data` mounted at `/data`, with `RIL_DATA_DIR=/data` in the `Dockerfile`, so `config.json`, `history.json` and `shots/` all land on the volume. The image pre-creates `/data` and `chown`s it to uid 10001 — under a read-only root, skipping that step means the first write fails.
- `cap_drop: ALL` + `no-new-privileges`, running as non-root uid 10001 inside the image.

Inside the container uvicorn binds `0.0.0.0`, which is **required** — otherwise nothing outside the container can connect; "loopback only" is enforced by the port publishing above, not by the bind address. `--no-proxy-headers` is hard-coded in the `CMD`; remove it only when you put a reverse proxy you control in front, and put that proxy's address into `TRUSTED_PROXIES` at the same time.

**The named volume `locator-data` survives `docker compose down` and image rebuilds** — which is exactly why it exists: a release build has no `.env` to edit, so configuration has to be remembered by the app itself. The flip side: **that volume holds a plaintext API key and other people's photos**. Treat it like `.env`: don't casually `docker cp` it out, don't ship it along with the image, and know that `docker compose down -v` is what actually deletes it, photos included. To see the files directly on the host, swap `locator-data:/data` for `./data:/data` (the `compose.yaml` comments already say so) — at the cost of them living in your project directory from then on. `./data` is already in both `.gitignore` and `.dockerignore`; don't move it out.

`.dockerignore` excludes `.env` and `data/`, so neither keys nor photos get baked into image layers and build artifacts are safe to pass around.

## Configuration

**Four layers, highest precedence first:**

1. **`X-RIL-*` request headers** — affect only the one request that carries them, never persisted (`app/overrides.py`).
2. **`data/config.json`** — what the UI saved, on the machine running the service (`app/store.py`, below).
3. **`.env`** — loaded at startup by `app/config.py` via `python-dotenv`.
4. **Hard-coded defaults in `app/config.py`**.

Layer 2 can only override the eight fields in `app/store.py:CONFIG_FIELDS`: `provider`, `anthropic_api_key`, `anthropic_model`, `anthropic_effort`, `openai_base_url`, `openai_api_key`, `openai_model`, `mapbox_token`. Every other variable in the table below (upload cap, edge length, rate limit, timeouts, `TRUSTED_PROXIES`, …) **answers to `.env` only** — neither the UI nor headers can reach them.

`load_settings(stored)` merges **field by field**, with just three rules:

- **Empty doesn't count.** Stored values are `strip()`ped first; an empty or whitespace-only string counts as never-filled and falls through to `.env`, then to the default (`pick()` is just `saved.get(field) or _text(env, default)`). So "clear this field and save" means back to `.env`, not "set it to empty".
- **`anthropic_effort` must also be legal.** A stored value outside `low` / `medium` / `high` / `xhigh` / `max` is ignored wholesale, falling back to `ANTHROPIC_EFFORT`, then to `medium`.
- **`provider` is recomputed, and stored gateway credentials take part.** `provider` itself goes through the same four layers; if the merge yields `claude` / `openai` it is pinned (`provider_pinned = True`), otherwise the auto rule re-derives it — the merged `openai_base_url` and `openai_api_key` must **both be non-empty** to pick `openai`. Whether those two came from `data/config.json` or `.env` is fully equivalent: saving a set of gateway credentials in the UI pushes auto to `openai` exactly like writing them into `.env`.

**Changing `.env` requires a process restart** (`load_dotenv()` runs once at import); changing `data/config.json` doesn't — after `PUT` / `DELETE /api/settings`, `app/main.py:_reload_settings()` rebuilds `settings` on the spot and the next request sees the new values.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_PROVIDER` | `auto` | `claude` / `openai` / `auto`. Lowercased; anything that isn't the first two is treated by the auto rule |
| `ANTHROPIC_API_KEY` | empty | Official Anthropic API key. On the claude path, "configured" means this is non-empty |
| `ANTHROPIC_MODEL` | `claude-opus-5` | Claude model id |
| `ANTHROPIC_EFFORT` | `medium` | Thinking effort, `low` / `medium` / `high` / `xhigh` / `max`. **The most direct speed knob.** Anthropic's own default is `high`; this app deliberately runs one notch lower: a single visual inference isn't the long-horizon agentic work `high` targets, and Opus 5 stays strong at lower effort. Illegal values fall back silently, never failing startup. Claude only — the OpenAI-compatible path has no equivalent parameter and ignores it. Overridable in the UI, below |
| `OPENAI_BASE_URL` | empty | OpenAI-compatible gateway address, **written up to and including `/v1`**, without `/chat/completions`. Trailing `/` is stripped; the code appends `/chat/completions` |
| `OPENAI_API_KEY` | empty | Sent to the gateway as `Bearer` |
| `OPENAI_MODEL` | `gpt-4o` | Model name on the gateway side (Qwen-VL, GPT-4o, relay models — anything) |
| `MAPBOX_TOKEN` | empty | Mapbox token for the result-page map; the page's **default** (overridable in the UI, below). Left empty with nothing set in the browser either, the frontend falls back to the built-in schematic globe and the page makes zero external requests. **It is sent to the browser in plaintext via `/api/config`**, so it must be a public `pk.` token, URL-restricted by domain in the Mapbox dashboard; never a secret `sk.` token |
| `MAX_UPLOAD_MB` | `12` | Raw byte cap per image; beyond it returns `too_large` |
| `MAX_IMAGE_EDGE` | `2000` | Longest-edge pixel cap before the model |
| `REQUESTS_PER_HOUR` | `40` | Per-IP hourly request cap (`/api/locate`, `/api/locate/stream` and `/api/verify` share one bucket); **0 or negative disables rate limiting entirely** |
| `TRUSTED_PROXIES` | empty | Comma-separated address list; only for requests from these addresses is the first hop of `X-Forwarded-For` taken as the client IP for rate limiting. **Empty by default = trust nobody's**, everything counts by socket address. Note this alone isn't enough: uvicorn's own `--proxy-headers` defaults to on and rewrites the address before the app sees it — see [Security boundary](#security-boundary) |
| `REQUEST_TIMEOUT_SECONDS` | `240` | Model-call timeout in seconds, applied to both the Anthropic SDK and httpx |
| `REFUSAL_FALLBACK` | `true` | Claude only: request first with the `server-side-fallback-2026-07-01` beta header so the server automatically reruns on a fallback model when a safety policy triggers |

Numeric variables that fail to parse fall back silently to their defaults; booleans accept `1` / `true` / `yes` / `on` (case-insensitive), anything else is false.

**The real `LLM_PROVIDER=auto` rule**: `OPENAI_BASE_URL` and `OPENAI_API_KEY` must **both be non-empty** to pick `openai`; otherwise it's `claude`. Filling in only the base_url without the key does not switch — this differs slightly from the wording of the comment in `.env.example`; the code is authoritative.

### The map token (`MAPBOX_TOKEN`): optional

**It works without one.** With no token, the result page draws the built-in schematic globe (`web/globe.js`, a locally rendered orthographic graticule SVG) with the verdict point at its center; coordinates and radius display as usual and the page makes zero external requests. Everything you came for — country, city, coordinates, evidence chain — is all there; the base map just has no streets.

With a token, the result page becomes an interactive Mapbox map with an uncertainty-radius circle, draggable and zoomable. Getting one: register a free account at [mapbox.com](https://www.mapbox.com/); the Account page gives you a **public token** starting with `pk.` — copy it. The free tier is far more than enough for looking at your own photos.

**Where it goes**: gear icon at the top right → "Map" panel → paste → "Save & apply". Or put `MAPBOX_TOKEN=` in `.env` (restart required after changing it).

**Only a public `pk.` token is acceptable.** It must be sent to the browser in plaintext to draw anything (that is how Mapbox is designed), so do add a URL restriction to it in the Mapbox dashboard while you're there. A secret `sk.` token is rejected by the frontend on the spot, and the backend's `/api/config` withholds it too, logging a warning — a token like that reaching a browser is already leaked.

**The price is that coordinates go to Mapbox** (photos do not): to render tiles the browser must request them carrying the model's inferred latitude/longitude. For fully offline, leave this empty.

#### Changing the map token in the UI

The Mapbox token is only ever used by the browser, but it's stored in the same place as the model keys, so there's no need to edit `.env` and restart the backend to change it. Open the settings button at the top right, switch to the "Map" panel, paste and save — effective immediately:

- Precedence is **`data/config.json` > `MAPBOX_TOKEN` in `.env` > neither, use the built-in schematic globe**.
- Saving goes through `PUT /api/settings`' `mapbox_token` field and lands on the server's disk — **it survives browser switches and restarts**, changing the value `/api/config` sends to **every** browser.
- It is **not masked** in `GET /api/settings`; the two API keys are. A public `pk.` token has to be sent to browsers in plaintext anyway; masking would only stop you from seeing what you typed.
- Clearing the input and saving deletes it, falling back to the `.env` value.
- If a result is already on screen when you save, the map redraws in place — no need to re-analyze the photo.
- A secret `sk.` token is rejected by the frontend outright — once a token like that reaches a browser, it's leaked.

### Changing model credentials in the UI

The gear at the top right opens the settings card, with "Model", "Map" and "Data" panels. The model panel changes which provider, whose key, and the thinking effort; "Save & apply" takes effect immediately — no `.env`, no backend restart.

Fields: a `PROVIDER` dropdown (`auto` / `claude` / `openai`), Anthropic's API key / model name / **thinking effort**, and the OpenAI-compatible gateway's base URL / API key / model name.

Neither dropdown offers a **"follow the server" option**. A real deployment has no `.env`; presenting a nonexistent file as a choice only misleads. Inputs can still be left empty — empty means inherit the next layer down, and if there's nothing there either, then there's nothing.

- **Stored on the server's disk**: saving is `PUT /api/settings`; the backend writes the fields it recognizes into `data/config.json` (`app/store.py:write_config`). It survives browser switches and restarts — a release build has no `.env` to edit, and this layer exists for exactly that.
- **Merge, not wholesale replace**: fields absent from the request body keep their values, so sending only what the user touched is enough. An empty (or whitespace-only) string for a field is an **explicit request to delete it**, falling back to `.env`; omitting the field entirely means "no opinion".
- **Reads come back masked**: `GET /api/settings` passes both API keys through `mask()`, and `openai_base_url` keeps only scheme + host. The response after a save is the same masked view. The settings card can therefore never display a key you typed — deliberately; see [Security boundary](#security-boundary).
- **Changing the gateway address requires that gateway's key in the same request**, else 400 `bad_override`.
- **"Clear saved configuration" is `DELETE /api/settings`**: deletes the whole `data/config.json`, back to `.env` and defaults.
- **This port has no authentication**: anyone who can reach it can change these settings. Hence loopback only.

**The frontend no longer stores any credential in `localStorage`.** Earlier versions kept seven fields in the browser and sent them as `X-RIL-*` headers on every request; that path is gone: `web/settings.js` now only validates the user's draft and derives "what the next request will use" from `/api/config` — not one line of storage code. The locate requests `web/app.js` sends carry **no `X-RIL-*` headers**; the server uses its own saved configuration. The `ril-model-config` an old version left in your browser is no longer read by any code.

**Calling the API directly? Use the `X-RIL-*` headers.** They remain valid as the **per-request** override channel for direct callers (curl, scripts): the backend uses them within that one request's lifetime only — **never written to `data/config.json`, never persisted, never logged** (logs only ever see the `mask()` output).

| Field | Header | `Settings` field overridden |
| --- | --- | --- |
| PROVIDER | `X-RIL-Provider` | `provider` |
| ANTHROPIC · API KEY | `X-RIL-Anthropic-Key` | `anthropic_api_key` |
| ANTHROPIC · MODEL | `X-RIL-Anthropic-Model` | `anthropic_model` |
| ANTHROPIC · EFFORT | `X-RIL-Anthropic-Effort` | `anthropic_effort` |
| Gateway · BASE URL | `X-RIL-OpenAI-Base` | `openai_base_url` |
| Gateway · API KEY | `X-RIL-OpenAI-Key` | `openai_api_key` |
| Gateway · MODEL | `X-RIL-OpenAI-Model` | `openai_model` |

**Headers also apply field by field**: a sent header is used; an unsent field falls to `data/config.json`, then `.env`, then the default. **Unsent / empty means "no opinion", not "clear"** — it never erases a saved value (to clear, send an empty string via `PUT /api/settings`). A single field over 500 characters (`MAX_VALUE_LEN`), or containing non-ASCII or unprintable characters, is rejected (`web/settings.js` intercepts once in the frontend, `overrides._clean` again in the backend).

**Too slow? Adjust the thinking effort first.** It controls how long Claude thinks before answering and is the single most direct speed knob in this app — far more effective than switching models:

| Level | When |
| --- | --- |
| `low` | Fastest. Single-photo inference usually still holds up |
| `medium` | Try this first for speed: clearly faster than the default with little quality loss |
| `high` | Anthropic's default, and the slowest of the common settings |
| `xhigh` | Finer reasoning, slower and pricier; limited payoff for this kind of one-shot visual judgment |
| `max` | Slowest; only when correctness trumps cost — prone to overthinking simple images |

Incidentally, lowering effort also relieves pressure on `MAX_TOKENS` (16000) — Claude Opus 5 has thinking on by default and `max_tokens` caps **thinking plus prose combined**; on a task that both reads an image and produces long JSON, `high` runs close to the cap. Hitting it shows up as `truncated`.

After the seven fields merge, `app/overrides.py:apply_overrides` decides which path this request takes:

| Case | Outcome |
| --- | --- |
| `X-RIL-Provider` is `claude` or `openai` | The user just chose; obey |
| `X-RIL-Provider` is `auto` | The user asked for re-derivation |
| Header absent, and the server-side `provider` explicitly says `claude` / `openai` (`data/config.json` or `LLM_PROVIDER`) | Operator-pinned; obey |
| Header absent, and that server layer is `auto` | Nobody ever chose; re-derive |

"Re-derive" uses the same rule as startup: the merged base URL and key must **both be non-empty** to go `openai`, else `claude`. That last row must recompute — at startup `load_settings` already collapsed `auto` into a concrete provider, and without recomputing, a request that filled in a gateway but sent no `X-RIL-Provider` would barrel on toward Claude. The sole reason `Settings.provider_pinned` exists is to tell these two kinds of "the server decides" apart. The UI dropdown no longer produces the header-absent case, but direct calls via curl still do, so the rule stays.

**The "Test connection" button** POSTs the current form's seven headers to `/api/verify` for a **free** reachability probe: Claude calls `models.list` (`GET /v1/models`, unbilled), gateways get `GET {base}/models`. No tokens spent; click freely. It tests the **current form**, not the saved configuration — when the form differs from what's stored and the probe succeeds, the message appends a reminder that you still need to hit "Save & apply" or analysis will keep using the old configuration.

**These are out of reach of both headers and `/api/settings`** (operator gates, `.env` only, restart to change): `MAX_UPLOAD_MB`, `MAX_IMAGE_EDGE`, `REQUESTS_PER_HOUR`, `REQUEST_TIMEOUT_SECONDS`, `TRUSTED_PROXIES`, `REFUSAL_FALLBACK`. They aren't in the `CONFIG_FIELDS` whitelist, so `PUT /api/settings` can't smuggle them in. `app/main.py` deliberately reads the module-level `settings`, not this request's `effective`, when checking size and edge limits. (`MAPBOX_TOKEN` is the exception: it has no `X-RIL-*` header, but it is in `CONFIG_FIELDS` and `/api/settings` can change it.)

### What the server stores: `data/`

```
data/
├─ config.json      configuration saved in the UI — plaintext API keys, 0600 from creation
├─ history.json     one entry per analysis: id, created_at, media_type, size_bytes, plus that
│                   run's complete /api/locate response body (payload). No image bytes
└─ shots/<id>.jpg   the images themselves, one file each
```

- **Location** is set by `RIL_DATA_DIR`, defaulting to `data/` under the project root (`app/store.py:DEFAULT_DATA_DIR`, right next to `.env` — same machine, same trust boundary, same class of secret). The `Dockerfile` sets it to `/data` in containers. An unusable value (contains NUL, `~` won't expand) logs a line and falls back to the default directory rather than killing the process.
- **What's stored is the frame the model saw**: the JPEG after `imaging.prepare`'s scaling, re-encoding and full EXIF strip (`PreparedImage.data`). Neither the original nor its GPS ever touches disk.
- **Only the most recent `HISTORY_CAP = 20` are kept.** Writing the 21st deletes the oldest entry together with its image file; if the index is lost or corrupted, the next successful write also sweeps up every file in `shots/` the index doesn't know — otherwise those files would never be referenced and never deleted.
- **`data/` is in both `.gitignore` and `.dockerignore`** — never committed, never baked into image layers.
- **This directory holds an API key and users' photos.** It replaces `.env`; treat it to the same standard: don't copy it around, don't put it on a cloud-synced path, don't tar it into a backup and mail it off.

## API reference

### `GET /api/health`

```json
{ "status": "ok" }
```

### `GET /api/config`

The frontend calls this at startup to render the model status at the top right. What's sent is **the server's currently effective configuration** (`data/config.json` over `.env`), not the header layer. `configured` false means the active provider's credentials are incomplete; `mapboxToken` is the public token verbatim, and the frontend uses the schematic globe when it's an empty string.

```json
{
  "provider": "claude",
  "providerPinned": false,
  "model": "claude-opus-5",
  "effort": "medium",
  "configured": true,
  "maxUploadMb": 12,
  "hasAnthropicKey": true,
  "hasOpenaiBase": false,
  "hasOpenaiKey": false,
  "mapboxToken": "pk.eyJ1Ijoi…"
}
```

`providerPinned` distinguishes a `provider` explicitly written as `claude` / `openai` (true) from an `auto` that merely resolved to it (false) — `provider` in `data/config.json` and `LLM_PROVIDER` in `.env` are equivalent here. `effort` is the server's current default thinking effort. `hasAnthropicKey` / `hasOpenaiBase` / `hasOpenaiKey` are **existence booleans for those three server-side values; content is never sent**. These four fields exist for one reason: to let the browser recompute, field by field, which provider the next request will land on — otherwise the chip at the top right could point at one provider while requests go to another (which happens when `.env` fills in half a gateway, or the key belongs to the path that wasn't selected).

`mapboxToken` is the only credential sent in plaintext, and it must be a public token: **a secret `sk.` token is withheld by this endpoint** (empty string returned) with a warning in the startup log.

### `GET /api/settings`

Reads `data/config.json`. **Keys are always masked; this endpoint has no branch that returns plaintext.**

```json
{
  "config": {
    "provider": "openai",
    "openai_base_url": "https://gw.example.com",
    "openai_api_key": "sk-oai…b7f2",
    "openai_model": "qwen-vl-max",
    "mapbox_token": "pk.eyJ1Ijoi…"
  },
  "historyCount": 3
}
```

`config` is the output of `store.public_config()`, containing only fields that **actually have stored values**:

- `anthropic_api_key` / `openai_api_key` go through `overrides.mask`: first 6 + last 4 characters, anything ≤ 14 characters becomes `***` entirely.
- `openai_base_url` goes through `overrides.safe_url`, keeping **only scheme + host (+ port)** — path and userinfo dropped. Not fastidiousness: plenty of relays put credentials in the path (`https://relay.example/sk-abc…/v1`) or in userinfo (`https://user:key@host/v1`), and echoing the address verbatim from an **unauthenticated** endpoint is handing the key over. The cost is that the settings card can't display the tail of the address you entered.
- `mapbox_token` is **not masked**: it's the public `pk.` token that `/api/config` sends to browsers in plaintext anyway.
- `historyCount` is the number of entries from `store.list_shots()`.

The server's own request path reads `store.read_config()` (plaintext); that function **may not appear in any route**.

### `PUT /api/settings`

The request body is a JSON object with **merge-patch semantics**: write only the fields you mention.

```bash
curl -X PUT http://127.0.0.1:8000/api/settings \
  -H "Content-Type: application/json" \
  -d '{"provider":"claude","anthropic_api_key":"sk-ant-…"}'
```

- Only the eight `CONFIG_FIELDS` are stored; everything else is **silently ignored** (one debug log line only — key names are caller-controlled and stay out of normal logs). This is a whitelist, not a filter: this file later gets layered over the operator's `Settings`, so accepting arbitrary keys would mean rewriting `max_upload_bytes`, `trusted_proxies` and the other gates the UI can't reach.
- Values are `strip()`ped; **an empty string means delete this field**. Strings and numbers are accepted (JSON makes it easy to write `"0"` as `0`); `true` / `null` / arrays / objects are rejected rather than stringified into `"True"`. Over 500 characters is truncated; control characters reject the whole value — these strings later get spliced into HTTP headers or a base URL.
- **This path is one notch looser than `X-RIL-*`**: `store._coerce` blocks only control characters, not non-ASCII, so a direct `curl -X PUT` with a Chinese model name **stores it and returns 200**, failing only later at the upstream call; the same value in a header is rejected on the spot by `overrides._clean`. `web/settings.js` intercepts it before saving — for UI users that's the only thing standing in between.
- **Changing `openai_base_url` without `openai_api_key` in the same request returns 400 `bad_override`** (`app/main.py:write_settings`). Same rule as on the `X-RIL-*` path: given only a destination without a key, the server would send the **already-saved** key to a caller-chosen address. No trigger when the address equals what's stored.
- After writing it calls `_reload_settings()`; the next request uses the new configuration, no restart. Logs record only the **names of changed fields**, never values.

The response is the same masked view:

```json
{ "config": { "provider": "claude", "anthropic_api_key": "sk-ant…7g2k" } }
```

A body that isn't valid JSON, or isn't a JSON object, returns 400 `bad_json`. The response body comes from **re-reading the disk** (the route calls `public_config()` again), so if the write failed you see what's actually on disk rather than what you just sent — sparing the UI from reporting a key that never got saved.

### `DELETE /api/settings`

Deletes the whole `data/config.json`, along with any `.config.json.*.tmp` that `_write_atomic` may have left behind (those temp files also contain plaintext keys), then rebuilds `settings` — back to `.env` and defaults.

```json
{ "config": {} }
```

What's deleted is **this app's memory of the key**, not the bytes on the platter: freed blocks remain readable on most filesystems. If you suspect a leak, rotate the key upstream.

### `GET /api/history`

```json
{
  "shots": [
    {
      "id": "20260807T041233912345-9f3a1c04",
      "created_at": "2026-08-07T04:12:33Z",
      "media_type": "image/jpeg",
      "size_bytes": 486213,
      "payload": { "result": { }, "meta": { } }
    }
  ]
}
```

**Newest first**, at most 20 entries (`HISTORY_CAP`). `payload` is the complete response body of the original `/api/locate` run, so reviewing history never re-queries the model. **Image bytes are not here** — base64 in the index would inflate it by 4/3 and make every history listing a download of every photo; images go through the endpoint below.

`id` is a `%Y%m%dT%H%M%S%f` UTC timestamp plus a 4-byte random tail, so lexicographic order is chronological order. When `history.json` can't be read (missing, hand-corrupted, wrong encoding, over-nested) this returns `{"shots": []}` instead of erroring, and the next successful write repairs the file.

### `GET /api/history/{id}/image`

Returns the image bytes themselves. `Content-Type` is the `media_type` recorded in the index; with the index gone it's inferred from the extension; unrecognizable means `application/octet-stream` — **a caller-chosen type is never echoed as Content-Type**. Responses carry `Cache-Control: private, max-age=300`.

`id` must match `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`: **no dot means `..` cannot be spelled; no `/` `\` `:` means neither separators nor drive letters can**, and Windows device names (`NUL`, `CON`, `COM1`, …) are blocked separately. This layer is the gate that actually holds — percent-decoding happened before the framework handed us the path, so `%2e%2e%2f` arrives here as `../`. Before touching disk there's a further `resolve()` + `is_relative_to(shots/)` backstop against symlinks inside `shots/`. An illegal id and a missing photo both return 404 `not_found`, indistinguishably.

### `DELETE /api/history/{id}`

```json
{ "deleted": true }
```

`deleted` reports **what actually happened**: `true` only if the image file or the index entry (at least one) changed. Deleting twice is `false`, not an error. A failed index rewrite is also `false` — that record is still in the list, still occupying a `HISTORY_CAP` slot, and claiming success would stop the caller from ever retrying.

### `DELETE /api/history`

Clears everything: deletes each image file, sweeps whatever remains in `shots/` (subdirectories and temp files included), then writes the index as `[]`.

```json
{ "removed": 20 }
```

`removed` is **the number of index entries cleared**; a failed index write returns 0, because the list will reappear unchanged on the next refresh. As with `DELETE /api/settings`, this is "the app forgot", not "the disk was wiped".

**These three DELETEs, like `PUT /api/settings`, have no authentication whatsoever**: anyone who can reach the port can replace the operator's keys or wipe history and photos in one shot. See [Security boundary](#security-boundary).

### `POST /api/verify`

What the settings card's "Test connection" button uses. **No request body**; credentials travel entirely in the seven `X-RIL-*` headers above. With no headers at all, it probes the server's currently effective credentials (`data/config.json`, then `.env`). The probe itself is free: Claude calls `models.list`, gateways get `GET {base}/models` — no tokens consumed.

```bash
curl -X POST http://127.0.0.1:8000/api/verify \
  -H "X-RIL-OpenAI-Base: http://127.0.0.1:11434/v1" \
  -H "X-RIL-OpenAI-Key: sk-…"
```

Probe success or failure both return HTTP 200 with a fixed shape (`ok` is derived from `code == "ok"`, not carried independently, so `unconfirmed` can't be mistaken for success). `message` is Chinese on the wire — the English UI translates by `code`:

```json
{
  "ok": true,
  "provider": "claude",
  "model": "claude-opus-5",
  "code": "ok",
  "message": "密钥可用，将使用 claude-opus-5。",
  "detail": ""
}
```

All values of `code`:

| `code` | `ok` | Meaning |
| --- | --- | --- |
| `ok` | true | Key works |
| `not_configured` | false | That path's credentials are incomplete (Claude missing a key; gateway missing address or key) |
| `auth` | false | Key invalid or expired (Anthropic auth failure, or gateway 401 / 403) |
| `unconfirmed` | false | Gateway only: `/models` returned 404 / 405 — the address is reachable but the key can't be confirmed (many relays proxy only `/chat/completions`) |
| `rate_limited` | false | Upstream rate limit (Anthropic `RateLimitError`, or gateway 429) |
| `timeout` | false | No connection within 20 seconds |
| `network` | false | Upstream unreachable |
| `upstream` | false | Any other status code, malformed addresses, and every unanticipated exception |

`detail` is the upstream's own text, passed through `overrides.scrub` and truncated to 200 characters (`MAX_DETAIL`); empty when there's nothing presentable. The probe timeout is fixed at 20 seconds (`PROBE_TIMEOUT`), **independent of `REQUEST_TIMEOUT_SECONDS`** — the user is watching a spinner on a settings panel, not waiting on a visual inference. Illegal headers return 400 `bad_override`; **it shares the rate-limit bucket with `/api/locate`**, returning 429 `rate_limited` when exceeded.

### `POST /api/locate`

`multipart/form-data`, field name fixed as `image`. Credentials can be overridden per-field with the seven `X-RIL-*` headers above. Each success stores a photo and a history entry under `data/` (see [What the server stores](#what-the-server-stores-data)).

An optional `lang` form field ∈ {`zh`, `en`}, default `zh`, selects the language of the **prose** in the result — `summary`, evidence `observation` / `implication`, alternatives' `reason`, `notes`. The web UI sends its current interface language; `name_zh` / `name_en` keep their fixed semantics either way. (`evidence[].category` is a fixed Chinese enum from `app/prompt.py`'s `RESULT_SCHEMA` on the wire; the English UI renders its translation.)

```bash
curl -X POST http://127.0.0.1:8000/api/locate -F "image=@photo.jpg" -F "lang=en"
```

Success returns 200 with the shape `{ result, meta }`. The example below (a `lang=en` run) deliberately shows a verdict that **only reaches country level**, to demonstrate the precision discipline: `precision` is `country`, so `region` / `city` are 「未确定」 + `known: false` across the board, `locality` is an empty string, and the radius was raised above the country-level floor.

```json
{
  "result": {
    "country": { "name_zh": "葡萄牙", "name_en": "Portugal", "known": true },
    "region":  { "name_zh": "未确定", "name_en": "", "known": false },
    "city":    { "name_zh": "未确定", "name_en": "", "known": false },
    "locality": "",
    "precision": "country",
    "coordinates": { "lat": 39.6, "lon": -8.2, "radius_km": 260 },
    "confidence": 71,
    "confidence_band": "high",
    "summary": "Blue-and-white azulejo façades, black-and-white cobblestone pavement and Portuguese shop signage together pin this to Portugal; but the frame contains no place name, area code or landmark, so it cannot converge further to a city.",
    "evidence": [
      { "category": "建筑风格", "weight": "high",
        "observation": "Street façades are faced extensively in blue-and-white glazed tile, with small cast-iron balconies and red barrel-tile roofs.",
        "implication": "Azulejo facing is a Portuguese signature, distinct from the whitewashed render of southern Spain." },
      { "category": "基础设施", "weight": "high",
        "observation": "The sidewalk is small black and white stone setts laid in geometric patterns, with tall narrow curbstones.",
        "implication": "Calçada portuguesa paving, used throughout Portugal — it fixes the country but not the city." },
      { "category": "文字与标识", "weight": "medium",
        "observation": "A shop sign reads \"Pastelaria\", with no phone number, address or any place name on the board.",
        "implication": "The Portuguese spelling confirms the language area, but without an area code or toponym it cannot converge to a specific city." },
      { "category": "车辆与车牌", "weight": "medium",
        "observation": "At the frame's edge a car carries a white plate with a blue EU band on the left; the characters are illegible.",
        "implication": "The EU-format plate rules out Brazil and the other Portuguese-speaking countries, but the issuing district cannot be read." }
    ],
    "alternatives": [
      { "country": "Spain", "region": "", "city": "", "likelihood": 14,
        "reason": "A similar Iberian street-front shop style, but tiled façades and black-and-white sett paving are far rarer in Spain." },
      { "country": "Brazil", "region": "", "city": "", "likelihood": 6,
        "reason": "Portuguese signage and sett paving would fit equally, but the EU-format plate rules it out." }
    ],
    "notes": "Any road sign with a place name, or one shop sign with an address, would jump the precision straight from country to city."
  },
  "meta": {
    "elapsedMs": 11842,
    "provider": "claude",
    "model": "claude-opus-5",
    "analyzedSize": [2000, 1500],
    "sourceSize": [4032, 3024],
    "exifGps": { "lat": 38.712014, "lon": -9.129831 },
    "shotId": "20260807T041233912345-9f3a1c04"
  }
}
```

The `meta` fields: `elapsedMs` is the backend's model-call duration in milliseconds (upload excluded); `provider` / `model` are the path and model actually used this run; `analyzedSize` is the post-scaling `[width, height]` actually sent to the model; `sourceSize` is the original's `[width, height]`; `exifGps` is the real coordinates read from the original's EXIF — **`null` when there is no GPS** — provided solely so you can check the model against reality; `shotId` is this photo's id in the server-side history, usable with `GET /api/history/{id}/image` to fetch the image back, and **absent entirely when persistence failed** (the analysis still returns; it just wasn't stored).

Fields in `result` that may be empty: `coordinates` is `null` when latitude/longitude are unparsable; `locality` / `notes` are empty strings when there's nothing to say; when a place name is missing, or its level was blanked for being finer than `precision`, `name_zh` is 「未确定」, `name_en` is an empty string, and `known` is `false`. The `known` on each of `country` / `region` / `city` is the frontend's switch for "does this level count" — don't string-compare `name_zh` against 「未确定」.

On error the body is `{ "error": { "code": "...", "message": "..." } }`, where `message` is user-presentable Chinese; the English UI shows its own translation for known codes (see [Error codes](#error-codes)).

### `POST /api/locate/stream`

**Exactly the same job, parameters, rate limit and override headers** as `/api/locate` (including `lang`) — the only difference is reporting while computing. The web page uses this one; `curl` and scripts are better served by the one above.

The response is `text/event-stream` with three event types:

| event | data | Meaning |
| --- | --- | --- |
| `partial` | `{"field": "...", "value": ...}` | A top-level field the model just finished writing — its **unnormalized** words |
| `partial` | `{"field": "...", "index": N, "value": ...}` | The **N-th element** of an array field, just completed |
| `result` | `{ result, meta }` | The complete response body, identical to `/api/locate` — **this one is authoritative** |
| `error` | `{"code": "...", "message": "..."}` | Failure; no further events after it |

```
event: partial
data: {"field": "precision", "value": "city"}

event: partial
data: {"field": "country", "value": {"name_zh": "巴拉圭", "name_en": "Paraguay"}}

event: partial
data: {"field": "coordinates", "value": {"lat": -25.2937, "lon": -57.6089, "radius_km": 12}}

event: partial
data: {"field": "evidence", "index": 0, "value": {"category": "文字与标识", "...": "..."}}

event: result
data: {"result": {...}, "meta": {...}}
```

**The presence of `index` is the only distinction**: with it, this is element N of array `field` — the client renders it into row N, replacing whatever that row held; without it, it's the whole field.

What gets emitted as `partial` splits two ways:

- **Whole fields**: `precision`, `country`, `region`, `city`, `locality`, `coordinates`, `confidence`, `confidence_band`, `summary`.
- **Element by element**: `evidence`, `alternatives`. These two arrays are **never emitted whole** — the elements already carried the content across, and one whole `evidence` runs about 4 KB; sending it again would make the browser parse it just to throw it away.

`notes` is not emitted (a closing addendum, meaningless on its own). `data` is always `ensure_ascii`, with Chinese as `\uXXXX`, so no proxy can truncate UTF-8 mid-character.

**One exception: an array field arriving whole, without `index`, means "discard every row already painted for this field".** It only happens when the model writes `evidence` twice within one JSON (the later one counts; the earlier rows don't exist in the final result). Otherwise these two fields never arrive whole, so there's no ambiguity.

**Three things you must know:**

- **`partial` is the model talking; `result` is the verdict.** `partial` has not been through `normalize`: no precision reconciliation, no radius floors, no `known` flags. The model routinely writes out a street name while only declaring `precision: "city"` — the `locality` in `result` is empty. The client must let `result` unconditionally overwrite everything shown before it. **`precision` sits first in the schema for exactly this**: the frontend knows the ceiling up front and treats finer levels as absent, so the headline only ever gets more precise, never precise-then-retracted.
- **It saves the "writing" time, not the "thinking" time.** The model thinks before it writes, and not one character streams out during thinking. In the measured 24-second run above, the first 3.7 s were pure thought with nothing on screen but the scan animation and timer; the remaining 20 s had something moving throughout. The higher the effort, the larger the thinking share, and the less this feature buys.
- **The HTTP status is always 200.** Bad image format, rate limiting, illegal override headers — everything that is a 400/429 on `/api/locate` is an `error` event here, because the stream has already started. Clients watch events, not status codes.

`PartialJSON` in `app/streaming.py` is the stream's parser: it reports only what has **closed** — `{` `}` `,` and escapes inside strings don't count, numbers wait for a delimiter (`95` might be half of `951`), nested objects wait for their own closing brace, array elements wait for their own layer to close. Chunk boundaries can't affect the outcome — feeding it character by character and feeding it whole blocks produce identical report sequences, `index` values included; that property is guarded by 300 random splits among the 58 self-checks in `python -m app.streaming`. A parse failure doesn't take the stream down: that one item is dropped, later ones report as usual, and since **the index is an array position, not a counter**, the dropped item leaves a hole instead of shifting later rows forward. A final authoritative `json.loads` backstops the end.

## Error codes

Every error body is `{ "code": "...", "message": "..." }` with a Chinese, user-presentable `message`. In English mode the web UI shows its own translation when it knows the `code`, and the server's message otherwise; direct API callers should switch on `code`.

| code | HTTP | Trigger | What to do |
| --- | --- | --- | --- |
| `rate_limited` | 429 | Local rate limit: this IP exceeded `REQUESTS_PER_HOUR` combined requests to `/api/locate`, `/api/locate/stream` and `/api/verify` within an hour; on the streaming route it arrives as 200 + one `error` event | Wait a bit, or raise / disable `REQUESTS_PER_HOUR` |
| `bad_override` | 400 | An unusable `X-RIL-*` header: over 500 characters, non-ASCII or unprintable characters, provider not auto/claude/openai, base URL not a complete http(s) address, or **a base-URL override without that gateway's key**. `PUT /api/settings` also returns it when **changing the gateway address without that gateway's key** | Fix the field named in `message`; returned by all four of `/api/locate`, `/api/locate/stream`, `/api/verify`, `PUT /api/settings` |
| `bad_json` | 400 | `PUT /api/settings` body isn't valid JSON, or isn't a JSON object | Check the `Content-Type` and the body itself |
| `not_found` | 404 | `GET /api/history/{id}/image` id is illegal, or the photo is no longer in history (deleted, or evicted by `HISTORY_CAP`) | Re-fetch `GET /api/history` |
| `empty` | 400 | Empty upload body | Pick the file again |
| `too_large` | 413 | Raw bytes exceed `MAX_UPLOAD_MB` | Compress and retry, or raise the cap |
| `bad_image` | 400 | Pillow can't decode it, or the format isn't on the supported list | Convert to JPG / PNG / WebP |
| `not_configured` | 503 | The active provider's credentials are incomplete | Fill them in on the settings card (`PUT /api/settings`, effective immediately) or in `.env` plus a restart; the openai path needs base_url and key both |
| `auth` | 502 | Anthropic auth failed, or the gateway returned 401 | Check that `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` is valid and unexpired |
| `network` | 502 | Can't reach the Anthropic API or the gateway (includes timeouts on the Claude path) | Check network, proxy, whether `OPENAI_BASE_URL` is reachable |
| `upstream` | 502 | Upstream returned a non-200 not covered by the other cases | Read the upstream text in the backend log; usually a nonexistent model name |
| `rate_limited` | 503 | Upstream model rate limit (Anthropic RateLimitError or gateway 429) | Retry later; note it shares a name with the local limit but differs in HTTP status |
| `timeout` | 504 | Gateway didn't respond within `REQUEST_TIMEOUT_SECONDS` (OpenAI path only) | Retry, raise the timeout, or pick a faster model |
| `refused` | 422 | Claude declined on safety policy (`stop_reason == "refusal"`) | Try another photo; with `REFUSAL_FALLBACK` on, the server first automatically retries on a fallback model |
| `truncated` | 502 | Claude's output was cut off by `max_tokens` | Just retry |
| `billing` | 402 | Anthropic account balance insufficient | The key itself is fine — top up under Plans & Billing. **Never retried** — degradation can't fix a billing problem |
| `forbidden` | 403 | The key has no access to this model | Change keys, or set a model this key can access |
| `bad_request` | 502 | A 400 on the Claude path that is neither of the two permanent failures above and mentions no parameter that degradation could remove; or every degradation posture was refused | Read the raw error in the log; usually a mistyped model id, an image over a hard limit, or an outdated SDK |
| `bad_response` | 502 | No parsable JSON could be dug out of the response, or the gateway returned an unexpected structure | Retry; if it recurs, that model can't keep up with the JSON schema — pick another |
| `internal` | 500 | Unanticipated exception; the stack trace goes to the log only, never the browser | Check the backend log |

## Project structure

```
reverse-image-location/
├─ app/
│  ├─ __init__.py      version number
│  ├─ config.py        environment variables → frozen Settings dataclass, provider auto-selection rule
│  ├─ imaging.py       Pillow decoding, EXIF GPS reading, re-orientation, scaling, base64 JPEG
│  ├─ prompt.py        the analyst system prompt, evidence category enum, RESULT_SCHEMA
│  ├─ overrides.py     X-RIL-* headers → this request's Settings, provider re-resolution, mask / scrub / safe_url
│  ├─ providers.py     Claude / OpenAI-compatible dual-path calls, stepwise degradation, normalize, LocateError,
│  │                   locate_stream (report-while-writing)
│  ├─ streaming.py     PartialJSON: safely lift closed top-level fields out of unfinished JSON,
│  │                   plus every element of evidence / alternatives; chunk-boundary independent,
│  │                   python -m app.streaming runs 58 self-checks
│  ├─ store.py         data/ persistence: config.json read/write and masking, history.json and shots/,
│  │                   the CONFIG_FIELDS whitelist, path validation, atomic writes (temp file → fsync → replace)
│  ├─ verify.py        the free credential reachability probe; every string in its result is scrubbed then truncated
│  └─ main.py          the FastAPI app: all API routes, SSE framing, _reload_settings, in-memory rate
│                      limiting, error mapping, mounting the web/ static directory
├─ web/
│  ├─ index.html       the single-page interface: chart board left, readouts right
│  ├─ styles.css       the aeronautical-chart visual system; dark/light themes driven by CSS custom properties
│  ├─ extras.css       styles for the add-on components: schematic globe, session thumbnail rail, toasts
│  ├─ map.css          map panel styles: hairline frame, monospaced footnote, magenta fix point
│  ├─ i18n.js          the language layer: zh/en dictionaries, t()/apply() over data-i18n annotations,
│  │                   the header 中/EN toggle's persistence (localStorage "ril-lang")
│  ├─ globe.js         the built-in schematic globe: orthographic graticule SVG, no coastlines, no network
│  ├─ map.js           Mapbox with two fallbacks: interactive map → static image → one-line notice; needs MAPBOX_TOKEN
│  ├─ settings.js      validation of settings-card drafts, and derivation of "what the next request
│  │                   will use"; never touches localStorage
│  ├─ app.js           upload / drag / paste, SSE reading and progressive rendering (provisional card
│  │                   rewritten in place, evidence inserted row by row, the final result taking over
│  │                   the same map and the same gauge), scan animation, history rail, shortcuts,
│  │                   export, the settings card (model / map / data panels)
│  ├─ fonts/           IBM Plex Sans / Mono / Condensed subset woff2, self-hosted;
│  │                   OFL 1.1 full text in LICENSE-IBM-Plex.txt alongside
│  └─ vendor/
│     ├─ motion.min.js    Motion 11.18.2, vendored locally (MIT), exposes window.Motion
│     └─ LICENSE-motion.txt
├─ data/               appears at runtime only, gitignored + dockerignored; relocatable via RIL_DATA_DIR
│  ├─ config.json      configuration saved in the UI, plaintext API keys, 0600 from creation
│  ├─ history.json     metadata and complete response bodies of the last 20 analyses
│  └─ shots/           the corresponding JPEGs, one file each
├─ run.py              one command from clone to running: builds .venv, installs deps, starts uvicorn
│                      with the right flags, opens the browser. Stdlib only (it must run before
│                      the dependencies are installed)
├─ requirements.txt
├─ LICENSE             MIT
├─ .env.example
├─ .env                optional, exists only if you create it; gitignored (along with .env.bak /
│                      .env.local style copies)
├─ Dockerfile
├─ compose.yaml
├─ .dockerignore
└─ .gitignore
```

All frontend code is served straight out of `web/` by FastAPI's `StaticFiles`: **no npm, no build step, no external fonts** (the IBM Plex subsets are right there in `web/fonts/`), and Motion is vendored locally too. **The only thing fetched from someone else's server is Mapbox**: the GL JS script and its CSS load from `api.mapbox.com`, and so do the map tiles — and both happen only when `MAPBOX_TOKEN` is configured. Leave it empty and the page makes zero external requests; see the section below.

## Security boundary

This is a tool meant to be used **on your own machine, over localhost**, and every point below is derived from that premise. Read this whole section before exposing the port.

### Bind loopback; do not run on `0.0.0.0`

**None of the endpoints have any authentication.** No login, no token, no origin check. Whoever can reach this port gets your key, your quota, and your outbound network access.

With configuration and history now on disk, this weighs far more than it used to:

- **`PUT /api/settings` has no authentication.** Whoever can reach the port can rewrite the operator's saved credentials — swap the key, swap the model, wrench the provider onto the other path, or point `openai_base_url` at their own machine (they must supply their own key alongside; see ["The lock protecting the operator's own key"](#the-lock-protecting-the-operators-own-key)).
- **`DELETE /api/history` has no authentication.** One request wipes every stored photo and history entry on this machine; `DELETE /api/settings` likewise deletes all saved configuration in one request.
- Both are irreversible and unattributable — the server has no identities to record; the logs hold only field names and counts.

**This is by far the strongest reason for "loopback only".** uvicorn listens on `127.0.0.1` by default; keep it. `compose.yaml` also publishes the port to `127.0.0.1` only.

### Server-side request forgery (SSRF) is the built-in price of this feature

The purpose of `X-RIL-OpenAI-Base` is to make the server issue requests to **the URL the caller names**. `app/overrides.py:_base_url` validates exactly two things: the scheme is `http` or `https`, and a host exists. **Private-network addresses are deliberately not blocked** — the whole point of the feature is self-hosted / LAN gateways, and a private-range blacklist would break perfectly legitimate uses like `http://127.0.0.1:11434/v1`.

The cost must be stated plainly: whoever can reach this port can use this server to scan its own internal network. The `code` returned by `/api/verify` suffices to distinguish "port open" (`ok` / `auth` / `unconfirmed` / `upstream`), "port closed" (`network`) and "firewalled drop" (`timeout`), and the first 200 characters of a non-200 response body appear (scrubbed) in `detail`. For a local tool, that's an accepted trade-off; for a port other people can reach, it's an open probing proxy.

### The lock protecting the operator's own key

`parse_overrides` **flatly rejects** a request that sends `X-RIL-OpenAI-Base` without `X-RIL-OpenAI-Key` (400 `bad_override`). The reason is blunt: otherwise the caller supplies only a destination and the server helpfully attaches the currently effective `openai_api_key` (`data/config.json`, then `.env`) — delivering the operator's key to an address the caller chose, a key the caller never had. Requiring both headers together costs the settings card nothing (it already sends them together) and closes the road without any address blacklist.

The Anthropic key never had this exposure: there is no overridable Anthropic base URL, so `X-RIL-Anthropic-Key` can only change the key itself, never where it goes.

**The same rule holds verbatim for saved configuration.** `PUT /api/settings` returns 400 `bad_override` when `openai_base_url` differs from the stored value and the body carries no non-empty `openai_api_key` (`app/main.py:write_settings`). The only difference is which key would have been shipped: on the header path, the one in `.env`; on this path, the one already saved in `data/config.json` — and writing that file requires no credentials at all.

### Keys now sit on disk

`data/config.json` stores API keys in **plaintext**. No encryption, no master password, no keystore of any kind.

- The file carries `0o600` (owner read/write only) **from the moment of creation**, not chmodded after writing — there is no instant in between when anyone else can read it. The temp file used by the atomic write is likewise created `O_EXCL` + 0600.
- But say it straight: **on Windows, `os.chmod` is essentially a no-op.** In `app/store.py`'s own words — it only toggles the read-only bit, **does not restrict other users**, and there is no umask; 0600 is real on POSIX and merely a comment on Windows, where what actually holds is the NTFS ACL inherited from the parent directory. On Windows, the data directory itself must therefore live somewhere private.
- **Deletion is not erasure.** `DELETE /api/settings` removes the file (and any leftover `.config.json.*.tmp` — those hold plaintext keys too), but freed blocks remain readable on most filesystems. If you believe it leaked, rotate the key upstream; don't count on this delete.
- Backups, cloud-drive sync, `docker cp`, snapshots — all of them carry it along.

### Reads are masked; writes don't echo

- `GET /api/settings` **has no branch that returns key plaintext**. `store.public_config()` is the only read function routes may call; `store.read_config()`, which returns plaintext, serves the server's own request path exclusively and may not appear in any route.
- The `PUT /api/settings` response body is the same masked view — saving never reads back what you just typed.
- `openai_base_url` keeps only scheme + host in both endpoints: relays put credentials in the path or the userinfo all the time, and echoing the address verbatim is itself a leak.
- Logs contain only changed **field names** and `mask()` output; there is no second path.

### Photos are on disk now too

After every successful analysis, the JPEG that went to the model is written to `data/shots/`. **Anyone who can read this machine's filesystem can see every photo ever analyzed** — they no longer live only in memory, no longer vanish when the browser closes. Restarting doesn't clear them, closing the browser doesn't, clearing browser data doesn't (the data isn't in the browser anymore); only `DELETE /api/history` or deleting the directory does.

What's written is the product of `imaging.prepare` (scaled + re-encoded + EXIF stripped), so the original's GPS never reaches the disk.

### Rate limiting is a courtesy, not a security measure

Two facts hold at once:

- `REQUESTS_PER_HOUR` counts by client address, and `X-Forwarded-For` **is honored only from addresses listed in `TRUSTED_PROXIES`** (empty by default = trust nobody's).
- But uvicorn's own `--proxy-headers` **defaults to on**, rewriting the source address from `X-Forwarded-For` before the app sees the request (its own default trust list is `127.0.0.1`). So a caller on loopback can forge away regardless.

Measured: `REQUESTS_PER_HOUR=3`, six requests with six different forged `X-Forwarded-For` values — with `--no-proxy-headers` the outcome is `200 200 429 429 429 429`; without it, all six pass. **Unless a genuinely trusted proxy sits in front, always start with `--no-proxy-headers`** — `run.py` and the `Dockerfile`'s `CMD` both hard-code it; only a hand-typed `uvicorn` command line needs remembering. When `REQUESTS_PER_HOUR > 0` and `TRUSTED_PROXIES` is empty, the startup log prints a warning about exactly this.

The limiter itself is just a sliding window in process memory: restarts zero it, and multiple replicas each count their own.

### A request without `X-RIL-*` headers spends the operator's key

A bare `POST /api/locate` runs a visual inference straight on the server's currently effective credentials (`data/config.json`, then `.env`). The Claude path spends up to `MAX_TOKENS = 16000` per call at the currently effective `anthropic_effort` (default `medium`, `app/providers.py`); the gateway path `max_tokens: 4096` per call. With no authentication, nothing stops someone else from spending that money for you — and leaving one of their photos on your disk while they're at it.

### Request headers have no aggregate limit

`MAX_VALUE_LEN = 500` governs only the seven recognized header names in `app/overrides.py:_FIELDS` (and the eight `PUT /api/settings` fields); other headers are never examined — and uvicorn, when running on httptools (the default parser installed by `uvicorn[standard]`), sets no cap on header size or count. If the port could ever be touched by something untrusted, a reverse proxy in front should be imposing those limits.

### What is scrubbed, and what is not

- **`overrides.scrub`** (the mandatory path for all upstream text): first collapse whitespace — an upstream that echoes a key split across two lines would evade literal matching, and collapsing re-joins it, so doing these in the other order would be useless; matching is **case-insensitive**; if the key is still present after removing all whitespace, the whole text is discarded (returning "upstream echoed the key; content discarded") because such text is beyond editorial rescue and diagnostics aren't worth that price. It additionally replaces anything shaped like a bearer token (long strings starting `sk-` / `pk-` / `rk-`, `Bearer …`) with `[redacted]` — **including keys we hold no copy of**, such as the operator's own key echoed back by a caller-chosen relay. Truncation comes last, so a key straddling the cut can't leak out in half. An upstream error body therefore cannot carry a key into the logs or the browser.
- **`overrides.safe_url`**: any gateway address ever displayed keeps only scheme + host (+ port). Some relays put credentials in the path or the userinfo; echoing the address verbatim is itself a leak.
- **Logs**: any credential appearing in logs is `mask()` output (first 6 + last 4 characters; ≤ 14 characters becomes `***` entirely); there is no second path.
- **What it cannot stop**: scrubbing guarantees only that **this port** never emits plaintext; it guarantees nothing about the disk. The copy in `data/config.json` is plaintext and the photos in `data/shots/` are as-is — anyone who can read this machine's filesystem, and anyone holding a backup, a cloud-sync copy or the container volume, can take them. On a shared or public deployment, the key shouldn't be on the machine at all. (The browser side no longer stores any credential; upgrading from an old version, clear this origin's `localStorage` once by hand to remove the leftover `ril-model-config`.)

## Scope and privacy

- **Photos are stored on the machine running the service**: after every successful analysis the JPEG the model saw is written to `data/shots/` and the verdict to `data/history.json`. The most recent `HISTORY_CAP` (20) are kept; older ones are deleted together with their image files, and `DELETE /api/history` clears everything at once. **Restarting doesn't clear them, closing the browser doesn't, clearing browser data doesn't** — the data isn't in the browser anymore. **This is a behavior change**: earlier versions processed in memory only, used-and-gone.
- **The key is on this machine too**: credentials saved in the UI go into `data/config.json` in plaintext (0600 from creation, but `chmod` is essentially void on Windows — see [Security boundary](#security-boundary)). It replaces `.env`; treat it as `.env`. `DELETE /api/settings` only makes the app forget; it doesn't wipe the disk.
- **What's stored is what the model saw, not your original**: `imaging.prepare` has already scaled, re-encoded and stripped all EXIF; that product is what lands on disk. So the original's GPS reaches neither the model nor the disk.
- **A photo's outbound destination is exactly one**: the currently effective model endpoint, determined by `data/config.json`, `.env`, or this request's `X-RIL-OpenAI-Base` (see [Security boundary](#security-boundary)). It goes nowhere else.
- **EXIF is stripped**: the model receives a re-encoded JPEG with no GPS, no device model, no timestamps, no metadata of any kind. The original's GPS is echoed only in `meta.exifGps` for your own comparison.
- **But with `MAPBOX_TOKEN` set, it is no longer fully offline** — a trade-off to weigh, not a footnote. Once `/api/config` sends a non-empty token, the browser fetches Mapbox GL JS from `api.mapbox.com` (script and CSS, version in `web/map.js`'s `GL_VERSION`), then requests tiles carrying **the model's inferred coordinates**. If the GL script fails to arrive, it falls back to the Static Images API — an image URL that likewise spells out the coordinates and your token in plaintext (the map footnote then reads "static image · no pan/zoom" and the console logs a warning). In other words: the photo never leaves your machine, but **the verdict coordinates do go to Mapbox**.

  > Why the script comes from the CDN instead of being vendored: GL JS stopped being open source at 2.0 — it's licensed under Mapbox's Terms of Service, and committing that 1.5 MB into a public repository would be redistributing someone else's SDK (Motion is MIT, which is why it stays in `web/vendor/`). Nothing of value is lost anyway — this panel needs Mapbox tiles and a token to draw anything at all, and if `api.mapbox.com` is unreachable, it makes no difference where the script lives. Measured cold-cache: script arrives in 116 ms, interactive map at 422 ms; the 20-second `GL_TIMEOUT_MS` is budgeted for networks far worse than that, and for requests that neither refuse nor answer (captive portals, filtering proxies — they never fire an error event). Timeout degrades to the static image — a **deliberate** outcome, not a failure.
- **Leave `MAPBOX_TOKEN` empty and the page makes zero external requests**: with no token, `web/app.js`'s `buildLocationView` goes straight to the built-in schematic globe `web/globe.js` — a locally drawn SVG graticule that initiates no network traffic; the coordinates never leave the browser. For full offline, leave it empty (the Google Maps / OSM links in the result area navigate only when you click them; unclicked, nothing is sent).
- **Rate limiting**: a per-client-IP hourly sliding window, with `/api/locate`, `/api/locate/stream` and `/api/verify` sharing one bucket. Only requests from `TRUSTED_PROXIES` addresses switch to the first hop of `X-Forwarded-For`. Counts live in process memory — restarts clear them, and multi-replica deployments count separately. **This is misuse protection, not adversary protection** — see [Security boundary](#security-boundary).
- **No person recognition**: the prompt explicitly forbids identifying, naming, or speculating on the identity, occupation or home address of any person in the frame.
- **Results are probabilistic judgments**: the location, coordinates and confidence are inferences from visual detail, and can be confidently wrong. Do not use them as sole grounds for any decision with real consequences.

## License

**The project itself is MIT** — full text in [`LICENSE`](LICENSE) at the repository root. Use it, change it, redistribute it; keep the license and copyright notice attached; no warranty of any kind.

Third-party parts carry their own licenses, spelled out so you don't trip:

| What | License | Where | Watch out for |
| --- | --- | --- | --- |
| Mapbox GL JS 3.9.0 | **Mapbox Terms of Service** (proprietary — **not** open source; 1.13 and earlier were BSD-3-Clause) | Not in the repository; the browser loads it from `api.mapbox.com` | Using it requires a Mapbox account in good standing. Which is why this repo doesn't vendor it — committing that 1.5 MB into a public repository would redistribute Mapbox's SDK. Leave `MAPBOX_TOKEN` unset and you never touch it |
| Motion 11.18.2 | **MIT** | `web/vendor/motion.min.js`, license full text alongside in `LICENSE-motion.txt` | MIT allows redistribution provided the copyright and license notice ride along — that file exists for exactly that |
| IBM Plex Sans / Mono / Condensed subsets | **SIL Open Font License 1.1** | `web/fonts/*.woff2`, license full text alongside in `LICENSE-IBM-Plex.txt` | OFL permits bundling and redistribution with software provided every copy carries the copyright notice and full license; modified fonts keeping the original name are bound by the Reserved Font Name clause |
| Python dependencies (fastapi, uvicorn, anthropic, httpx, pillow, python-multipart, python-dotenv) | Their own open-source licenses; not in this repository | `requirements.txt`, installed into `.venv/` by pip | They are installed, not distributed by this project |

**The Anthropic API is not part of this project.** You use your own key and your own account; billing and usage terms are between you and Anthropic — this project only sends the image over and takes the JSON back.
