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


def setup_logging(debug: bool) -> None:
    logdir = paths.sub("logs")
    handlers: list[logging.Handler] = [logging.handlers.RotatingFileHandler(
        logdir / "jarvis.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr and not getattr(sys, "frozen", False):
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "uvicorn.access", "comtypes", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


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
                             timeout_keep_alive=30)
        server = uvicorn.Server(cfg)
        asyncio.run(server.serve())

    t = threading.Thread(target=run, daemon=True, name="server")
    t.start()
    for _ in range(100):
        if rt.loop is not None and port_in_use(port):
            break
        time.sleep(0.1)
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

    setup_logging(args.debug)
    log = logging.getLogger("jarvis")
    cfg = config.load()
    port = cfg.phone.port
    if port_in_use(port):
        if already_running(port):
            log.info("JARVIS already running, opening chat")
            webbrowser.open(f"http://127.0.0.1:{port}/")
            return 0
        log.error("port %s is used by another program", port)
        return 2

    from .runtime import Runtime

    rt = Runtime(cfg)
    start_server(rt, port)
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
