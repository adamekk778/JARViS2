import multiprocessing
import os
import sys
import traceback


def _crash_dir() -> str:
    base = os.environ.get("JARVIS_HOME") or os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "JARVIS")
    os.makedirs(base, exist_ok=True)
    return base


if __name__ == "__main__":
    multiprocessing.freeze_support()
    crash_file = os.path.join(_crash_dir(), "crash.log")
    try:
        import faulthandler

        faulthandler.enable(open(os.path.join(_crash_dir(), "fault.log"), "w"))
        from jarvis.__main__ import main

        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        with open(crash_file, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        if sys.platform == "win32" and "--no-ui" not in sys.argv:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, f"JARVIS spadl při startu. Podrobnosti: {crash_file}", "JARVIS", 0x10)
        sys.exit(1)
