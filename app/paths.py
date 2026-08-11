"""Where the code's own files are, and where the user's files go.

Two questions that had the same answer for as long as this app was a directory
of .py files on someone's disk: both were derived from __file__, so both landed
one level above app/. A PyInstaller build breaks that in two different ways,
and they need opposite fixes.

  * Read-only files that ship WITH the code (web/) are unpacked somewhere that
    has nothing to do with __file__ — a temporary directory under onefile,
    _internal/ beside the executable under onedir. sys._MEIPASS is the only
    thing that knows which. That is resource().

  * The writable directory (data/: the API key the user pasted into the
    settings sheet, and every photo they have analysed) must NOT be that same
    place. Under onefile the bundle is extracted to a temp directory and
    DELETED when the process exits, so a data/ derived from __file__ inside a
    frozen build would take the key and the whole history with it on every
    quit — silently, and looking exactly like "it forgot my key again". That is
    data_dir(), which resolves next to the executable instead.

So the two only coincide in a source checkout, which is precisely the case that
must not change: resource("web") is <project>/web and data_dir() is
<project>/data, exactly as the expressions they replaced produced.

Everything here reads sys and os.environ at CALL time rather than caching it at
import, because that is what lets the self-check at the bottom exercise all
four layouts — source, onefile, onedir, macOS .app — from one interpreter.
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
from pathlib import Path

log = logging.getLogger("locator.paths")

# The one name a user or a container sets to put the data somewhere else. It
# lives here rather than in app/store.py because it is a question about paths
# and the two modules have to agree on the spelling; store.py imports it from
# here, so `from app.store import DATA_DIR_ENV` keeps working as it always did.
DATA_DIR_ENV = "RIL_DATA_DIR"

# The per-user directory a packaged build falls back to when it cannot write
# beside itself. Named after the repository and the Release asset, so someone
# who stumbles on it can tell what put it there.
APP_DIR_NAME = "photo-locator"

# <project>/, from app/paths.py -> app -> project root. Meaningless in a frozen
# build (app/ is inside the bundle there) and never used in one.
_SOURCE_ROOT = Path(__file__).resolve().parent.parent


def _frozen() -> bool:
    """Is this process a PyInstaller build?

    Both attributes, not either. PyInstaller sets sys.frozen AND sys._MEIPASS;
    cx_Freeze and py2exe set only sys.frozen and have no _MEIPASS for
    resource() to read. We ship PyInstaller builds and nothing else, so
    demanding both means an unexpected freezer degrades to the source layout
    instead of to an AttributeError halfway down a path that does not exist.
    """
    return bool(getattr(sys, "frozen", False)) and getattr(sys, "_MEIPASS", None) is not None


# The answer for this process, for callers that just want to branch on it.
# Nothing inside this module reads it — see the note about call time above.
FROZEN: bool = _frozen()


def resource(*parts: str | os.PathLike[str]) -> Path:
    """A read-only file that ships with the code: web/, and anything else the
    build adds to the bundle.

    Source checkout: <project>/<parts>, byte for byte what
    Path(__file__).resolve().parent.parent / ... returned before. Frozen: the
    same relative path under sys._MEIPASS, which is where PyInstaller's
    --add-data puts it. Never for anything that gets written — see data_dir().
    """
    if not _frozen():
        return _SOURCE_ROOT.joinpath(*parts)
    # Deliberately not .resolve(): the bootloader already hands over an
    # absolute path, and resolving it on macOS rewrites /var/... to
    # /private/var/..., so our paths would stop matching the ones PyInstaller
    # itself prints in a traceback.
    return Path(str(getattr(sys, "_MEIPASS", ""))).joinpath(*parts)


# Resolved once per process. Not for speed: the answer involves creating a
# directory and probing it, and a data directory that could change under a
# running server is a class of bug nobody would enjoy.
_DATA_DIR: Path | None = None


def data_dir() -> Path:
    """The writable directory: config.json, history.json, shots/.

    Logged the first time it is worked out, because "where did my API key go"
    is the question this module exists to make answerable, and in a packaged
    build the answer is not guessable from anything the user can see.
    """
    global _DATA_DIR
    if _DATA_DIR is None:
        _DATA_DIR, why = _resolve_data_dir()
        log.info("data directory %s (%s)", _DATA_DIR, why)
    return _DATA_DIR


def _resolve_data_dir() -> tuple[Path, str]:
    """The directory, and the one-phrase reason, for the log line."""
    override = _env_data_dir()
    if override is not None:
        # No writability probe on this branch, on purpose. The user named this
        # directory; sending their data somewhere else because a probe failed
        # would be the app quietly ignoring an explicit instruction. A write
        # that then fails is reported by store.py rather than swallowed.
        return override, f"from {DATA_DIR_ENV}"

    if not _frozen():
        # A source checkout keeps the layout it always had: <project>/data,
        # next to .env — same machine, same trust boundary, same secrets. No
        # probe and no mkdir here either; this used to be a plain expression
        # evaluated at import, and anything with a side effect would be a
        # change in behaviour for every existing user.
        return _SOURCE_ROOT / "data", "source checkout"

    return _frozen_data_dir()


def _env_data_dir() -> Path | None:
    """RIL_DATA_DIR, if it is set to something the OS can express.

    An unusable value is dropped rather than returned, because this result also
    becomes store.DEFAULT_DATA_DIR — the very thing store.Store falls back TO
    when the environment is bad. Handing the broken path back would make that
    fallback land on the same broken path.
    """
    raw = (os.getenv(DATA_DIR_ENV) or "").strip()
    if not raw:
        return None
    try:
        candidate = Path(raw).expanduser()
        if "\x00" in str(candidate):
            # CPython lets a NUL through Path() and only rejects it at the
            # first syscall — which would be a mkdir in the middle of a write.
            raise ValueError(f"NUL byte in {DATA_DIR_ENV}")
        return candidate
    except (ValueError, RuntimeError, OSError):
        # RuntimeError is expanduser() with a leading "~" it cannot resolve
        # because neither HOME nor USERPROFILE is set — ordinary inside a
        # stripped-down container. The value itself is not logged: it may have
        # come out of .env.
        log.warning("%s is not a usable path — ignoring it", DATA_DIR_ENV)
        return None


def _frozen_data_dir() -> tuple[Path, str]:
    """Where a packaged build keeps the user's files.

    Beside the executable, "portable" style. Someone who unzipped a folder and
    double-clicked what was inside expects their data to be in that folder, and
    it makes the whole thing one gesture to move, back up, or delete. Never
    sys._MEIPASS, which under onefile is a temporary extraction directory the
    process removes on the way out.

    Three situations where beside-the-executable is the wrong answer, all
    detected rather than assumed, and all falling back to the platform's
    per-user location:

      * a macOS .app — sys.executable is inside Contents/MacOS/, i.e. inside
        the bundle the user drags around. Writing there invalidates the
        signature, is lost when they replace the app, and fails outright if the
        bundle sits on a read-only volume or in /Applications.
      * an unzip into Program Files, /opt, or anywhere else the user does not
        own — the directory simply is not writable, and discovering that at the
        first save means the key they just typed is gone.
      * a run from inside a temporary directory. Windows Explorer lets people
        double-click the .exe inside a zip preview, which extracts it under
        %TEMP% and runs it from there — a perfectly writable directory that the
        OS then cleans out, taking the API key and photo history with it. The
        exact data-loss the portable layout exists to prevent, through a
        different door.
    """
    exe_dir = Path(sys.executable).resolve().parent

    if _in_macos_app_bundle(exe_dir):
        return _user_data_dir(), "inside a macOS .app — kept outside the bundle"

    if _in_temp_dir(exe_dir):
        fallback = _user_data_dir()
        log.warning(
            "running from a temporary folder (%s) — keeping data in %s so it "
            "survives cleanup. Unpack the archive properly to get the portable "
            "layout.",
            exe_dir,
            fallback,
        )
        return fallback, "run from a temporary folder"

    beside = exe_dir / "data"
    if _writable(beside):
        return beside, "next to the executable"

    # If the per-user location is unwritable too there is nowhere left to go.
    # Return it anyway: store.py reports a failed write, which a user can act
    # on, where an exception here would stop the app booting at all.
    fallback = _user_data_dir()
    log.warning("cannot write to %s — using %s instead", beside, fallback)
    return fallback, "beside the executable is not writable"


def _in_temp_dir(exe_dir: Path) -> bool:
    """Is this executable running from inside the OS temp directory?

    tempfile.gettempdir() answers per platform (%TEMP%, $TMPDIR, /tmp) with the
    same environment overrides the OS itself honours. Compared case-insensitively
    on Windows via Path equality of resolved paths — is_relative_to does the
    right thing once both sides are resolved. A false positive costs a per-user
    data directory rather than a key that evaporates with the next temp sweep.
    """
    import tempfile

    try:
        temp_root = Path(tempfile.gettempdir()).resolve()
    except (OSError, ValueError):
        return False
    return exe_dir == temp_root or exe_dir.is_relative_to(temp_root)


def _in_macos_app_bundle(exe_dir: Path) -> bool:
    """Is this executable inside Foo.app/Contents/MacOS/ ?

    The shape is the test, not sys.platform. It is the layout Apple defines and
    nothing else produces it; it is what the self-check can exercise from any
    host; and a false positive costs a per-user data directory rather than a
    lost key.
    """
    parts = exe_dir.parts
    return (
        len(parts) >= 3
        and parts[-1] == "MacOS"
        and parts[-2] == "Contents"
        and parts[-3].endswith(".app")
    )


def _user_data_dir() -> Path:
    """The platform's per-user place for application data.

    One directory, not <dir>/data: this IS the data directory, and a nested
    data/ would only read as a mistake to whoever went looking for it.
    """
    try:
        home = Path.home()
    except (RuntimeError, OSError):
        # No HOME, no USERPROFILE, no passwd entry — a stripped-down container.
        # Nothing persistent is left to prefer, so this becomes relative to the
        # working directory, and the log line above says where it went.
        home = Path()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_DIR_NAME
    if os.name == "nt":
        # LOCALAPPDATA rather than APPDATA: this is machine-local state, not
        # something that should follow a roaming profile across the network —
        # it holds an API key and up to twenty full-size photos.
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        return (Path(base) if base else home / "AppData" / "Local") / APP_DIR_NAME
    return Path(os.getenv("XDG_DATA_HOME") or home / ".local" / "share") / APP_DIR_NAME


def _writable(directory: Path) -> bool:
    """Can we really create this directory and write in it?

    Answered by doing it, not by inspecting permissions: os.access lies on
    Windows, where it reports the read-only attribute rather than the ACL that
    actually decides — and an unzip into Program Files is exactly the case this
    has to catch. Creating the directory is the point rather than a side
    effect; a packaged build's data/ has to appear on first run anyway.
    """
    probe = directory / f".ril-write-probe-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # O_EXCL so a leftover from another process is never adopted, and the
        # descriptor is closed before the unlink below because Windows will not
        # delete a file that is still open.
        os.close(os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        return True
    except (OSError, ValueError):
        return False
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            # Creatable but not removable is odd and harmless: the name carries
            # our pid and four random bytes, so it collides with nothing.
            log.debug("could not remove the write probe in %s", directory)


if __name__ == "__main__":
    # Self-check: python -m app.paths
    #
    # The three frozen layouts are simulated by setting sys.frozen,
    # sys._MEIPASS and sys.executable — which is exactly what PyInstaller's
    # bootloader does — rather than by actually building one. That is the only
    # way to exercise Windows, Linux and macOS packaging from one interpreter
    # on one machine, and it is why nothing above caches what it reads.
    import shutil
    import tempfile
    from contextlib import contextmanager

    failures: list[str] = []

    def check(ok: bool, label: str, detail: str = "") -> None:
        print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(label)

    # The log line data_dir() promises is a behaviour under test, so it is
    # captured rather than printed: a user who cannot find their config has
    # only this line to go on.
    lines: list[str] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(record.getMessage())

    log.addHandler(_Collect())
    log.setLevel(logging.INFO)  # INFO is what a user's log shows; debug is noise here
    log.propagate = False  # the simulated failures below log on purpose

    _MISSING = object()

    def _set(name: str, value: object) -> None:
        if value is _MISSING:
            if hasattr(sys, name):
                delattr(sys, name)
        else:
            setattr(sys, name, value)

    def _set_env(key: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)

    @contextmanager
    def simulate(executable: object = None, meipass: object = None, **env: str | None):
        """Run a block as if the process were something other than this one.

        meipass=None means "not frozen". Keyword arguments patch os.environ,
        with None meaning "unset". Everything is restored afterwards, including
        the cached data directory — otherwise the first scenario's answer would
        be handed to all of them.
        """
        saved_sys = {name: getattr(sys, name, _MISSING) for name in ("frozen", "_MEIPASS", "executable")}
        saved_env = {key: os.environ.get(key) for key in env}
        try:
            _set("frozen", True if meipass is not None else _MISSING)
            _set("_MEIPASS", str(meipass) if meipass is not None else _MISSING)
            if executable is not None:
                _set("executable", str(executable))
            for key, value in env.items():
                _set_env(key, value)
            lines.clear()
            globals()["_DATA_DIR"] = None
            yield
        finally:
            for name, value in saved_sys.items():
                _set(name, value)
            for key, value in saved_env.items():
                _set_env(key, value)
            globals()["_DATA_DIR"] = None

    workdir = Path(tempfile.mkdtemp(prefix="ril-paths-"))
    # The scenario directories live under the REAL temp dir (that is what
    # mkdtemp gives), which would trip the run-from-a-temp-folder divert in
    # every frozen scenario. So the check installs its own notion of "the temp
    # directory" — a subdirectory none of the scenario paths are under — via
    # tempfile.tempdir, the documented override gettempdir() consults first.
    # Restored in the finally below, because this is process-global state.
    fake_temp = workdir / "fake-temp"
    fake_temp.mkdir()
    _real_tempdir = tempfile.tempdir
    tempfile.tempdir = str(fake_temp)
    # Every per-user fallback is redirected in here, so the check never creates
    # a directory in the real ~/Library, %LOCALAPPDATA% or ~/.local/share.
    fake_home = workdir / "home"
    (fake_home / "AppData" / "Local").mkdir(parents=True)
    HOME_ENV: dict[str, str | None] = {
        "HOME": str(fake_home),
        "USERPROFILE": str(fake_home),
        "LOCALAPPDATA": str(fake_home / "AppData" / "Local"),
        "APPDATA": str(fake_home / "AppData" / "Roaming"),
        "XDG_DATA_HOME": str(fake_home / ".local" / "share"),
    }

    def under(child: Path, parent: Path) -> bool:
        return child == parent or parent in child.parents

    try:
        # ── 1. source checkout: today's behaviour, byte for byte ───────────
        old_web = Path(__file__).resolve().parent.parent / "web"
        old_data = Path(__file__).resolve().parent.parent / "data"
        with simulate(**{DATA_DIR_ENV: None}):
            check(not _frozen() and FROZEN is False, "not frozen", "plain interpreter")
            check(resource("web") == old_web, "resource('web') is <project>/web", str(old_web))
            resolved = data_dir()
            check(resolved == old_data, "data_dir() is <project>/data", str(resolved))
            check(resolved is data_dir(), "resolved once and cached", "same object on the second call")
            check(len(lines) == 1 and str(resolved) in lines[0], "logged once at startup", lines[0])
            check(
                resource("web", "index.html") == old_web / "index.html"
                and resource() == old_web.parent,
                "resource() joins parts and accepts none",
            )

        # The wiring, from the other side: this is the constant the store
        # actually uses, and a checkout must still see <project>/data.
        #
        # Imported here rather than at the top of the file for two reasons.
        # app.store imports app.paths, and under `python -m app.paths` this
        # file is __main__ — so the import below loads a second, independent
        # copy of this module, which resolves its own data directory as it
        # goes. That copy must therefore be created inside a clean simulated
        # environment, or an RIL_DATA_DIR set in this shell would decide the
        # answer being asserted.
        with simulate(**{DATA_DIR_ENV: None}):
            from app.store import DEFAULT_DATA_DIR

            check(DEFAULT_DATA_DIR == old_data, "store.DEFAULT_DATA_DIR unchanged", str(DEFAULT_DATA_DIR))

        # ── 2. PyInstaller onefile ─────────────────────────────────────────
        # _MEIPASS is a temp extraction directory that the process deletes on
        # exit. Reading from it is right; writing the user's key into it is the
        # bug this module exists to prevent.
        unpacked = workdir / "onefile"
        meipass = workdir / "_MEI123456"
        meipass.mkdir(parents=True)
        with simulate(unpacked / "photo-locator.exe", meipass, **{DATA_DIR_ENV: None}):
            check(_frozen(), "onefile: detected as frozen", "sys.frozen + sys._MEIPASS")
            check(resource("web") == meipass / "web", "onefile: web/ read from _MEIPASS", str(meipass / "web"))
            resolved = data_dir()
            check(resolved == unpacked / "data", "onefile: data next to the .exe", str(resolved))
            check(not under(resolved, meipass), "onefile: data is NOT in _MEIPASS", "the temp dir is deleted on exit")
            check(resolved.is_dir(), "onefile: the directory exists after resolving")
            check(list(resolved.iterdir()) == [], "onefile: the write probe cleaned up after itself")
            check(len(lines) == 1 and str(resolved) in lines[0], "onefile: logged once", lines[0])

        # ── 3. PyInstaller onedir ──────────────────────────────────────────
        # The user unzips one folder: the executable at the top, the bundle in
        # _internal/ beside it, and data/ arriving next to both on first run.
        onedir = workdir / "onedir"
        internal = onedir / "_internal"
        internal.mkdir(parents=True)
        with simulate(onedir / "photo-locator.exe", internal, **{DATA_DIR_ENV: None}):
            check(resource("web") == internal / "web", "onedir: web/ read from _internal", str(internal / "web"))
            resolved = data_dir()
            check(resolved == onedir / "data", "onedir: data next to the .exe", str(resolved))
            check(not under(resolved, internal), "onedir: data is NOT in the bundle dir")

        # ── 4. macOS .app bundle ───────────────────────────────────────────
        # sys.executable is inside the bundle the user drags into
        # /Applications, so data must go to ~/Library/Application Support.
        bundle = workdir / "Photo Locator.app"
        macos = bundle / "Contents" / "MacOS"
        frameworks = bundle / "Contents" / "Frameworks"
        frameworks.mkdir(parents=True)
        macos.mkdir(parents=True)
        with simulate(macos / "photo-locator", frameworks, **{DATA_DIR_ENV: None}, **HOME_ENV):
            check(_in_macos_app_bundle(macos), ".app: Contents/MacOS detected", str(macos))
            check(resource("web") == frameworks / "web", ".app: web/ still read from the bundle")
            resolved = data_dir()
            check(not under(resolved, bundle), ".app: data is NOT inside the .app", str(resolved))
            check(under(resolved, fake_home), ".app: data is in the per-user location")
            check(resolved.name == APP_DIR_NAME, ".app: named after the app", resolved.name)
            check(len(lines) == 1 and str(resolved) in lines[0], ".app: logged once", lines[0])

        # ── 5. frozen, and the directory beside the .exe is not writable ───
        # An unzip into Program Files. Simulated with a plain file standing
        # where the executable's directory should be, so every mkdir under it
        # fails the way a denied ACL does.
        blocker = workdir / "program-files"
        blocker.write_bytes(b"not a directory")
        with simulate(blocker / "photo-locator.exe", meipass, **{DATA_DIR_ENV: None}, **HOME_ENV):
            resolved = data_dir()
            check(under(resolved, fake_home), "unwritable: fell back to the per-user dir", str(resolved))
            check(any("cannot write" in line for line in lines), "unwritable: said so in the log")
            check(len(lines) == 2, "unwritable: one warning plus the one data line", " | ".join(lines))

        # ── 5b. frozen, run from inside the temp directory ─────────────────
        # Explorer runs a double-clicked .exe straight out of a zip preview by
        # extracting it under %TEMP% — writable, and periodically wiped. Data
        # beside the executable there evaporates; it must divert to the
        # per-user location and say so.
        in_temp = fake_temp / "Temp1_photo-locator.zip"
        in_temp.mkdir(parents=True)
        with simulate(in_temp / "photo-locator.exe", meipass, **{DATA_DIR_ENV: None}, **HOME_ENV):
            resolved = data_dir()
            check(under(resolved, fake_home), "temp run: diverted to the per-user dir", str(resolved))
            check(not under(resolved, fake_temp), "temp run: nothing written under the temp dir")
            check(
                any("temporary folder" in line for line in lines),
                "temp run: warned, naming the reason",
                " | ".join(lines),
            )

        # ── 6. RIL_DATA_DIR wins, frozen or not ────────────────────────────
        chosen = workdir / "chosen"
        for label, exe, mei in (
            ("source", None, None),
            ("onefile", unpacked / "photo-locator.exe", meipass),
            (".app", macos / "photo-locator", frameworks),
        ):
            with simulate(exe, mei, **{DATA_DIR_ENV: str(chosen)}, **HOME_ENV):
                resolved = data_dir()
                check(resolved == chosen, f"{label}: {DATA_DIR_ENV} wins", str(resolved))
                check(not resolved.exists(), f"{label}: an override is not probed or created")
                check(DATA_DIR_ENV in lines[0], f"{label}: the log names the override", lines[0])

        # A value the OS cannot express is dropped, not returned: it would
        # otherwise become the directory store.Store falls back TO.
        with simulate(**{DATA_DIR_ENV: "  "}):
            check(data_dir() == old_data, "blank override is ignored", str(old_data))
        homeless: dict[str, str | None] = dict.fromkeys(
            ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "XDG_DATA_HOME", "LOCALAPPDATA", "APPDATA")
        )
        with simulate(**{DATA_DIR_ENV: "~/ril-unresolvable"}, **homeless):
            resolved = data_dir()
            # Windows raises RuntimeError out of expanduser and we fall back;
            # POSIX still finds the passwd entry and resolves it. Either is
            # fine — what must not happen is a literal "~" reaching the store.
            check(
                resolved == old_data or (resolved.is_absolute() and "~" not in str(resolved)),
                "an unresolvable ~ never reaches the store",
                str(resolved),
            )
            check(not resolved.exists() or resolved == old_data, "and nothing was created for it")

        # ── 7. sys.frozen without _MEIPASS is not our kind of frozen ───────
        with simulate(**{DATA_DIR_ENV: None}):
            _set("frozen", True)
            check(not _frozen(), "sys.frozen alone is not enough", "no _MEIPASS to read from")
            check(data_dir() == old_data, "and it degrades to the source layout")

        print()
        if failures:
            print(f"{len(failures)} FAILURE(S): " + "; ".join(failures))
            raise SystemExit(1)
        print("self-check ok")
    finally:
        tempfile.tempdir = _real_tempdir
        shutil.rmtree(workdir, ignore_errors=True)
