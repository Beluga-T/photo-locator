"""On-disk state: the settings the user typed, and the photos they analysed.

Until now nothing survived a restart. Credentials lived in the browser's
localStorage and came back as X-RIL-* headers (see app/overrides.py), and an
analysed photo existed only for the length of one request. This module is the
other choice: the settings sheet writes to a file on the machine running the
server, and every analysed photo is kept alongside its answer.

    <RIL_DATA_DIR or ./data>/
        config.json        the UI-entered overrides — CONTAINS API KEYS
        history.json       one entry per analysed photo, newest last
        shots/<id>.<ext>   the image bytes, one file each

PRIVACY — what this costs, in plain terms. Photos people analyse and the API
keys they paste now sit unencrypted on this machine's disk and stay there until
something clears them. Restarting the app does not clear them; closing the
browser does not clear them; clearing the browser's storage does not clear them,
because the data is no longer in the browser. Only clear_config()/clear_shots()
or deleting the directory does.

What protects that data: file permissions (config.json is created 0600, owner
only) and the fact that the HTTP port never returns a key in the clear —
public_config() masks them, and read_config() is for the server's own request
path, not for a route. The directory is listed in .gitignore and .dockerignore,
so it does not travel with the source or into an image.

What does NOT protect it: nothing is encrypted, the disk may keep freed blocks
readable after a delete, and the port has no authentication at all — anyone who
can read this filesystem, back it up, or sync it to a cloud drive gets both the
photos and the keys. Bind the server to localhost and treat the data directory
the way you would treat .env.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .overrides import MAX_VALUE_LEN, mask, safe_url

log = logging.getLogger("locator.store")

# <project>/data — app/store.py -> app -> project root. Sits next to .env, which
# is the right mental model: same machine, same trust boundary, same secrets.
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

DATA_DIR_ENV = "RIL_DATA_DIR"

# How many analysed photos to keep. This is a disk budget, not a preference:
# each entry is a whole image, and an unbounded history fills the volume the
# server itself runs on.
HISTORY_CAP = 20

# The only keys write_config will store. An allowlist rather than a filter,
# because the file is later merged over the operator's Settings — an attacker
# who could add arbitrary keys here could reach further than the settings sheet
# ever intended (max_upload_bytes, trusted_proxies, request_timeout...).
CONFIG_FIELDS: tuple[str, ...] = (
    "provider",
    "anthropic_api_key",
    "anthropic_model",
    "anthropic_effort",
    "openai_base_url",
    "openai_api_key",
    "openai_model",
    "mapbox_token",
)

# Model credentials. Never returned in the clear over HTTP.
#
# mapbox_token is deliberately absent: it is a public pk.* token that already
# ships to the browser so the map can render (see /api/config), so masking it
# would only stop the settings sheet from showing the user what they typed.
SECRET_FIELDS: frozenset[str] = frozenset({"anthropic_api_key", "openai_api_key"})

# Not a secret by itself, and not masked either — reduced to scheme+host on the
# way out. Relays that carry the credential in the path ("…/sk-abc…/v1") or in
# userinfo ("https://user:key@host/v1") are common, so echoing the URL verbatim
# to an unauthenticated route hands over the key just as surely as the key field
# would. overrides.safe_url exists for exactly this; the cost is that the
# settings sheet cannot show the user the tail of the address they typed.
_URL_FIELDS: frozenset[str] = frozenset({"openai_base_url"})

# A shot id, as it arrives from a URL path segment. Letters, digits, hyphen and
# underscore only — the pattern is what actually holds, not any later string
# check, because the framework has already percent-decoded the segment by the
# time we see it: "%2e%2e%2f" is plain "../" here, and "%00" is a real NUL byte.
# No "." at all means ".." cannot be spelled; no "/" ":" or "\" means neither a
# separator nor a drive letter can be. 64 chars is well past our own ids.
#
# \A and \Z rather than ^ and $, and fullmatch rather than match: Python's $
# also matches immediately before a terminal newline, so "goodid\n" would pass
# a gate the comment above calls the thing that actually holds — and the name
# that reaches the filesystem is the one with the newline still on it.
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")

# The one class of name that passes the allowlist above and still is not a file
# on Windows: DOS device names resolve to the device even with an extension, so
# shots/NUL.jpg is the null device and reads back as empty. Our own ids always
# start with a year, so this can only ever be a hand-crafted request.
_WINDOWS_DEVICES = frozenset(
    {"con", "prn", "aux", "nul", "clock$"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)

# Media type -> file extension, and the reverse. Doubles as the allowlist for
# what read_shot may report: a stored media_type is handed straight back as a
# response Content-Type, so anything unrecognised collapses to octet-stream
# rather than letting a caller-chosen "text/html" be served from our origin.
# In practice imaging.prepare() only ever produces JPEG; the rest is for the
# day someone stores the original upload instead of the analysed copy.
_EXTENSIONS: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/tiff": "tif",
}
_MEDIA_TYPES: dict[str, str] = {ext: media for media, ext in _EXTENSIONS.items()}
_FALLBACK_MEDIA = "application/octet-stream"
_FALLBACK_EXT = "bin"

# Owner read/write. Set at creation time rather than after, so the file is never
# briefly world-readable while it already holds a key.
_SECRET_MODE = 0o600


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id() -> str:
    """A sortable, filesystem-safe id.

    Fixed-width UTC timestamp first, so lexicographic order is chronological and
    the history file can be trusted to be in order even after hand-editing. The
    random tail breaks ties between two uploads in the same microsecond and
    keeps ids unguessable enough that knowing one does not give you the next.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    return f"{stamp}-{secrets.token_hex(4)}"


class Store:
    """Everything this app keeps on disk. Synchronous, thread-safe, never raises.

    Every method is fast and purely synchronous — no sleeping, no network, no
    subprocess. The route handlers are async and call these directly on the
    event loop, so a blocking call here would stall every other request.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        # Explicit argument > environment > <project>/data. The environment hook
        # is what makes a container's bind mount work without a code change.
        chosen = root if root is not None else (os.getenv(DATA_DIR_ENV) or "").strip()
        try:
            candidate = Path(chosen).expanduser() if chosen else DEFAULT_DATA_DIR
            if "\x00" in str(candidate):
                # Not every version raises on construction — CPython 3.12 lets
                # the NUL through Path() and only rejects it at the first
                # syscall, which would be a mkdir inside someone's write.
                raise ValueError(f"NUL byte in {DATA_DIR_ENV}")
            self._root = candidate
        except (ValueError, RuntimeError, OSError):
            # Path() raises ValueError for a NUL byte in the value, and
            # expanduser() raises RuntimeError when a leading "~" cannot be
            # resolved because neither HOME nor USERPROFILE is set — which is
            # ordinary inside a stripped-down container. The constructor runs at
            # import time on the server's startup path, so a bad RIL_DATA_DIR
            # must degrade to the default, not stop the process from booting.
            log.exception("unusable data directory %r — falling back to the default", chosen)
            self._root = DEFAULT_DATA_DIR
        self._config_path = self._root / "config.json"
        self._history_path = self._root / "history.json"
        self._shots_dir = self._root / "shots"

        # One lock for the whole store, held across each read-modify-write.
        # Reentrant because the public methods call each other (write_config ->
        # public_config) and a plain Lock would deadlock the second hop.
        #
        # This guards one process. A second uvicorn worker or a second Store on
        # the same directory is NOT serialised — os.replace still keeps every
        # file whole, but concurrent writers become last-writer-wins. Run one
        # worker, which is what a single-user local tool wants anyway.
        self._lock = threading.RLock()

        self._ensure_dirs()

    @property
    def root(self) -> Path:
        return self._root

    # ── plumbing ──────────────────────────────────────────────────────────

    def _ensure_dirs(self) -> bool:
        """Create the data directory. Called before every write, because the
        user may well delete the directory while the server is running."""
        try:
            self._shots_dir.mkdir(parents=True, exist_ok=True)  # creates root too
            return True
        except (OSError, ValueError):
            # ValueError as well as OSError: a NUL anywhere in the path is
            # rejected by the syscall wrapper, not the filesystem, and this runs
            # ahead of every write — "the write failed" is the answer, not an
            # exception out of write_config.
            log.exception("cannot create data directory %s", self._root)
            return False

    def _read_json(self, path: Path, fallback: Any) -> Any:
        """Load a JSON file, degrading to `fallback` for any reason at all.

        A truncated write, a hand-edit with a trailing comma, a file the user
        chmod'd away — none of those are worth taking the service down for. The
        next successful write repairs the file.
        """
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return fallback
        except OSError:
            log.exception("cannot read %s — treating as empty", path.name)
            return fallback
        if not raw.strip():
            return fallback
        try:
            loaded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            # RecursionError is not a ValueError: a hand-edited file nested a few
            # thousand brackets deep blows the interpreter stack inside the
            # parser, and without this it propagates out of read_config() on the
            # request path — the one place this module promises never to raise.
            log.warning("%s is corrupt — treating as empty, next write repairs it", path.name)
            return fallback
        # Right JSON, wrong shape (an object where we wanted a list) is the same
        # class of problem as a parse error.
        if type(loaded) is not type(fallback):
            log.warning("%s has unexpected shape %s — treating as empty", path.name, type(loaded))
            return fallback
        return loaded

    def _write_json(self, path: Path, value: Any) -> bool:
        try:
            # default=str so one unserialisable object in a payload cannot cost
            # the user their whole history.
            blob = json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        except (TypeError, ValueError):
            log.exception("cannot serialise %s", path.name)
            return False
        return self._write_atomic(path, blob)

    def _write_atomic(self, path: Path, blob: bytes) -> bool:
        """Replace `path` with `blob`, or leave it exactly as it was.

        A half-written config.json means a user has lost the key they pasted, so
        the content is never written into the live file: temp file in the SAME
        directory (os.replace is only atomic within one filesystem), flush,
        fsync so the bytes are on the platter before the rename, then replace.
        A crash at any point leaves either the old file or the new one.
        """
        if not self._ensure_dirs():
            return False
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        try:
            # O_EXCL: never adopt a leftover temp file someone else may hold
            # open. Mode is applied at creation, so there is no instant where a
            # file holding an API key is readable by anyone else.
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _SECRET_MODE)
            # Through the buffered object, not os.write: the raw syscall is
            # allowed to write fewer bytes than it was handed, and a short write
            # here would be renamed over the live file as if it were the whole
            # thing — a config.json that reads back as corrupt JSON and takes
            # every stored credential with it. file.write() loops until the
            # buffer is out or it raises. fsync still happens before the replace.
            with os.fdopen(fd, "wb") as handle:
                handle.write(blob)
                handle.flush()
                os.fsync(handle.fileno())
            # Belt and braces: on Windows os.chmod only toggles the read-only
            # bit — it does NOT restrict other users, and there is no umask
            # either. Treat 0600 as real on POSIX and as documentation on
            # Windows; NTFS ACLs inherited from the parent are what actually
            # apply there, so the data directory should live somewhere private.
            os.chmod(tmp, _SECRET_MODE)
            os.replace(tmp, path)
        except OSError:
            log.exception("failed writing %s", path.name)
            _unlink_quietly(tmp)
            return False
        except BaseException:
            # Anything else that can land between the open and the replace —
            # MemoryError on a large blob, KeyboardInterrupt, a SystemExit
            # raised from a signal handler. The temp file holds the same bytes
            # the live file would, which for config.json is the API key in the
            # clear, and nothing would ever come back for it: it is not
            # config.json, so clear_config's unlink misses it, and its name is
            # unguessable, so the user cannot find it either. Remove it first,
            # then let the exception carry on exactly as it was.
            _unlink_quietly(tmp)
            raise

        # Durability of the rename itself, on POSIX. Windows cannot open a
        # directory as a file descriptor, hence the guard rather than a bare try.
        if hasattr(os, "O_DIRECTORY"):
            try:
                dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        return True

    # ── config ────────────────────────────────────────────────────────────

    def read_config(self) -> dict[str, str]:
        """SECRETS IN THE CLEAR — server-internal use only, NEVER a route.

        This is what the request path merges over Settings before calling a
        provider, so it has to return the real key. Returning it over HTTP would
        hand every API key to anyone who can reach the port, and the port has no
        authentication. If you are writing a route, you want public_config().
        """
        with self._lock:
            return self._read_config_locked()

    def _read_config_locked(self) -> dict[str, str]:
        loaded = self._read_json(self._config_path, {})
        # Re-validate on the way out: the file is editable by hand, and an
        # unknown or non-string key must not reach Settings just because it got
        # onto disk somehow.
        config: dict[str, str] = {}
        for field in CONFIG_FIELDS:
            value = loaded.get(field)
            if not isinstance(value, str) or not value:
                continue
            if len(value) > MAX_VALUE_LEN:
                # Refused, not truncated. write_config caps on the way IN, where
                # cutting is the caller's own paste being tidied; cutting on the
                # way OUT would turn a hand-edited key into a subtly wrong one
                # and send it to a provider as if the user had typed it, which
                # reads as "the provider rejected my key" and nothing else.
                log.warning(
                    "%s in %s is %d chars, over the %d limit — ignoring it",
                    field,
                    self._config_path.name,
                    len(value),
                    MAX_VALUE_LEN,
                )
                continue
            config[field] = value
        return config

    def public_config(self) -> dict[str, str]:
        """The config with every secret masked. The ONLY config reader a route
        may expose.

        The masking is app.overrides.mask and the URL trimming is
        app.overrides.safe_url — both imported rather than reimplemented, so the
        settings sheet shows a key the same way the log does: enough to
        recognise, never enough to use. The service listens without
        authentication, so a raw key in a response body is a key handed to
        whoever can reach the port — including anything else on the machine and
        anything on the LAN if the bind address is not loopback.
        """
        return _public_view(self.read_config())

    def write_config(self, patch: Mapping[str, Any]) -> dict[str, str]:
        """Merge `patch` into the stored config. Returns the MASKED result.

        Merge, not replace: a key the patch does not mention keeps its stored
        value, which is what lets the settings sheet send only the field the
        user touched. A key present with an empty string is an explicit clear
        and is removed from the file — that is how a user blanks one credential
        without blanking the others.

        The return value goes through the same reduction as public_config()
        because the caller is a route: keys masked, openai_base_url cut back to
        scheme+host. Anything server-side that needs the real values calls
        read_config().
        """
        with self._lock:
            config = self._read_config_locked()
            changed = False

            for key, raw in (patch or {}).items():
                field = str(key).strip()
                if field not in CONFIG_FIELDS:
                    # Ignored, never stored. Logged at debug only: the key name
                    # is caller-controlled and does not belong in a normal log.
                    log.debug("ignoring unknown config field %r", field[:40])
                    continue

                value = _coerce(field, raw)
                if value is None:  # unusable type — leave whatever is stored
                    continue
                if not value:  # explicit clear
                    if config.pop(field, None) is not None:
                        changed = True
                    continue
                if config.get(field) != value:
                    config[field] = value
                    changed = True

            if changed and not self._write_atomic(
                self._config_path,
                json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8"),
            ):
                # The write failed; report what is actually on disk, not what we
                # hoped to put there, so the UI does not claim a saved key.
                return self.public_config()

            return _public_view(config)

    def clear_config(self) -> dict[str, str]:
        """Forget every stored credential. Returns the (now empty) masked config.

        The file is removed rather than blanked. Neither actually scrubs the
        bytes — a deleted file's blocks stay readable on most filesystems until
        they are reused — so this is "the app has forgotten it", not "the disk
        has forgotten it". Rotate a key you believe was exposed.
        """
        with self._lock:
            try:
                self._config_path.unlink(missing_ok=True)
            except OSError:
                # Deleting failed (a lock, a read-only mount). Blank the file
                # instead — leaving the keys in place while telling the UI they
                # are gone is the one outcome worse than either.
                log.exception("cannot delete %s — blanking it instead", self._config_path.name)
                self._write_atomic(self._config_path, b"{}")

            # The temp files too. _write_atomic writes the whole config, keys
            # and all, into .config.json.<pid>.<hex>.tmp before renaming it into
            # place; a crash in between leaves that file behind at 0600 with the
            # key in the clear. Unlinking config.json alone would report "every
            # stored credential forgotten" while the credential is still on
            # disk, under a name the user has no reason to look for.
            for stray in self._list_dir(self._root, f".{self._config_path.name}.*.tmp"):
                log.warning("removing leftover %s — it held credentials", stray.name)
                _unlink_quietly(stray)

            # Re-read rather than assume: if both attempts failed the caller
            # must see what is still stored, not an empty dict we wished for.
            return self.public_config()

    # ── history ───────────────────────────────────────────────────────────

    def _read_history_locked(self) -> list[dict]:
        entries = self._read_json(self._history_path, [])
        # Drop anything that is not a usable entry; a hand-edited file should
        # cost the user that one row, not the whole history.
        return [
            entry
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and _valid_id(entry["id"])
        ]

    def list_shots(self) -> list[dict]:
        """Every stored analysis, newest first. Metadata and payload only —
        the image bytes are a separate request to read_shot()."""
        with self._lock:
            return list(reversed(self._read_history_locked()))

    def add_shot(self, image: bytes, media_type: str, payload: Mapping) -> dict | None:
        """Store one analysed photo and its answer. Returns the entry, or None.

        The entry holds metadata and the /api/locate response body, never the
        image itself: base64 in the index would multiply its size by 4/3 and
        make listing the history cost as much as downloading every photo in it.
        """
        if not isinstance(image, (bytes, bytearray)) or not image:
            log.warning("refusing to store an empty shot")
            return None

        media = str(media_type or "").split(";")[0].strip().lower()
        if media not in _EXTENSIONS:
            # Unknown types are stored, but never described as something a
            # browser will execute — see _EXTENSIONS.
            log.warning("unknown media type %r — storing as %s", media[:40], _FALLBACK_MEDIA)
            media = _FALLBACK_MEDIA
        ext = _EXTENSIONS.get(media, _FALLBACK_EXT)

        blob = bytes(image)
        entry = {
            "id": _new_id(),
            "created_at": _now_iso(),
            "media_type": media,
            "size_bytes": len(blob),
            "payload": _coerce_payload(payload),
        }

        # The whole write is under the lock, including the image fsync, which is
        # the slowest thing this module does and runs on the event loop. It is a
        # read-modify-write of history.json — read the index, append, evict,
        # write it back — and dropping the lock anywhere in the middle would let
        # a second add_shot resurrect an evicted entry or lose this one. A photo
        # silently missing from the history is worse than a stall, so
        # correctness wins here; read_shot, which has no such excuse, does its
        # file read outside the lock.
        with self._lock:
            path = self._shots_dir / f"{entry['id']}.{ext}"
            if not self._write_atomic(path, blob):
                return None

            history = self._read_history_locked()
            history.append(entry)
            evicted = history[:-HISTORY_CAP] if len(history) > HISTORY_CAP else []
            history = history[-HISTORY_CAP:]

            if not self._write_json(self._history_path, history):
                # The index is the source of truth. If it did not land, the
                # image file is an orphan — remove it rather than leak a photo
                # that nothing references and nothing will ever clear.
                self._unlink_shot(entry["id"])
                return None

            for old in evicted:
                self._unlink_shot(old["id"])
            if evicted:
                log.info("history at cap %d — evicted %d oldest", HISTORY_CAP, len(evicted))

            # The index we just wrote is now the complete list of shots that
            # exist, so anything else in shots/ is unreachable. This is the only
            # thing that ever reclaims those files: a history.json that went
            # missing or corrupt reads back as [], eviction then sees nothing to
            # evict, and the up-to-20 files already on disk would never be
            # referenced or deleted again — repeat that and shots/ grows without
            # bound while the history keeps reporting HISTORY_CAP or fewer.
            self._reconcile_shots_locked(history)

            return dict(entry)

    def read_shot(self, shot_id: str) -> tuple[bytes, str] | None:
        """The image bytes and their media type, or None if there is no such shot."""
        # Only the index lookup is serialised. The image itself is up to
        # max_upload_bytes — 12 MB by default — and this is called from an async
        # route handler, so reading it under the lock would block the event loop
        # and every other request behind it for the length of a disk read.
        with self._lock:
            path = self._shot_file(shot_id)
            if path is None:
                return None

            # Prefer the index's media type; fall back to the extension so a
            # lost history.json does not make the images unreadable.
            media: str | None = None
            for entry in self._read_history_locked():
                if entry["id"] == shot_id:
                    stored = entry.get("media_type")
                    if isinstance(stored, str) and stored in _EXTENSIONS:
                        media = stored
                    break

        # Outside the lock. A delete_shot landing in this gap makes the read
        # fail, and None is exactly what a deleted shot should return anyway.
        try:
            blob = path.read_bytes()
        except OSError:
            log.exception("cannot read shot file")
            return None
        if not blob:
            return None
        return blob, media or _MEDIA_TYPES.get(path.suffix.lstrip("."), _FALLBACK_MEDIA)

    def delete_shot(self, shot_id: str) -> bool:
        """Forget one shot: its image file and its history entry."""
        with self._lock:
            if not _valid_id(shot_id):
                log.warning("rejected shot id")
                return False
            removed_file = self._unlink_shot(shot_id)

            history = self._read_history_locked()
            kept = [entry for entry in history if entry["id"] != shot_id]
            removed_entry = len(kept) != len(history)
            if removed_entry and not self._write_json(self._history_path, kept):
                # Say what happened, not what was attempted. The index write is
                # what makes a shot gone: if it failed the entry still lists,
                # still counts against HISTORY_CAP, and read_shot now returns
                # None for it — a caller told "removed" would never retry.
                log.warning("could not rewrite the index — the entry is still listed")
                return False
            return removed_file or removed_entry

    def clear_shots(self) -> int:
        """Delete every stored photo. Returns how many history entries went."""
        with self._lock:
            history = self._read_history_locked()
            for entry in history:
                self._unlink_shot(entry["id"])

            # Sweep whatever else is in shots/ as well: an entry whose write
            # failed halfway, a file left by an older layout, or a directory
            # somebody dropped in there would otherwise sit there forever with
            # no way for the user to clear it.
            self._sweep_dir(self._shots_dir)

            if not self._write_json(self._history_path, []):
                # The files are gone but the index still names them. Reporting
                # the old count would tell the UI the history is empty when the
                # next list_shots will still show every row.
                log.warning("cleared the shot files but the index write failed")
                return 0
            return len(history)

    def _reconcile_shots_locked(self, history: list[dict]) -> None:
        """Delete every file in shots/ that `history` does not name.

        Called with the index that was just written, which by definition is the
        complete list of shots that exist. Nothing else ever notices an image
        file the index has lost track of.
        """
        keep = {entry["id"] for entry in history}
        for stray in self._list_dir(self._shots_dir):
            if stray.name.endswith(".tmp"):
                continue  # a write in flight — ours a moment ago, or another process's
            # Our names are "<id>.<ext>" and an id never contains a dot, so the
            # part before the first dot is the id, and a dotfile yields "" and
            # is swept like any other thing we did not write.
            if stray.name.split(".", 1)[0] in keep:
                continue
            try:
                if stray.is_dir() and not stray.is_symlink():
                    continue  # we never create one; not ours to remove on a write path
                stray.unlink(missing_ok=True)
                log.info("removed an orphaned shot file the index had lost")
            except OSError:
                # One undeletable file must not stop the rest being reclaimed.
                log.exception("cannot delete orphaned shot file")

    def _sweep_dir(self, directory: Path) -> None:
        """Empty a directory, entry by entry. Never raises.

        Per-entry error handling on purpose: a single locked or read-only file
        used to abort the whole loop and strand every photo after it, which for
        "delete everything" is the one failure mode that matters. Directories go
        too — a subdirectory in shots/ was previously skipped outright and so
        could never be cleared through the UI at all.
        """
        for stray in self._list_dir(directory):
            try:
                if stray.is_dir() and not stray.is_symlink():
                    shutil.rmtree(stray, ignore_errors=True)
                else:
                    stray.unlink(missing_ok=True)
            except OSError:
                log.exception("cannot delete %s", stray.name)

    @staticmethod
    def _list_dir(directory: Path, pattern: str | None = None) -> list[Path]:
        """Directory listing as a concrete list, or [] if it cannot be read.

        Materialised before use because the callers delete as they go, and an
        iterator over a directory being mutated is undefined on some platforms.
        iterdir() rather than glob("*") when there is no pattern: the glob rules
        hide dotfiles, and a leftover .<name>.<pid>.<hex>.tmp is exactly the kind
        of thing a sweep exists to remove.
        """
        try:
            return sorted(directory.glob(pattern) if pattern else directory.iterdir())
        except OSError:
            log.exception("cannot list %s", directory)
            return []

    # ── shot paths ────────────────────────────────────────────────────────

    def _shot_file(self, shot_id: str) -> Path | None:
        """Locate a shot's file, refusing anything that is not squarely inside
        shots/.

        Two independent checks, deliberately. The allowlist is what actually
        holds — it runs on the already-decoded string the framework hands us and
        cannot express "..", a separator, a drive letter or a NUL. The resolve()
        + is_relative_to() below is the backstop that catches what a pattern
        cannot see: a symlink inside shots/ pointing somewhere else, or a future
        edit that widens the pattern by one character.
        """
        if not _valid_id(shot_id):
            log.warning("rejected shot id")
            return None
        try:
            base = self._shots_dir.resolve()
        except OSError:
            return None

        for candidate in self._candidates(shot_id, base):
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(base):
                # Only reachable via a symlink or a race; still worth refusing
                # loudly, because it is the shape a real escape would have.
                log.warning("shot path escaped %s — refusing", base)
                continue
            if resolved.is_file():
                return resolved
        return None

    def _candidates(self, shot_id: str, base: Path) -> list[Path]:
        """The file this id could be, across the extensions we write.

        Built from our own table rather than by globbing on the id, so nothing
        caller-supplied is ever interpreted as a pattern.
        """
        exts = list(_EXTENSIONS.values()) + [_FALLBACK_EXT]
        return [base / f"{shot_id}.{ext}" for ext in exts]

    def _unlink_shot(self, shot_id: str) -> bool:
        path = self._shot_file(shot_id)
        if path is None:
            return False
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            log.exception("cannot delete shot file")
            return False


def _unlink_quietly(path: Path) -> None:
    """Remove a file, swallowing every failure. For cleanup paths that are
    already handling something else and must not raise on top of it."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.warning("cannot remove %s", path.name)


def _public_view(config: Mapping[str, str]) -> dict[str, str]:
    """One config, reduced to what an unauthenticated route may return.

    Keys are masked; the gateway URL keeps only scheme and host. Everything else
    is echoed as stored — see SECRET_FIELDS and _URL_FIELDS for why each field
    is on the list it is on.
    """
    public: dict[str, str] = {}
    for field, value in config.items():
        if field in SECRET_FIELDS:
            public[field] = mask(value)
        elif field in _URL_FIELDS:
            public[field] = safe_url(value)
        else:
            public[field] = value
    return public


def _coerce_payload(payload: Any) -> dict:
    """The /api/locate response body, as something safe to put in the index.

    This is the one field that arrives straight from a response body, and
    dict(payload or {}) was unguarded: dict("abc") raises ValueError and dict(5)
    raises TypeError, so a provider or a caller sending the wrong shape took the
    whole store_shot call down with it. The photo and its metadata are worth
    keeping even when the answer is not, so a bad payload costs the payload.
    """
    if not payload:
        return {}
    if not isinstance(payload, Mapping):
        log.warning("payload is %s, not a mapping — storing it empty", type(payload).__name__)
        return {}
    try:
        return dict(payload)
    except Exception:  # a Mapping whose own iteration raises  # noqa: BLE001
        log.exception("cannot copy payload — storing it empty")
        return {}


def _valid_id(shot_id: Any) -> bool:
    """Whether a URL path segment may be used to build a filename at all."""
    if not isinstance(shot_id, str) or not _ID_RE.fullmatch(shot_id):
        return False
    # See _WINDOWS_DEVICES: the stem is what Windows matches, so strip nothing —
    # our ids never contain a dot, so the whole id is the stem.
    return shot_id.lower() not in _WINDOWS_DEVICES


def _coerce(field: str, raw: Any) -> str | None:
    """One config value, normalised. None means "unusable — leave it alone",
    "" means "the caller asked to clear this".

    Strings are stripped (whitespace is a paste artifact, exactly as in
    overrides._clean) and capped at the same 500 characters the header layer
    allows, so the two entry points cannot disagree about what fits. Numbers are
    accepted because JSON makes it easy to send 0 where "0" was meant;
    everything else — bool, null, list, dict — is refused rather than
    stringified into "True" or "None", which would be stored and later sent to a
    provider as if the user had typed it.
    """
    if isinstance(raw, str):
        value = raw.strip()
    elif isinstance(raw, bool) or raw is None:
        return None
    elif isinstance(raw, (int, float)):
        value = str(raw)
    else:
        log.debug("ignoring %s: unsupported type %s", field, type(raw).__name__)
        return None

    if len(value) > MAX_VALUE_LEN:
        log.warning("%s exceeds %d chars — truncated", field, MAX_VALUE_LEN)
        value = value[:MAX_VALUE_LEN]

    # A stored value is replayed into an HTTP request later (an Authorization
    # header, a base URL). A control byte there is header injection or a client
    # crash, and it can only be a mangled paste or an attack, so refuse the
    # value instead of silently repairing it into something the user did not type.
    if value and any(char < "\x20" or char == "\x7f" for char in value):
        log.warning("%s contains control characters — ignored", field)
        return None
    return value


if __name__ == "__main__":
    # Self-check: python -m app.store
    import shutil
    import tempfile

    logging.basicConfig(level=logging.CRITICAL)  # the failure paths below log on purpose

    workdir = Path(tempfile.mkdtemp(prefix="ril-store-"))
    try:
        store = Store(workdir / "data")
        assert store.root == workdir / "data"
        assert (store.root / "shots").is_dir()

        # ── config: merge, not replace ─────────────────────────────────────
        assert store.read_config() == {}, "a fresh store is empty"
        assert store.public_config() == {}

        KEY = "sk-ant-api03-" + "A" * 40
        OAI = "sk-oai-" + "B" * 40
        store.write_config({"provider": "claude", "anthropic_api_key": KEY})
        store.write_config({"anthropic_model": "claude-opus-5"})  # mentions neither
        merged = store.read_config()
        assert merged == {
            "provider": "claude",
            "anthropic_api_key": KEY,
            "anthropic_model": "claude-opus-5",
        }, merged
        print("merge      ", sorted(merged))

        # ── config: "" clears exactly one key ──────────────────────────────
        store.write_config({"anthropic_model": ""})
        after = store.read_config()
        assert "anthropic_model" not in after
        assert after["anthropic_api_key"] == KEY, "clearing one key kept the others"
        assert store.write_config({"anthropic_model": "   "}) is not None  # whitespace == clear
        print("clear one  ", sorted(after))

        # ── config: unknown keys never reach the file ──────────────────────
        store.write_config(
            {
                "openai_api_key": OAI,
                "max_upload_bytes": 999999999,  # a real Settings field — still refused
                "trusted_proxies": "0.0.0.0/0",
                "__class__": "nope",
                "../../etc/passwd": "nope",
            }
        )
        on_disk = json.loads((store.root / "config.json").read_text("utf-8"))
        assert set(on_disk) <= set(CONFIG_FIELDS), on_disk
        assert "max_upload_bytes" not in on_disk and "trusted_proxies" not in on_disk
        print("unknown    ", "ignored:", sorted(set(CONFIG_FIELDS) & {"max_upload_bytes"}) or "none")

        # ── config: bad types and oversized values ─────────────────────────
        store.write_config({"openai_model": ["gpt-4o"], "provider": {"a": 1}})
        assert store.read_config()["provider"] == "claude", "a bad type left the value alone"
        assert "openai_model" not in store.read_config()
        store.write_config({"openai_model": "x" * (MAX_VALUE_LEN + 50)})
        assert len(store.read_config()["openai_model"]) == MAX_VALUE_LEN
        store.write_config({"openai_model": "gpt-4o\nX-Injected: 1"})
        assert store.read_config()["openai_model"] == "x" * MAX_VALUE_LEN, "control chars refused"
        store.write_config({"openai_model": "gpt-4o"})
        print("types      ", "bad type/ctrl refused, 500-char cap applied")

        # ── public_config masks both secrets and nothing else ──────────────
        store.write_config({"mapbox_token": "pk.eyJ1IjoidGVzdCIsImEiOiJja3h4In0.abcdef"})
        public = store.public_config()
        private = store.read_config()
        assert set(public) == set(private)
        for field in SECRET_FIELDS:
            assert public[field] == mask(private[field]) != private[field], field
            assert private[field] not in json.dumps(public), f"{field} leaked"
        for field in set(private) - SECRET_FIELDS - _URL_FIELDS:
            assert public[field] == private[field], f"{field} should not be masked"
        assert KEY not in json.dumps(public) and OAI not in json.dumps(public)
        print("mask       ", public["anthropic_api_key"], public["openai_api_key"])
        print("unmasked   ", public["provider"], public["mapbox_token"][:14] + "…")

        # ── the gateway URL is a credential too ────────────────────────────
        # Relays carry the key in the path or in userinfo; read_config keeps the
        # real address because that is the server's own request path, but no
        # route may see it.
        RELAYS = (
            ("https://relay.example/sk-Xk3ABCDEFGH9fQ/v1", "https://relay.example", "Xk3ABCDEFGH9fQ"),
            ("https://u:sk-gw-pw-000000@gw.example:8443/v1", "https://gw.example:8443", "gw-pw-000000"),
        )
        for relay, expected, embedded in RELAYS:
            written = store.write_config({"openai_base_url": relay})
            assert store.read_config()["openai_base_url"] == relay, "read_config keeps it whole"
            for shown in (written, store.public_config()):
                url = shown["openai_base_url"]
                assert url == expected, url
                assert embedded not in json.dumps(shown), f"credential leaked in {url}"
        print("base url   ", store.public_config()["openai_base_url"], "(path/userinfo dropped)")
        store.write_config({"openai_base_url": ""})

        # ── an over-long hand-edited value is refused, not truncated ───────
        forged = json.dumps({"anthropic_api_key": KEY, "openai_model": "y" * (MAX_VALUE_LEN + 1)})
        (store.root / "config.json").write_text(forged, "utf-8")
        reread = store.read_config()
        assert "openai_model" not in reread, "an over-long stored value must not be truncated"
        assert reread["anthropic_api_key"] == KEY, "the other fields still load"
        print("over-long  ", "refused rather than cut to a subtly wrong value")

        # ── corrupt config.json degrades to empty, next write repairs ──────
        (store.root / "config.json").write_bytes(b'{"anthropic_api_key": "sk-tru')
        assert store.read_config() == {}, "truncated JSON must not raise"
        assert store.public_config() == {}
        (store.root / "config.json").write_bytes(b"[1, 2, 3]")
        assert store.read_config() == {}, "right JSON, wrong shape"
        (store.root / "config.json").write_bytes(b"\xff\xfe not utf-8 at all")
        assert store.read_config() == {}
        # Nested past the interpreter's stack limit: json raises RecursionError,
        # which is not a ValueError and would otherwise escape read_config().
        (store.root / "config.json").write_bytes(b"[" * 200_000 + b"]" * 200_000)
        assert store.read_config() == {}, "deep nesting must not raise RecursionError"
        assert store.list_shots() is not None  # the same guard on the history side
        repaired = store.write_config({"anthropic_api_key": KEY})
        assert store.read_config() == {"anthropic_api_key": KEY}, "the next write repairs it"
        assert repaired["anthropic_api_key"] == mask(KEY)
        print("corrupt    ", "degraded to {} four ways (incl. deep nesting), then repaired")

        # ── every byte lands, and the file is only ever whole ──────────────
        # os.write may write short; the buffered object does not. A config.json
        # committed half-written reads back as corrupt JSON and takes every
        # stored credential with it, so the size on disk is the thing to assert.
        big = json.dumps({"anthropic_api_key": KEY, "pad": "p" * (4 * 1024 * 1024)}).encode("utf-8")
        probe = store.root / "big.json"
        assert store._write_atomic(probe, big) is True
        assert probe.stat().st_size == len(big), "short write committed as if whole"
        assert json.loads(probe.read_bytes().decode("utf-8"))["anthropic_api_key"] == KEY
        probe.unlink()
        assert store._list_dir(store.root, ".big.json.*.tmp") == [], "a temp file survived"
        print("whole write", f"{len(big)} bytes in, {len(big)} bytes on disk, no temp left")

        # A temp file that outlived its write holds the key in the clear, so
        # "forget every stored credential" has to take it too.
        leftover = store.root / f".config.json.{os.getpid()}.deadbeef.tmp"
        leftover.write_text(json.dumps({"anthropic_api_key": KEY}), "utf-8")
        assert store.clear_config() == {} and not (store.root / "config.json").exists()
        assert not leftover.exists(), "clear_config left a temp file holding the key"
        assert store._list_dir(store.root, ".config.json.*.tmp") == []
        store.write_config({"anthropic_api_key": KEY})
        print("clear tmp  ", "config.json and every .config.json.*.tmp gone")

        # ── file permissions ───────────────────────────────────────────────
        mode = (store.root / "config.json").stat().st_mode & 0o777
        print("mode       ", oct(mode), "(0o600 on POSIX; Windows ignores chmod — see comment)")

        # ── shots: add / list / read / delete ──────────────────────────────
        assert store.list_shots() == []
        assert store.read_shot("20260807T000000000000-deadbeef") is None

        first = store.add_shot(b"\xff\xd8\xff-first-jpeg", "image/jpeg", {"result": {"a": 1}})
        assert first is not None
        assert set(first) == {"id", "created_at", "media_type", "size_bytes", "payload"}, first
        assert "data" not in first and "image" not in first, "no bytes in the index"
        second = store.add_shot(b"\x89PNG-second", "image/png; charset=binary", {"meta": {"b": 2}})
        assert second is not None and second["media_type"] == "image/png"

        listed = store.list_shots()
        assert [entry["id"] for entry in listed] == [second["id"], first["id"]], "newest first"
        assert listed[1]["payload"] == {"result": {"a": 1}}
        assert listed[0]["size_bytes"] == len(b"\x89PNG-second")
        index_text = (store.root / "history.json").read_text("utf-8")
        assert "first-jpeg" not in index_text, "image bytes are not in history.json"

        got = store.read_shot(first["id"])
        assert got == (b"\xff\xd8\xff-first-jpeg", "image/jpeg"), got
        assert store.read_shot(second["id"])[1] == "image/png"
        print("shots      ", len(listed), "entries;", first["id"], "->", got[1], f"{got[0][:4]!r}…")

        assert store.delete_shot(first["id"]) is True
        assert store.delete_shot(first["id"]) is False, "deleting twice is not an error"
        assert store.read_shot(first["id"]) is None
        assert [entry["id"] for entry in store.list_shots()] == [second["id"]]
        print("delete     ", "file and index entry both gone")

        # a lost index still yields the bytes, typed from the extension
        (store.root / "history.json").unlink()
        assert store.read_shot(second["id"]) == (b"\x89PNG-second", "image/png")
        assert store.list_shots() == []
        print("no index   ", "read_shot still works from the extension")

        # ── a payload that is not a mapping costs the payload, not the shot ─
        # It is the one field that comes straight from a response body, and
        # dict("abc") is a ValueError while dict(5) is a TypeError.
        for junk in ("abc", 5, [1, 2], None, object(), True):
            odd = store.add_shot(b"\xff\xd8\xff-junk-payload", "image/jpeg", junk)
            assert odd is not None, f"add_shot refused or raised on payload {junk!r}"
            assert odd["payload"] == {}, odd["payload"]
        assert store.add_shot(b"\xff\xd8\xff-ok", "image/jpeg", {"ok": 1})["payload"] == {"ok": 1}
        print("payload    ", "non-mapping payloads stored empty, nothing raised")

        # ── a lost index orphans nothing: the next write reconciles shots/ ──
        store.clear_shots()
        live = store.add_shot(b"\xff\xd8\xff-live", "image/jpeg", {})
        orphans = [store.root / "shots" / f"2026010{n}T000000000000-orphan.jpg" for n in range(3)]
        for orphan in orphans:
            orphan.write_bytes(b"\xff\xd8\xff-unreferenced")
        (store.root / "history.json").write_bytes(b"{ not json at all")  # the index is lost
        recovered = store.add_shot(b"\xff\xd8\xff-after", "image/jpeg", {})
        assert recovered is not None
        assert not any(orphan.exists() for orphan in orphans), "orphaned files survived"
        assert not (store.root / "shots" / f"{live['id']}.jpg").exists(), "the lost entry went too"
        remaining = sorted(path.name for path in (store.root / "shots").iterdir())
        assert remaining == [f"{recovered['id']}.jpg"], remaining
        print("reconcile  ", "3 orphans and 1 unindexed shot reclaimed;", len(remaining), "file left")

        # ── delete_shot / clear_shots report what actually happened ────────
        store.clear_shots()
        keeper = store.add_shot(b"\xff\xd8\xff-keeper", "image/jpeg", {})
        store._write_json = lambda path, value: False  # the index write fails
        try:
            assert store.delete_shot(keeper["id"]) is False, "delete_shot claimed a removal"
            assert store.clear_shots() == 0, "clear_shots counted rows it did not clear"
        finally:
            del store._write_json
        assert [entry["id"] for entry in store.list_shots()] == [keeper["id"]], "still listed"
        assert store.clear_shots() == 1, "and the honest path still counts"
        print("honest     ", "a failed index write is reported, not papered over")

        # ── eviction past HISTORY_CAP deletes the image files ──────────────
        store.clear_shots()
        ids = [
            store.add_shot(f"photo-{n}".encode(), "image/jpeg", {"n": n})["id"]
            for n in range(HISTORY_CAP + 5)
        ]
        kept = store.list_shots()
        assert len(kept) == HISTORY_CAP, len(kept)
        assert [entry["id"] for entry in kept] == list(reversed(ids[-HISTORY_CAP:]))
        for gone in ids[:5]:
            assert store.read_shot(gone) is None, gone
        files = sorted(path.name for path in (store.root / "shots").iterdir())
        assert len(files) == HISTORY_CAP, f"evicted image files still on disk: {len(files)}"
        assert not any(gone in name for gone in ids[:5] for name in files)
        print("evict      ", f"added {len(ids)}, kept {len(kept)}, files on disk {len(files)}")

        # ── path traversal is refused, every spelling ──────────────────────
        # The secret the traversal is reaching for, and a decoy inside shots/.
        (store.root / "config.json").write_text('{"anthropic_api_key": "sk-DO-NOT-LEAK"}', "utf-8")
        outside = workdir / "outside.jpg"
        outside.write_bytes(b"not yours")

        attacks = [
            "..",
            ".",
            "",
            "../config",
            "../config.json",
            "..\\config.json",
            "../../.env",
            "....//config",
            "shots/../config",
            "/etc/passwd",
            "C:\\Windows\\win.ini",
            "\\\\server\\share\\x",
            "%2e%2e%2fconfig",          # as sent
            "../config\x00.jpg",         # decoded %00
            "sub/child",
            "id.with.dot",
            "id with space",
            "id~tilde",
            "*",
            "id\nX-Injected",
            "trailing-newline\n",        # "$" also matches just before this one
            "trailing-crlf\r\n",
            "\ntrailing-newline",
            "\u002e\u002e/config",
            "\uff0e\uff0e/config",       # fullwidth dots
            "NUL",
            "con",
            "COM1",
            "a" * 65,
            None,
            123,
        ]
        for attack in attacks:
            assert store.read_shot(attack) is None, f"read_shot accepted {attack!r}"
            assert store.delete_shot(attack) is False, f"delete_shot accepted {attack!r}"
        assert (store.root / "config.json").exists(), "traversal deleted config.json!"
        assert outside.exists(), "traversal deleted a file outside the data dir!"
        assert len(list((store.root / "shots").iterdir())) == HISTORY_CAP, "shots/ was disturbed"
        print("traversal  ", len(attacks), "attempts, all refused, nothing outside touched")

        # the id we actually issue passes the same gate — and nothing appended
        # to it does, which is the whole point of \Z over $.
        assert _valid_id(ids[-1]) and store.read_shot(ids[-1]) is not None
        assert not _valid_id(ids[-1] + "\n"), "an id with a trailing newline passed"
        assert not _valid_id(ids[-1] + "\r\n") and not _valid_id("\n" + ids[-1])
        assert ids == sorted(ids), "ids sort chronologically"
        print("newline id ", "refused; a valid id plus \\n is not a valid id")

        # ── clearing ───────────────────────────────────────────────────────
        # Everything in shots/ goes, not just the files: a subdirectory was
        # previously skipped and could never be cleared through the UI at all.
        (store.root / "shots" / "leftover").mkdir()
        (store.root / "shots" / "leftover" / "photo.jpg").write_bytes(b"\xff\xd8\xff-nested")
        (store.root / "shots" / ".partial.jpg.999.abcdef.tmp").write_bytes(b"\xff\xd8\xff-half")
        cleared = store.clear_shots()
        assert cleared == HISTORY_CAP and store.list_shots() == []
        assert list((store.root / "shots").iterdir()) == []
        assert store.clear_config() == {} and store.read_config() == {}
        assert not (store.root / "config.json").exists()
        print("clear      ", cleared, "shots removed; config file deleted")

        # ── a store on a path that does not exist yet ──────────────────────
        fresh = Store(workdir / "nested" / "deeper" / "data")
        assert fresh.read_config() == {} and fresh.list_shots() == []
        assert fresh.write_config({"provider": "openai"}) == {"provider": "openai"}
        os.environ[DATA_DIR_ENV] = str(workdir / "from-env")
        try:
            assert Store().root == workdir / "from-env"
        finally:
            os.environ.pop(DATA_DIR_ENV, None)
        print("roots      ", "explicit, nested, and RIL_DATA_DIR all resolve")

        # ── a data directory the OS cannot express ─────────────────────────
        # Path() raises ValueError on an embedded NUL and expanduser() raises
        # RuntimeError when a leading ~ has no HOME/USERPROFILE to resolve
        # against. The constructor runs on the server's startup path, so both
        # fall back to the default directory instead of stopping the boot.
        # (The default is redirected here so the check does not create one.)
        real_default = DEFAULT_DATA_DIR
        globals()["DEFAULT_DATA_DIR"] = workdir / "fallback"
        try:
            # (A NUL cannot go through os.environ at all, so the explicit
            # argument is the only way to reach the same guard from here.)
            assert Store("bad\x00dir").root == workdir / "fallback"
            assert Store("bad\x00dir").write_config({"provider": "claude"}) == {"provider": "claude"}

            # No HOME and no USERPROFILE: expanduser raises RuntimeError on
            # Windows, while POSIX still finds the passwd entry. Either answer
            # is fine — what matters is that the constructor returns a store.
            homeless = {
                name: os.environ.pop(name)
                for name in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
                if name in os.environ
            }
            try:
                resolved = Store("~/ril-no-home-check").root
            finally:
                os.environ.update(homeless)
            assert resolved == workdir / "fallback" or "ril-no-home-check" in str(resolved)
            if resolved != workdir / "fallback":
                shutil.rmtree(resolved, ignore_errors=True)  # POSIX resolved it after all
        finally:
            os.environ.pop(DATA_DIR_ENV, None)
            globals()["DEFAULT_DATA_DIR"] = real_default
        print("bad root   ", "NUL and an unresolvable ~ both yield a working store")

        print("self-check ok")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
