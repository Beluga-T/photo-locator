# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the downloadable build: one file, no Python, no pip.

    python -m pip install -r requirements.txt -r requirements-build.txt
    python -m PyInstaller --clean --noconfirm photo-locator.spec

The product is a single console executable per platform, built by CI and
attached to the GitHub Release. Someone downloads it, unzips it, double-clicks
it, and the app is running -- they install nothing, and they never see a
terminal unless they want to. launch.py is what runs inside it.

Three things in here are load-bearing, and each of them fails *silently* if it
is got wrong, which is why they are written out rather than left to a default:

  datas            web/ is not Python, so nothing in the module graph points at
                   it. Left out, the server starts perfectly and answers 404 for
                   every page. Collected by walking the directory below, so a
                   file added to web/fonts/ or web/vendor/ is in the next build
                   without anyone remembering this file exists.

  hiddenimports    uvicorn resolves its protocol, lifespan and loop classes from
                   *strings* at startup (uvicorn/config.py), so no module graph
                   contains them. PyInstaller's bundled hooks happen to cover
                   that today; the list below is written out anyway, and says
                   why -- see the note above it.

  console=True     the console window is the only feedback channel this app has
                   and the only way to stop it. A windowed build would leave a
                   double-clicking user with no output, no error and no way out
                   short of Task Manager.

Not signed. The owner accepted the consequence: the first run on Windows shows
a SmartScreen panel that hides the button behind "More info -> Run anyway", and
macOS needs a right-click -> Open. Signing is a certificate purchase and a
notarisation step, not a change to this file.

macOS deliberately produces a plain Unix executable and NOT a .app bundle.
A .app would hide the console -- so the user would get no output, no error text
and no way to stop the app -- and it would put the portable data directory
inside Photo Locator.app/Contents/MacOS/, where the next drag-and-drop upgrade
throws the user's API key and history away with the old copy. A bare binary
next to its data folder is the honest shape for this program.
"""

import os
from pathlib import Path

# SPECPATH is injected by PyInstaller and is the directory holding this file --
# the repository root. Deriving everything from it keeps the spec working from
# any working directory, which matters because CI builds with --workpath and
# --distpath pointing somewhere else entirely.
PROJECT_ROOT = Path(SPECPATH).resolve()

APP_NAME = "photo-locator"
ENTRY_POINT = PROJECT_ROOT / "launch.py"
WEB_ROOT = PROJECT_ROOT / "web"

# Files that a checkout picks up from the operating system and that have no
# business inside a release artefact.
JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def web_datas():
    """Every file under web/, as PyInstaller (source, destination) pairs.

    A walk rather than the one-line ``('web', 'web')``, because this is the part
    that breaks quietly. It fails the build with a sentence if web/ is missing
    or has lost a subdirectory, and it prints what it collected so that a CI log
    shows the file count of the thing that was actually shipped.

    web/fonts/ and web/vendor/ are checked by name: they are the two the page
    cannot do without and the two most likely to be absent -- fonts and a
    vendored library are exactly what an over-eager .gitignore rule or a
    shallow, filtered checkout drops, and neither leaves any trace in the
    Python module graph to notice it by.
    """
    if not WEB_ROOT.is_dir():
        raise SystemExit(
            "photo-locator.spec: {0} does not exist.\n"
            "Build from a complete checkout -- the frontend is not optional."
            .format(WEB_ROOT)
        )

    collected = []
    for folder, dirnames, filenames in os.walk(WEB_ROOT):
        dirnames[:] = [name for name in dirnames if name != "__pycache__"]
        for filename in sorted(filenames):
            if filename in JUNK_NAMES:
                continue
            source = Path(folder) / filename
            # Destination is a *directory* relative to the bundle root, and
            # PyInstaller wants it in posix form on every platform.
            destination = (Path("web") / source.parent.relative_to(WEB_ROOT)).as_posix()
            collected.append((str(source), destination))

    required = ["index.html", "app.js", "styles.css"]
    missing = [name for name in required if not (WEB_ROOT / name).is_file()]
    if missing:
        raise SystemExit(
            "photo-locator.spec: web/ is missing {0}.".format(", ".join(missing))
        )
    for subdirectory in ("fonts", "vendor"):
        if not any(dest.startswith("web/" + subdirectory) for _src, dest in collected):
            raise SystemExit(
                "photo-locator.spec: web/{0}/ is empty or missing. The page "
                "loads it, so a build without it is broken.".format(subdirectory)
            )

    print("photo-locator.spec: bundling {0} files from web/".format(len(collected)))
    for destination in sorted({dest for _source, dest in collected}):
        names = sorted(Path(src).name for src, dest in collected if dest == destination)
        print("    {0:<12} {1}".format(destination, " ".join(names)))
    return collected


# --- what static analysis cannot see --------------------------------------
#
# Every entry here was checked by building the executable WITHOUT this list and
# running it, and the honest result is that all of them are currently redundant:
# pyinstaller-hooks-contrib ships hook-uvicorn.py, which is one line of
# collect_submodules('uvicorn'), and the anthropic and starlette imports below
# turn out to be reachable by static analysis after all -- they sit inside
# function bodies and try blocks, which modulegraph does follow.
#
# The list stays, for two reasons that are about the next person rather than
# about today's build. It is the written-down contract that these particular
# import strings must resolve at startup, which is otherwise discoverable only
# by reading uvicorn's config module; and it is what survives the day that
# blanket collect_submodules hook is narrowed, or starlette changes how it
# reaches the multipart parser, or anthropic finishes making its resources lazy.
# Naming them costs nothing -- they are in the binary either way -- and a
# missing one turns into a build-log warning instead of a runtime crash on a
# stranger's machine.

HIDDEN_IMPORTS = [
    # uvicorn keeps its implementations in string tables (HTTP_PROTOCOLS,
    # LIFESPAN, LOOP_FACTORIES in uvicorn/config.py) and calls importlib on the
    # chosen entry at startup. Nothing anywhere imports these by name.
    "uvicorn.protocols.http.auto",           # HTTP_PROTOCOLS["auto"]: what launch.py asks for
    "uvicorn.protocols.http.h11_impl",       # what auto uses when httptools is absent
    "uvicorn.protocols.http.httptools_impl", # what auto prefers when it is present
    "uvicorn.lifespan.on",                   # LIFESPAN["auto"]: runs @app.on_event("startup")
    "uvicorn.loops.asyncio",                 # LOOP_FACTORIES["asyncio"]: pinned in launch.py
    # Not what launch.py selects, but it is uvicorn's own default and it costs a
    # kilobyte: any other entry point into this bundle (a future flag, a Config
    # built somewhere else) gets a working server instead of a crash, and with
    # uvloop excluded it simply resolves to the asyncio factory above.
    "uvicorn.loops.auto",

    # starlette reaches the multipart parser through a try/except ladder that
    # tries `python_multipart` first and the legacy `multipart` alias second
    # (starlette/formparsers.py). The upload route is the entire point of this
    # app, and without the parser every POST /api/locate fails while the rest of
    # the site works perfectly -- the most confusing failure in this list.
    "python_multipart",
    "python_multipart.multipart",

    # anthropic reaches its resource modules two ways: anthropic/_client.py has
    # `from .resources.messages import Messages` inside a cached_property body,
    # and anthropic/_utils/_resources_proxy.py goes through
    # importlib.import_module("anthropic.resources"). Only the first is
    # analysable, so the package is named rather than left to depend on which
    # one PyInstaller happens to follow.
    "anthropic.resources",
    "anthropic.resources.messages",
]

# --- what nobody should have to download ----------------------------------

EXCLUDES = [
    # A GUI toolkit for an app whose only interface is a browser. tkinter drags
    # in the whole Tcl/Tk runtime, tens of megabytes of it, purely because
    # pillow ships an optional PIL.ImageTk bridge.
    "tkinter",
    "PIL.ImageTk",
    "PIL.ImageQt",

    # uvicorn[standard] installs watchfiles for --reload, and uvicorn/__init__.py
    # pulls the reloader in transitively. This build never reloads (launch.py
    # constructs Config directly and passes no reload flag), and watchfiles is a
    # compiled Rust extension of several megabytes.
    "watchfiles",

    # The other half of uvicorn[standard] that only exists on POSIX, so its
    # weight is invisible from a Windows build and lands entirely on the macOS
    # and Linux downloads. launch.py pins loop="asyncio" precisely so that all
    # three platforms run the same event loop; leaving uvloop in the bundle
    # would ship a compiled extension that is then never loaded.
    # uvicorn.loops.auto still works with it gone -- its `import uvloop` is in a
    # try block whose except branch is the asyncio factory.
    "uvloop",

    # Also from uvicorn[standard]: PyYAML exists only so that --log-config can
    # take a .yaml file. launch.py configures logging in Python.
    "yaml",
    "_yaml",

    # The app talks to the browser over Server-Sent Events and opens no
    # WebSocket -- launch.py passes ws="none", so uvicorn never resolves a
    # WebSocket class at all. Both of these are pulled in by uvicorn[standard]
    # and neither is reachable. If a WebSocket route is ever added, drop these
    # two lines, drop ws="none" in launch.py, and add
    # uvicorn.protocols.websockets.auto to HIDDEN_IMPORTS.
    "websockets",
    "wsproto",

    # The one pillow plugin worth removing, and it is worth a lot: PIL._avif is
    # an entire AV1 decoder, 7.9 MB of shared library, for a format
    # app/imaging.py does not accept (ACCEPTED_FORMATS: JPEG PNG WEBP GIF BMP
    # TIFF). Nothing reaches it except PIL's plugin auto-registration, which
    # PyInstaller's own hook-PIL.Image.py pulls in wholesale. Two builds
    # differing only in this line: 21.0 MiB with it, 16.8 MiB without -- a fifth
    # of the download, removed by one line.
    #
    # The cost is one sentence of error text: an AVIF upload is refused either
    # way, but with the plugin present the user is told "暂不支持 AVIF 格式" and
    # without it they get the vaguer "这个文件不是可识别的图片格式。". If AVIF
    # uploads ever become common enough for that to matter, delete this line and
    # the binary grows back.
    "PIL.AvifImagePlugin",

    # Not a dependency of anything here -- it arrives because PyInstaller itself
    # requires setuptools, and setuptools ships a distutils-precedence.pth that
    # runs at interpreter startup, so the analyser records it as an import of
    # the entry script. 130 modules of build tooling inside a runtime artefact,
    # about 1.2 MiB of the download.
    "setuptools",
    "_distutils_hack",
    "distutils",
    "pkg_resources",

    # Test and packaging machinery. None of it is installed by requirements.txt,
    # so these are here to stop a build machine's stray site-packages from
    # leaking into a release binary rather than to remove anything real.
    "pytest",
    "_pytest",
    "nose",
    "numpy",
    "IPython",
]

# The rest of pillow's format plugins stay. Six of them are required outright by
# ACCEPTED_FORMATS, and the others are what lets Image.open() *recognise* an
# upload it cannot use -- the difference between "暂不支持 PSD 格式，请上传 JPG、
# PNG 或 WebP。" and the unhelpful "这个文件不是可识别的图片格式。". Dropping all
# 38 of them was built and measured: 0.16 MiB off a 16.8 MiB binary, because
# pillow's real weight is _imaging, _webp and the codecs linked into them, and
# those stay whatever happens. AVIF above is the exception that proves the rule
# -- it went for its 7.9 MB decoder, not for being a plugin.


analysis = Analysis(
    [str(ENTRY_POINT)],
    pathex=[str(PROJECT_ROOT)],  # so `import app` resolves during analysis
    binaries=[],
    datas=web_datas(),
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    # Left alone on every platform. Stripping symbols saves a couple of
    # megabytes on Linux and has been known to break macOS binaries outright;
    # on an unsigned build that nobody can debug remotely, the symbols are worth
    # more than the megabytes.
    strip=False,
    # UPX is off on purpose, not just unavailable. A packed executable is one of
    # the strongest heuristics antivirus vendors have, and this binary is
    # already unsigned -- compressing it trades a few megabytes for a much
    # better chance that the first thing the user sees is a quarantine dialog.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # The window is the interface. See the module docstring.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # No icon: there is no .ico/.icns in the repository, and pointing at one
    # that does not exist fails the build. Add the files and set this when the
    # project has artwork.
    icon=None,
)
