"""3.14 (návrh 21): start a real JARVIS server (test data, no microphone, no AI) and let web/tests/uicheck.mjs open
every page in Chromium – script errors, pages spilling sideways, a notch off the window – with screenshots.

    python -m jarvis.uicheck --out uicheck-out      (needs web/dist built and Node with Playwright)
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(port: int) -> threading.Thread:
    import uvicorn

    from .runtime import Runtime
    from .server.app import create_app
    from .tools.platform.null import NullPlatform

    rt = Runtime(platform=NullPlatform(), persist_config=False)
    rt.cfg.phone.port = port
    rt.cfg.general.onboarded = True            # the pages themselves, not the first-run guide over them
    rt.cfg.general.user_name = "Adam"
    app = create_app(rt, manage_runtime=False)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), 0.2):
                return th
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jarvis.uicheck")
    ap.add_argument("--out", default="uicheck-out")
    a = ap.parse_args(argv)
    os.environ.setdefault("JARVIS_NO_NET", "1")
    root = Path(__file__).resolve().parents[2]
    port = free_port()
    serve(port)
    script = root / "web" / "tests" / "uicheck.mjs"
    env = {**os.environ, "NODE_PATH": os.environ.get("NODE_PATH", "")}
    r = subprocess.run(["node", str(script), f"http://127.0.0.1:{port}", a.out], cwd=str(root / "web"), env=env)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
