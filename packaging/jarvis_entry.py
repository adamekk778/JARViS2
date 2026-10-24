import multiprocessing
import os
import sys
import traceback


def _crash_dir() -> str:
    base = os.environ.get("JARVIS_HOME") or os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "JARVIS")
    os.makedirs(base, exist_ok=True)
    return base


def _fault_file():
    """faulthandler's log. Busy (another JARVIS still has it open) or not writable → another name, or none:
    a diagnostic file must never stop JARVIS from starting."""
    own = f"fault-{os.getpid()}.log"
    # helper processes (skills) never take the main instance's log
    names = (own,) if "--run-skill" in sys.argv or "--legacy" in sys.argv else ("fault.log", own)
    for name in names:
        try:
            return open(os.path.join(_crash_dir(), name), "w")
        except OSError:
            continue
    return None


def _dpi_aware():
    """Before ANY window exists (tray, keyboard hooks, WebView2): tell Windows JARVIS draws at the real screen
    resolution. Otherwise at 125 / 150 % scaling Windows stretches a low-resolution picture → blurry, pixelated."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2))  # DPI_AWARENESS_CONTEXT_SYSTEM_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


if __name__ == "__main__":
    _dpi_aware()
    multiprocessing.freeze_support()
    crash_file = os.path.join(_crash_dir(), "crash.log")
    try:
        import faulthandler

        fault = _fault_file()
        if fault is not None:
            faulthandler.enable(fault)
        from jarvis.__main__ import main

        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        try:
            with open(crash_file, "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except OSError:
            crash_file = os.path.join(_crash_dir(), f"crash-{os.getpid()}.log")
            try:
                with open(crash_file, "w", encoding="utf-8") as f:
                    traceback.print_exc(file=f)
            except OSError:
                pass
        if sys.platform == "win32" and "--no-ui" not in sys.argv:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, f"JARVIS spadl při startu. Podrobnosti: {crash_file}", "JARVIS", 0x10)
        sys.exit(1)
