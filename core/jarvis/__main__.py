"""Start JARVIS: server + voice + desktop shell.

    python -m jarvis                 # everything (Windows)
    python -m jarvis --no-ui         # server only (headless / Linux dev)
    python -m jarvis --background    # autostart: don't open the chat window
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import socket
import sys
import threading
import time
import webbrowser

import httpx

from . import __version__, config, paths


def fix_windowed_stdio() -> None:
    """A windowed (no console) exe has sys.stdout/stderr = None; libraries that print or call isatty() crash."""
    import os

    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def setup_logging(debug: bool) -> None:
    logdir = paths.sub("logs")
    handlers: list[logging.Handler] = [logging.handlers.RotatingFileHandler(
        logdir / "jarvis.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr and not getattr(sys, "frozen", False):
        handlers.append(logging.StreamHandler())
    from .redact import RedactFilter

    for hd in handlers:
        hd.addFilter(RedactFilter())
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def thread_hook(a):
        logging.getLogger("jarvis").error("thread %s crashed", a.thread.name if a.thread else "?",
                                          exc_info=(a.exc_type, a.exc_value, a.exc_traceback))

    threading.excepthook = thread_hook
    for noisy in ("httpx", "httpcore", "uvicorn.access", "comtypes", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


HEADLESS = False


def message_box(text: str) -> None:
    logging.getLogger("jarvis").error(text)
    if sys.platform == "win32" and not HEADLESS:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "JARVIS", 0x10)


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def already_running(port: int) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2).json().get("name") == "JARVIS"
    except Exception:
        return False


def start_server(rt, port: int) -> threading.Thread:
    import uvicorn

    from .server.app import create_app

    app = create_app(rt)

    def run():
        cfg = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning", ws_max_size=32 * 2**20,
                             timeout_keep_alive=30, log_config=None)  # our logging; uvicorn's needs a console
        server = uvicorn.Server(cfg)
        asyncio.run(server.serve())

    t = threading.Thread(target=run, daemon=True, name="server")
    t.start()
    for _ in range(600):
        if rt.loop is not None and port_in_use(port):
            break
        time.sleep(0.1)
    else:
        message_box("JARVIS se nepodařilo spustit (server nenaběhl). Podrobnosti najdeš v %APPDATA%\\JARVIS\\logs\\jarvis.log.")
        raise SystemExit(3)
    return t


def start_extras(rt) -> None:
    """Voice loop + media watcher, all optional."""
    log = logging.getLogger("jarvis")
    try:
        from .voice.loop import VoiceLoop

        rt.voice = VoiceLoop(rt)
        rt.speaker = rt.voice.speaker
        rt.voice.start()
    except Exception as e:
        log.warning("voice unavailable: %s", e)
        try:
            from .voice.tts import Speaker

            rt.speaker = Speaker(rt)
        except Exception as e2:
            log.warning("tts unavailable: %s", e2)
    if sys.platform == "win32":
        from .desktop.media import watch

        rt.submit(watch(rt))


def main(argv: list[str] | None = None) -> int:
    fix_windowed_stdio()
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--run-python"] and len(argv) > 1:  # run_python tool inside the frozen exe
        import runpy

        sys.argv = argv[1:]
        runpy.run_path(argv[1], run_name="__main__")
        return 0
    ap = argparse.ArgumentParser(prog="jarvis", description="JARVIS 2")
    ap.add_argument("--no-ui", action="store_true", help="jen server (bez oken)")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--background", action="store_true", help="neotvírat okno chatu")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)
    global HEADLESS
    HEADLESS = args.no_ui

    setup_logging(args.debug)
    log = logging.getLogger("jarvis")
    cfg = config.load()
    port = cfg.phone.port
    if port_in_use(port):
        if already_running(port):
            log.info("JARVIS already running, showing its window")
            try:
                httpx.post(f"http://127.0.0.1:{port}/api/show", timeout=3)
            except Exception:
                webbrowser.open(f"http://127.0.0.1:{port}/")
            return 0
        log.error("port %s is used by another program", port)
        message_box(f"Port {port} používá jiný program. Zavři ho, nebo změň port v %APPDATA%\\JARVIS\\config.toml (sekce [phone]).")
        return 2

    from .runtime import Runtime

    rt = Runtime(cfg)
    start_server(rt, port)
    from .bootstrap import start_background

    start_background(rt)
    if not args.no_voice and cfg.voice.enabled:
        start_extras(rt)
    elif sys.platform == "win32":
        from .desktop.media import watch

        rt.submit(watch(rt))
    log.info("JARVIS %s running on :%s", __version__, port)

    if args.no_ui:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0
    try:
        from .desktop.host import DesktopHost
    except Exception as e:
        log.error("desktop UI unavailable (%s); open http://127.0.0.1:%s", e, port)
        webbrowser.open(f"http://127.0.0.1:{port}/")
        while True:
            time.sleep(3600)
    DesktopHost(rt, f"http://127.0.0.1:{port}").run(open_chat=not args.background)
    return 0


if __name__ == "__main__":
    sys.exit(main())
