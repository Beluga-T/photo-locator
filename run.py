#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One command from a fresh clone to a running app:

    python run.py

It creates .venv, installs requirements.txt into it, starts the server on
http://127.0.0.1:8000 and opens a browser there. There is nothing to configure
first -- click the gear in the page and paste your own Anthropic API key; it is
stored server-side in data/config.json, which is gitignored. A .env file works
too but is optional.

    python run.py --port 8010        use a different port
    python run.py --no-browser       do not open a browser
    python run.py --reload           restart on edits to app/ (development)
    python run.py --recreate-venv    throw .venv away and build it again

Standard library only, deliberately: this file runs *before* anything in
requirements.txt is installed, so it must not import fastapi, uvicorn, dotenv
or anything else from there.

It is also written in the subset of Python that Python 2 can still *parse* --
no f-strings, no annotations -- and it does the version check before importing
any Python-3-only module. On a machine where `python` is still Python 2, that
turns a SyntaxError into a sentence explaining what to install.
"""

from __future__ import print_function

import os
import sys

# --- The Python floor -----------------------------------------------------
# From the code, not from habit: app/store.py:44 has `from datetime import UTC`
# and app/store.py:140 calls `datetime.now(UTC)` on the request path. Python
# added `datetime.UTC` in 3.11, so 3.10 fails at import.
#
# Nothing in app/ needs more than that: there are no PEP 695 `type` aliases and
# no `def f[T]()`, and every module starts with `from __future__ import
# annotations`, so the `X | Y` annotations never get evaluated. The Dockerfile
# builds on python:3.12-slim, but that is the image's pin, not the code's
# requirement.
MIN_PYTHON = (3, 11)

_PY = sys.version_info[:2]


def _too_old():
    """Explain the version problem, in terms of what to install."""
    lines = [
        "",
        "This project needs Python {0}.{1} or newer.".format(*MIN_PYTHON),
        "You started it with Python {0}.{1} ({2}).".format(
            _PY[0], _PY[1], sys.executable or "unknown interpreter"
        ),
        "",
        "Why {0}.{1}: app/store.py does `from datetime import UTC`, and".format(
            *MIN_PYTHON
        ),
        "`datetime.UTC` does not exist in older versions.",
        "",
        "Install a newer Python, then start this script with it -- the virtual",
        "environment is built from whichever interpreter runs this file:",
        "",
        "  Windows   https://www.python.org/downloads/   then:  py -3 run.py",
        "  macOS     brew install python@3.12            then:  python3.12 run.py",
        "  Linux     sudo apt install python3.12 python3.12-venv",
        "            (or your distribution's equivalent)  then:  python3.12 run.py",
        "",
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(1)


if _PY < MIN_PYTHON:
    _too_old()

# Everything below this line may use Python 3 only. The imports are here, and
# not at the top, on purpose: `import urllib.request` is itself a failure on
# Python 2, and it would happen before the message above ever printed.
import argparse  # noqa: E402
import hashlib  # noqa: E402
import ipaddress  # noqa: E402
import shutil  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402
import webbrowser  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(HERE, ".venv")
REQUIREMENTS = os.path.join(HERE, "requirements.txt")

# Lives inside .venv, so it disappears with the environment it describes and
# git never sees it (.venv/ is ignored).
STAMP = os.path.join(VENV_DIR, ".requirements-stamp")

ASGI_APP = "app.main:app"
HEALTH_PATH = "/api/health"

# Import names, not distribution names: `pip install pillow` gives you `PIL`,
# and `python-multipart` gives you `multipart`. Checked with importlib rather
# than a real import, which would cost a second of fastapi startup.
IMPORT_NAMES = ["fastapi", "uvicorn", "anthropic", "httpx", "PIL", "multipart", "dotenv"]

DEBUG = bool(os.environ.get("RIL_RUN_DEBUG"))


class Failure(Exception):
    """A problem this script knows how to explain.

    Raised with a message meant for someone who just cloned the repository and
    does not know how it is built. It is printed as prose; the traceback is
    only shown when RIL_RUN_DEBUG is set.
    """


def say(text=""):
    print(text)
    sys.stdout.flush()


# --- venv -----------------------------------------------------------------


def venv_python(venv_dir):
    """The interpreter inside a virtual environment.

    The one real cross-platform difference in this file: CPython puts the
    scripts in Scripts\\ on Windows and bin/ everywhere else.
    """
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def looks_like_venv(venv_dir):
    """True for a directory that is a virtual environment, however broken.

    Guards the --recreate-venv delete: pyvenv.cfg exists in every venv Python
    has made since 3.3, and in almost nothing else.
    """
    return os.path.isfile(os.path.join(venv_dir, "pyvenv.cfg"))


def remove_venv():
    if not os.path.exists(VENV_DIR):
        return
    if not looks_like_venv(VENV_DIR):
        raise Failure(
            "Refusing to delete {0}: it has no pyvenv.cfg, so it is not a\n"
            "virtual environment this script made. Move it aside yourself and\n"
            "run this again.".format(VENV_DIR)
        )
    say("Removing {0} ...".format(VENV_DIR))
    try:
        shutil.rmtree(VENV_DIR)
    except OSError as exc:
        raise Failure(
            "Could not delete {0}: {1}\n\n"
            "Something is probably still using it -- close any running server\n"
            "or shell that has this environment activated, then try again.".format(
                VENV_DIR, exc
            )
        )


def create_venv():
    say("Creating a virtual environment in .venv (one time, a few seconds) ...")
    try:
        subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])
    except subprocess.CalledProcessError:
        raise Failure(
            "Could not create the virtual environment in {0}.\n\n"
            "On Debian and Ubuntu the venv module ships separately from Python:\n"
            "    sudo apt install python3-venv\n"
            "Otherwise check that you can write to this folder, then run this\n"
            "again.".format(VENV_DIR)
        )
    except OSError as exc:
        raise Failure(
            "Could not run {0} -m venv: {1}".format(sys.executable, exc)
        )
    if not os.path.isfile(venv_python(VENV_DIR)):
        raise Failure(
            "The virtual environment was created but has no interpreter at\n"
            "{0}.\n\n"
            "Delete .venv and try again:  python run.py --recreate-venv".format(
                venv_python(VENV_DIR)
            )
        )


def broken_venv_message(detail):
    return (
        ".venv exists but does not work: {0}\n\n"
        "That usually means it was interrupted while being built, or the\n"
        "project folder (or the Python that made it) was moved or deleted.\n"
        "A virtual environment is disposable -- rebuild it:\n\n"
        "    python run.py --recreate-venv\n\n"
        "Nothing of yours lives in .venv; your key and history are in data/."
    ).format(detail)


def ensure_venv(recreate):
    """Return the path to a usable interpreter inside .venv."""
    if recreate:
        remove_venv()

    if not os.path.exists(VENV_DIR):
        create_venv()
    elif not looks_like_venv(VENV_DIR):
        raise Failure(
            "{0} exists but is not a virtual environment (no pyvenv.cfg).\n"
            "Move it aside and run this again.".format(VENV_DIR)
        )

    python = venv_python(VENV_DIR)
    if not os.path.isfile(python):
        raise Failure(broken_venv_message("there is no interpreter at " + python))
    return python


# --- dependencies ---------------------------------------------------------


def requirements_fingerprint():
    """What the installed set is expected to match.

    The interpreter version is in here as well as the file: the same
    requirements.txt installed under a different Python is a different set of
    wheels, and if someone rebuilds .venv from another interpreter the stamp
    should stop matching.
    """
    try:
        with open(REQUIREMENTS, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise Failure(
            "Cannot read {0}: {1}\n\n"
            "Run this script from inside the cloned project.".format(REQUIREMENTS, exc)
        )
    digest = hashlib.sha256(raw).hexdigest()
    return "1|{0}.{1}|{2}".format(_PY[0], _PY[1], digest)


def read_stamp():
    try:
        with open(STAMP, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def write_stamp(value):
    try:
        with open(STAMP, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
    except OSError:
        # Not fatal. The only cost is that the next run reinstalls, which pip
        # will turn into a fast no-op anyway.
        pass


def imports_present(python):
    """Are all seven dependencies importable by that interpreter?

    `importlib.util.find_spec` locates a module without executing it, so this
    is one interpreter startup (about a tenth of a second) rather than the
    second or so that importing fastapi and anthropic for real would take.
    It doubles as a health check on the environment itself: a .venv whose
    interpreter cannot start fails here instead of at uvicorn.
    """
    probe = (
        "import importlib.util as u, sys\n"
        "missing = [m for m in {0!r} if u.find_spec(m) is None]\n"
        "sys.exit(1 if missing else 0)\n".format(IMPORT_NAMES)
    )
    try:
        completed = subprocess.run(
            [python, "-c", probe],
            cwd=HERE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise Failure(broken_venv_message("cannot run {0} ({1})".format(python, exc)))
    return completed.returncode == 0


def can_reach(host, port, timeout=4.0):
    try:
        connection = socket.create_connection((host, port), timeout)
    except OSError:
        return False
    connection.close()
    return True


def pip_install(python):
    say("Installing dependencies into .venv (first run downloads a few MB) ...")
    say()
    command = [
        python,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-r",
        REQUIREMENTS,
    ]
    try:
        code = subprocess.call(command, cwd=HERE)
    except OSError as exc:
        raise Failure(broken_venv_message("cannot run pip ({0})".format(exc)))

    if code != 0 and not has_pip(python):
        # A venv built with --without-pip, or one made by a tool that skipped
        # the seed step. Put pip in it and try once more.
        say()
        say("That environment has no pip. Adding it ...")
        subprocess.call([python, "-m", "ensurepip", "--upgrade"], cwd=HERE)
        code = subprocess.call(command, cwd=HERE)

    if code != 0:
        raise Failure(install_failed_message())
    say()


def has_pip(python):
    try:
        completed = subprocess.run(
            [python, "-c", "import importlib.util as u,sys;"
                           "sys.exit(0 if u.find_spec('pip') else 1)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return False
    return completed.returncode == 0


def long_path_hint():
    """Windows only, and only while the 260-character path limit is on.

    Not hypothetical: the anthropic package ships module filenames over 100
    characters long, and installed under a deep clone path they cross MAX_PATH.
    pip then fails with `[Errno 2] No such file or directory` naming a file it
    is in the middle of creating, which reads like a bug in the project rather
    than a limit of the filesystem. Observed while testing this script from a
    long temporary directory.
    """
    if os.name != "nt":
        return ""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        )
        try:
            enabled = bool(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
        finally:
            winreg.CloseKey(key)
    except Exception:
        enabled = False
    if enabled:
        return ""
    return (
        "  - Windows' 260-character path limit, if pip's error above names a\n"
        "    file it cannot find while installing one it just downloaded.\n"
        "    Some dependencies ship very long module filenames, and this\n"
        "    project sits {0} characters deep. Either move the project\n"
        "    somewhere short (C:\\dev\\reverse-image-location), or lift the\n"
        "    limit once, in an Administrator PowerShell (one line -- a\n"
        "    backslash does not continue a line in PowerShell):\n"
        "        Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem'"
        " -Name LongPathsEnabled -Value 1\n"
        "    and reboot.\n"
    ).format(len(HERE))


def install_failed_message():
    """Say *why* pip failed, when that can be established cheaply."""
    if not can_reach("pypi.org", 443):
        return (
            "Installing the dependencies failed, and this machine cannot reach\n"
            "pypi.org:443 at all -- so this is a network problem, not a problem\n"
            "with the project.\n\n"
            "  - Check that you are online, and that a VPN or firewall is not\n"
            "    blocking outbound HTTPS.\n"
            "  - Behind a company proxy, set HTTPS_PROXY and try again.\n"
            "  - If you use a package mirror, point pip at it, for example:\n"
            "        set PIP_INDEX_URL=<your mirror>      (Windows)\n"
            "        export PIP_INDEX_URL=<your mirror>   (macOS, Linux)\n\n"
            "Then run this script again -- finished work is not repeated."
        )
    return (
        "Installing the dependencies failed. pypi.org is reachable, so the\n"
        "reason is in pip's output above -- the last few lines usually name it.\n\n"
        "Common causes:\n"
        "{0}"
        "  - No compiler for a package with no wheel for your platform. An\n"
        "    up-to-date pip usually fixes this:\n"
        "        {1} -m pip install --upgrade pip\n"
        "  - A half-built environment. Start it over:\n"
        "        python run.py --recreate-venv\n"
        "  - No space left on the drive."
    ).format(long_path_hint(), venv_python(VENV_DIR))


def ensure_dependencies(python):
    """Install requirements.txt, but only when something actually changed.

    Two cheap checks, either of which can send us to pip: a stamp that records
    the requirements.txt this environment was built from, and a probe that the
    modules are really importable. The stamp catches an edited requirements.txt;
    the probe catches a half-installed or half-deleted environment that the
    stamp would happily vouch for.
    """
    fingerprint = requirements_fingerprint()
    if read_stamp() == fingerprint and imports_present(python):
        return
    pip_install(python)
    if not imports_present(python):
        raise Failure(
            "pip reported success, but the dependencies still are not\n"
            "importable from .venv. Rebuild the environment:\n\n"
            "    python run.py --recreate-venv"
        )
    write_stamp(fingerprint)


# --- network --------------------------------------------------------------


def is_loopback(host):
    text = host.strip().strip("[]").lower()
    if text in ("localhost", ""):
        return text == "localhost"
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        # A hostname we cannot classify without resolving it. Treat it as
        # exposed: over-warning costs a paragraph, under-warning costs money.
        return False


def url_host(host):
    """The host to put in a URL a browser will open."""
    text = host.strip().strip("[]")
    if text in ("0.0.0.0", ""):
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return text
    if address.is_unspecified:  # :: -> the loopback of the same family
        return "[::1]" if address.version == 6 else "127.0.0.1"
    return "[{0}]".format(text) if address.version == 6 else text


def check_port_free(host, port):
    """Fail before uvicorn does, with a sentence instead of a stack trace."""
    try:
        candidates = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except socket.gaierror:
        raise Failure(
            "Cannot resolve --host {0}. Use an address of this machine, or\n"
            "leave it alone to listen on 127.0.0.1 only.".format(host)
        )

    family, socktype, proto, _canonname, sockaddr = candidates[0]
    probe = socket.socket(family, socktype, proto)
    try:
        if os.name != "nt":
            # Same option uvicorn sets, so this test agrees with the real bind:
            # without it a socket still in TIME_WAIT would read as occupied.
            # Never on Windows, where SO_REUSEADDR means something different
            # and lets two processes claim one port.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(sockaddr)
    except OSError:
        raise Failure(
            "Port {0} on {1} is already in use.\n\n"
            "Either this app is already running -- try http://{2}:{0}/ first --\n"
            "or something else has the port. Pick another one:\n\n"
            "    python run.py --port {3}".format(
                port, host, url_host(host), port + 1 if port < 65535 else 8010
            )
        )
    finally:
        probe.close()


def open_browser_when_ready(url, health_url, timeout=40.0):
    """Open a browser once the server answers, in a background thread.

    Waiting on /api/health instead of opening immediately: uvicorn's first
    import of fastapi, anthropic and pillow takes a second or two on a cold
    filesystem, and a browser that arrives early shows a connection error the
    user then has to reload past.
    """

    def wait_then_open():
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(health_url, timeout=2) as response:
                    if response.getcode() == 200:
                        webbrowser.open(url)
                        return
            except Exception:
                pass
            time.sleep(0.25)
        # It never came up. uvicorn has already printed why; adding a second
        # opinion here would just be noise.

    thread = threading.Thread(target=wait_then_open, name="open-browser")
    thread.daemon = True
    thread.start()


# --- serving --------------------------------------------------------------


def exposure_warning(host, port):
    return "\n".join(
        [
            "",
            "  !!  WARNING: --host {0} puts this on the network.".format(host),
            "",
            "      This app has NO AUTHENTICATION. There is no login and no",
            "      token: anyone who can reach this machine on port {0} can".format(
                port
            ),
            "",
            "        - run analyses, which spend YOUR Anthropic API credits;",
            "        - read every photo you have ever uploaded, and the",
            "          locations guessed for them;",
            "        - overwrite your stored settings through",
            "          PUT /api/settings -- including the API key itself, which",
            "          they can then read back or point at their own endpoint.",
            "",
            "      That is fine on a private LAN you trust. It is not fine on a",
            "      public address, a cafe network, or a cloud VM with an open",
            "      port. Put an authenticating reverse proxy in front, or go",
            "      back to the default 127.0.0.1 (this machine only).",
            "",
        ]
    )


def uvicorn_command(python, host, port, reload_enabled):
    command = [
        python,
        "-m",
        "uvicorn",
        ASGI_APP,
        "--host",
        host,
        "--port",
        str(port),
        # NOT optional, and not a style choice. uvicorn ships with
        # --proxy-headers ON, so it rewrites request.client from the
        # X-Forwarded-For header before the app ever sees the request. The rate
        # limiter counts per client address, so with that enabled anyone can
        # send a different forged X-Forwarded-For on every request and get a
        # fresh quota each time -- the limit stops existing, and the credits it
        # protects are yours. Measured on this app with REQUESTS_PER_HOUR=3 and
        # six forged headers: 200 200 429 429 429 429 with this flag, six
        # straight 200s without it.
        #
        # Only drop it if you put a reverse proxy you control in front, and
        # then also set TRUSTED_PROXIES to that proxy's address.
        "--no-proxy-headers",
        # Do not advertise the server and its version to whoever connects.
        "--no-server-header",
        "--log-level",
        "info",
    ]
    if reload_enabled:
        # Scoped to app/ on purpose. uvicorn's default is to watch the whole
        # working directory, which here means walking .venv -- thousands of
        # files in site-packages -- on every scan. web/ is left out too: those
        # files are served from disk on each request, so editing them needs a
        # browser refresh, not a server restart.
        command += ["--reload", "--reload-dir", os.path.join(HERE, "app")]
    return command


def serve(python, host, port, reload_enabled, open_browser):
    url = "http://{0}:{1}/".format(url_host(host), port)

    say("")
    say("  Reverse Image Location")
    say("  " + "-" * 44)
    say("  URL     {0}".format(url))
    say("  Data    {0}".format(os.path.join(HERE, "data")))
    say("  Stop    Ctrl+C")
    say("")
    say("  First run: open the settings sheet in the page and paste your own")
    say("  Anthropic API key. It is saved to data/config.json on this machine")
    say("  and is never committed.")
    if not is_loopback(host):
        say(exposure_warning(host, port))
    say("")

    if open_browser:
        open_browser_when_ready(url, "http://{0}:{1}{2}".format(
            url_host(host), port, HEALTH_PATH
        ))

    try:
        process = subprocess.Popen(uvicorn_command(python, host, port, reload_enabled),
                                   cwd=HERE)
    except OSError as exc:
        raise Failure(broken_venv_message("cannot start uvicorn ({0})".format(exc)))

    try:
        return process.wait()
    except KeyboardInterrupt:
        # Ctrl+C reached uvicorn too -- it is in the same console process
        # group. Give it a moment to close its sockets before insisting.
        try:
            process.wait(timeout=10)
        except Exception:
            process.terminate()
        say("")
        say("Stopped.")
        return 0


# --- entry point ----------------------------------------------------------


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="python run.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Set up and start Reverse Image Location.\n\n"
            "Creates .venv if it is missing, installs requirements.txt into it\n"
            "when they have changed, then serves the app and opens a browser.\n"
            "Safe to run again -- work that is already done is skipped."
        ),
        epilog=(
            "examples:\n"
            "  python run.py                     set up and start on 127.0.0.1:8000\n"
            "  python run.py --port 8010         when 8000 is taken\n"
            "  python run.py --reload            restart on edits to app/\n"
            "  python run.py --recreate-venv     rebuild a broken .venv\n"
            "\n"
            "Your API key goes in the settings sheet in the page, not in a file.\n"
            "It is stored in data/, which is gitignored along with .env.\n"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        metavar="N",
        help="port to listen on (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        metavar="ADDR",
        help=(
            "address to bind (default: 127.0.0.1, this machine only). "
            "Anything else exposes an app with no authentication -- see the "
            "warning it prints."
        ),
    )
    parser.add_argument(
        "--no-browser",
        dest="browser",
        action="store_false",
        help="do not open a browser window",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="restart the server when files in app/ change (development)",
    )
    parser.add_argument(
        "--recreate-venv",
        action="store_true",
        help="delete .venv and build it again, then continue as usual",
    )
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)

    if not 1 <= args.port <= 65535:
        raise Failure(
            "--port must be between 1 and 65535; got {0}.".format(args.port)
        )
    if not os.path.isfile(os.path.join(HERE, "app", "main.py")):
        raise Failure(
            "This does not look like a complete checkout: {0} is missing.\n\n"
            "Clone the repository again, or unpack the whole release archive\n"
            "rather than a few files from it.".format(
                os.path.join(HERE, "app", "main.py")
            )
        )

    # Before the slow parts: refusing after a two-minute pip install would be
    # rude, and the port is the thing most likely to be taken.
    check_port_free(args.host, args.port)

    python = ensure_venv(args.recreate_venv)
    ensure_dependencies(python)
    return serve(python, args.host, args.port, args.reload, args.browser)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Failure as failure:
        if DEBUG:
            raise
        sys.stderr.write("\n" + str(failure) + "\n\n")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.stderr.write("\nCancelled.\n")
        sys.exit(130)
    except Exception as unexpected:  # noqa: BLE001 - a traceback helps nobody here
        if DEBUG:
            raise
        sys.stderr.write(
            "\nrun.py hit an unexpected problem:\n"
            "    {0}: {1}\n\n"
            "Set RIL_RUN_DEBUG=1 and run it again for the full traceback.\n\n".format(
                type(unexpected).__name__, unexpected
            )
        )
        sys.exit(1)
