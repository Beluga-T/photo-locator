#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry point for the packaged build: double-click it, and the app is running.

This is the script PyInstaller freezes -- see photo-locator.spec. It exists
instead of reusing run.py because run.py's whole job is to build a .venv and
install requirements.txt into it, and inside a frozen executable there is no
venv to build, no pip to run and no requirements.txt to read: the interpreter
and every dependency are already inside the binary. What is left is the part
run.py does at the end -- pick a port, start uvicorn, open a browser, say where
the data went -- and that is all this file is.

It is written around one assumption: for someone who unzipped a download and
double-clicked it, the console window IS the user interface. There is no
terminal they can scroll back in and no log they know how to find. So the
banner is short, the numbers that matter (URL, data directory, how to stop) are
on their own lines, and the process never exits silently -- an unexpected error
prints and then *waits*, because a console that closes in the same instant it
printed the reason has reported nothing at all.

    photo-locator                  start on 127.0.0.1:8000, or the next free port
    photo-locator --port 8010      start somewhere specific
    photo-locator --no-browser     do not open a browser

Only the standard library is imported at module scope; the app comes in inside
main(), for the reason given there.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import socket
import sys
from pathlib import Path
import threading
import time
import traceback
import webbrowser

# Not configurable, on purpose. This app has no authentication of any kind, and
# run.py has to print a nine-line warning before it will bind anything else.
# A build that strangers download and double-click is exactly the audience that
# would not read the warning, so the address is simply not a knob here: someone
# who genuinely wants this on a LAN can run it from source, read the warning,
# and put a proxy in front.
HOST = "127.0.0.1"

DEFAULT_PORT = 8000

# How far above the requested port to look before giving up. Twenty is not a
# limit anyone reaches -- it is there so that a machine where *every* bind fails
# for some unrelated reason (a firewall policy, an exhausted handle table) says
# so within a second, instead of walking 57000 ports in silence.
PORT_SCAN_LIMIT = 20

# How long the browser thread waits for the server to come up. The first import
# of fastapi, anthropic and pillow can take a couple of seconds on a cold disk,
# and on a slow laptop with an antivirus scanning a freshly unpacked binary it
# can take a good deal longer.
BROWSER_TIMEOUT = 60.0


class Failure(Exception):
    """A problem this launcher knows how to explain.

    Raised with a message meant for someone who downloaded a zip and has no
    idea what uvicorn is. It is printed as prose, without a traceback.
    """


def say(text: str = "") -> None:
    print(text)
    sys.stdout.flush()


def use_utf8() -> None:
    """Make the Chinese in the banner survive a redirected stdout.

    A real Windows console is fine either way: Python writes to it through the
    wide-character API regardless of the code page. A *redirected* stdout is
    not -- it falls back to the machine's ANSI code page, and on a non-Chinese
    Windows that is cp1252, where the first Chinese character raises
    UnicodeEncodeError. Losing the entire app to its own greeting would be an
    absurd way to fail, so the streams are switched to UTF-8 and anything that
    still cannot be encoded degrades to a replacement character.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            # Not a TextIOWrapper, or already gone. Nothing here is worth
            # failing over before the app has even started.
            pass


# --- network --------------------------------------------------------------


def reserve_port(first_port: int) -> tuple[socket.socket, int]:
    """Bind the first free port at or above `first_port`, and keep the socket.

    The bound socket is handed to uvicorn rather than closed and re-bound by it.
    That closes a race that a desktop app actually hits: between "I proved this
    port was free" and "uvicorn binds it" sits a window in which a second copy
    of this app -- started by someone who double-clicked twice because nothing
    seemed to happen -- takes the port, and one of the two then dies with an
    error message about address reuse that means nothing to them.
    """
    last_error: OSError | None = None
    ceiling = min(first_port + PORT_SCAN_LIMIT, 65536)

    for port in range(first_port, ceiling):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            # The option uvicorn sets when it binds for itself. Without it a
            # listener cannot come back on the same port while connections from
            # the previous run are still in TIME_WAIT, so quitting and starting
            # again would quietly move the app to 8001 and leave the old URL in
            # the user's tab. Never on Windows, where SO_REUSEADDR means
            # something different: it lets two processes hold one port, and the
            # second one silently receives nothing.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
        except OSError as exc:
            sock.close()
            last_error = exc
            continue
        return sock, port

    raise Failure(
        "找不到可以使用的端口：{0} 到 {1} 都被占用了。({2})\n"
        "No free port between {0} and {1} -- they are all in use. ({2})\n\n"
        "先关掉可能已经在运行的这个程序，或者指定一个端口：\n"
        "Close any copy of this app that is already running, or pick a port:\n\n"
        "    photo-locator --port 9000".format(
            first_port, ceiling - 1, last_error
        )
    )


def open_browser_when_ready(server, url: str) -> None:
    """Open the browser once uvicorn reports it is serving, from a thread.

    Waiting on `server.started` rather than opening straight away: that flag is
    set after the ASGI lifespan startup has finished, which is later than "the
    port is bound" and is the honest definition of ready -- fastapi, anthropic
    and pillow have all been imported by then. A browser that arrives earlier
    shows a connection error the user has to know to reload past, and the first
    thing this app should do is work.
    """

    def wait_then_open() -> None:
        deadline = time.monotonic() + BROWSER_TIMEOUT
        while time.monotonic() < deadline:
            if server.started:
                webbrowser.open(url)
                return
            if server.should_exit:
                # Startup failed. uvicorn has already logged why; a browser
                # window pointing at nothing would only add confusion.
                return
            time.sleep(0.1)

    threading.Thread(target=wait_then_open, name="open-browser", daemon=True).start()


# --- the banner -----------------------------------------------------------


def stop_hint() -> str:
    """How to stop the app, in the terms of whoever is looking at it.

    On Windows this executable is almost always double-clicked, and the console
    it opens is the only window it has: closing that window is what the user
    will reach for, and it is the truthful answer. Ctrl+C works everywhere and
    is the only answer on macOS and Linux, where the binary is run from a shell
    that outlives it.
    """
    if os.name == "nt":
        return "关掉这个窗口就停了  (close this window to stop)"
    return "按 Ctrl+C  (press Ctrl+C)"


def banner(url: str, data_root, requested_port: int, port: int, portable: bool) -> None:
    say("")
    say("  照片定位  Photo Locator")
    say("  " + "-" * 60)
    if port != requested_port:
        # Said before the URL, not after: the user is about to read an address
        # that is not the one any instruction told them to expect.
        say("  端口 {0} 被占用了，改用 {1}。".format(requested_port, port))
        say("  Port {0} was busy, so this is running on {1} instead.".format(
            requested_port, port
        ))
        say("")
    say("  网址 URL     {0}".format(url))
    say("  数据 Data    {0}".format(data_root))
    if portable:
        # Worth one line: it is the difference between "where did my history
        # go" and "this whole thing is one folder I can move or delete".
        say("               (就在程序旁边，整个文件夹删掉就清空了)")
        say("               (next to the program -- delete the folder to erase it all)")
    say("  停止 Stop    {0}".format(stop_hint()))
    say("")
    say("  第一次使用：打开页面右上角的设置，把你自己的 Anthropic API key 粘进去。")
    say("  它只保存在上面那个文件夹里，不会传到别处。")
    say("")
    say("  First run: open the settings sheet at the top right of the page and")
    say("  paste your own Anthropic API key. It stays in the folder above.")
    say("")


# --- entry point ----------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="photo-locator",
        description=(
            "Start Reverse Image Location and open it in a browser. "
            "Run it with no arguments -- everything else is a convenience."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        metavar="N",
        help=(
            "port to listen on (default: %(default)s). If it is taken, the next "
            "free one above it is used and the app says so."
        ),
    )
    parser.add_argument(
        "--no-browser",
        dest="browser",
        action="store_false",
        help="do not open a browser window",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise Failure(
            "--port 必须在 1 和 65535 之间，收到的是 {0}。\n"
            "--port must be between 1 and 65535; got {0}.".format(args.port)
        )

    say("")
    say("正在启动，请稍候…  Starting, please wait…")

    # Imported here rather than at the top of the file, for two reasons.
    #
    # It is the slow part -- fastapi, anthropic and pillow together take a
    # second or two on a cold disk, longer while an antivirus is still reading
    # a freshly unpacked binary -- and the line above should already be on
    # screen while that happens, or a double-clicked window sits blank and gets
    # double-clicked again.
    #
    # And anything that goes wrong in it lands inside the handler at the bottom
    # of this file, which keeps the window open. At module scope the same
    # failure would kill the process before there was anything to catch it
    # with, which is precisely the vanishing-window failure this file exists to
    # prevent.
    import uvicorn

    from app.main import app as asgi_app
    from app.main import store
    from app.paths import FROZEN, resource

    # A build whose spec stopped bundling web/ produces a server that starts
    # perfectly and then answers 404 for every page -- which reads as a broken
    # app rather than a broken build, and is impossible to diagnose from the
    # browser. One stat is cheaper than that. The directory is asked for the
    # same way app/main.py asks for it, so this checks the real mount point.
    web_root = resource("web")
    if not (web_root / "index.html").is_file():
        raise Failure(
            "这个程序打包不完整：找不到网页文件（{0}）。\n"
            "This build is incomplete -- the web files are missing ({0}).\n\n"
            "请重新下载一次 release 里的压缩包，并且整包解压。\n"
            "Download the release archive again and unpack all of it.".format(web_root)
        )

    sock, port = reserve_port(args.port)
    url = "http://{0}:{1}/".format(HOST, port)

    config = uvicorn.Config(
        asgi_app,
        host=HOST,
        port=port,
        # NOT optional, and not a style choice -- the same flag run.py passes as
        # --no-proxy-headers, for the same reason. uvicorn ships with proxy
        # headers ON, so it rewrites request.client from X-Forwarded-For before
        # the app ever sees the request. app/main.py counts rate-limit hits per
        # client address, so with this left on, anyone who can reach the port
        # sends a different forged X-Forwarded-For per request and gets a fresh
        # quota every time -- the limit stops existing, and the API credits it
        # protects are the user's own.
        proxy_headers=False,
        # Do not tell whoever connects which server and version this is.
        server_header=False,
        # The app streams results to the browser over Server-Sent Events
        # (text/event-stream, app/main.py) and opens no WebSocket anywhere.
        # Saying so stops uvicorn resolving a WebSocket implementation at
        # startup, and lets photo-locator.spec leave the websockets package out
        # of the binary altogether.
        ws="none",
        # Pinned rather than left on "auto". auto prefers uvloop wherever it can
        # import it, which would make the macOS and Linux builds run on a
        # different event loop -- and a different set of bundled binaries --
        # from the Windows one, for a throughput gain that a single user
        # clicking through one photo at a time cannot measure.
        loop="asyncio",
        log_level="info",
    )
    server = uvicorn.Server(config)

    # Where the data really went, asked of the Store rather than computed again
    # here: app.paths.data_dir() is the default it starts from, but RIL_DATA_DIR
    # overrides it and an unusable value makes the Store fall back. Printing
    # anything other than the directory it actually opened would be a lie in the
    # one line the user is most likely to act on.
    #
    # "portable" is whether the data REALLY sits beside the executable — not
    # merely FROZEN. paths.data_dir() diverts to the per-user directory for an
    # unwritable install dir, a run from a temp folder, or a .app bundle, and
    # printing "next to the program" over any of those would contradict the
    # warning logged two lines earlier.
    portable = FROZEN and store.root.parent == Path(sys.executable).resolve().parent
    banner(url, store.root, args.port, port, portable)

    if args.browser:
        open_browser_when_ready(server, url)

    # The socket is already bound (see reserve_port). uvicorn will listen() on
    # it, serve it, and close it on the way out.
    server.run(sockets=[sock])

    say("")
    say("已停止。 Stopped.")
    return 0


def hold_window(message: str) -> None:
    """Keep the console on screen until a key is pressed.

    The classic double-click failure is a window that appears and vanishes: the
    error was printed, nobody could read it, and what comes back is "I clicked
    it and nothing happened".

    Two conditions, and both are about not hanging someone who does not need
    this. Only when frozen -- a developer running `python launch.py` already has
    a terminal that stays put. That question is put to the interpreter directly
    rather than to app.paths.FROZEN, because this handler has to keep working in
    the case where importing app.paths is itself what failed.

    And only when *stdout* is a console. It is stdout and not stdin, which was
    the obvious first guess and is wrong: msvcrt.getch() below reads the console
    device rather than stdin, so it blocks even when stdin has been redirected,
    and a scripted `photo-locator --port 70000 > log.txt` hung here forever --
    observed, not theorised. stdout is also the stream that answers the question
    actually being asked: if the output went to a file or a pipe, it has already
    been saved somewhere the user can read at leisure and there is nothing to
    hold the window for.
    """
    if not getattr(sys, "frozen", False):
        return
    if sys.stdout is None or not sys.stdout.isatty():
        return

    say("")
    say(message)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.getch()
        else:
            # A macOS Finder double-click opens Terminal, whose default is to
            # keep the window after the process exits -- but that is a setting,
            # and a user who changed it deserves the same chance to read this.
            input()
    except Exception:
        # A console that cannot be read from is not worth a second error on top
        # of the first one.
        pass


if __name__ == "__main__":
    # First, before anything can spawn. On Windows a frozen app that reaches
    # multiprocessing re-executes this very file in the child process, and
    # without this call the child starts a whole second server instead of doing
    # the child's work -- and so does its child, forever. Nothing here uses
    # multiprocessing today (one uvicorn worker, no reloader), but uvicorn
    # imports it, and the cost of being wrong once is a process bomb on a
    # stranger's machine.
    multiprocessing.freeze_support()

    use_utf8()

    try:
        sys.exit(main(sys.argv[1:]))
    except Failure as failure:
        say("")
        say(str(failure))
        hold_window("按任意键关闭。 Press any key to close.")
        sys.exit(1)
    except KeyboardInterrupt:
        say("")
        say("已停止。 Stopped.")
        sys.exit(130)
    except SystemExit as request:
        # uvicorn calls sys.exit() itself on a startup failure. A clean exit
        # should close the window as expected; a failed one has just printed the
        # reason and needs to stay long enough to be read.
        if request.code not in (0, None):
            hold_window("按任意键关闭。 Press any key to close.")
        raise
    except BaseException:
        # Anything not anticipated. The traceback is printed in full because it
        # is the only thing the user can usefully send back, and then the window
        # is held open, because a console that closes on the same millisecond it
        # printed the reason has reported nothing at all.
        say("")
        say("程序出了意料之外的问题： Photo Locator hit an unexpected problem:")
        say("")
        traceback.print_exc()
        hold_window(
            "把上面这些内容截图发到项目的 issue 里。按任意键关闭。\n"
            "Send a screenshot of the above with your bug report. Press any key to close."
        )
        sys.exit(1)
