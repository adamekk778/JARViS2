"""3.14 Webkamera – one place for the PC's camera (opt-in features only):

- "mluv bez Hey Jarvis": you are alone at the PC and look at the screen → just talk (17)
- ochrana PC: someone at the PC while you are away → a photo for you (38)
- sezení u PC: leaning in too close for too long → a gentle reminder (44)

Everything is processed on this PC (OpenCV's built-in face finder, no AI service), a frame is never stored unless a
feature says so (the guard photo), and every use is written into the access log (Bezpečí a soukromí → Co JARVIS viděl).
Without OpenCV or a camera the features say so and stay off.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Any

log = logging.getLogger(__name__)
_lock = threading.Lock()
_cascade: Any = None


class NoCamera(RuntimeError):
    pass


def available() -> bool:
    try:
        import cv2  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def open_camera(index: int = 0) -> Any:
    try:
        import cv2
    except Exception as e:  # noqa: BLE001
        raise NoCamera("chybí OpenCV (součást instalace JARVISe pro Windows)") from e
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(index)
    if not cap.isOpened():
        cap.release()
        raise NoCamera("kamera není připojená nebo ji používá jiná aplikace")
    return cap


def read(cap: Any) -> Any:
    ok, frame = cap.read()
    if not ok or frame is None:
        raise NoCamera("z kamery nepřišel obraz")
    return frame


def grab(index: int = 0) -> Any:
    """One frame from the camera (BGR numpy array). Raises NoCamera."""
    with _lock:
        cap = open_camera(index)
        try:
            frame = None
            for _ in range(4):                       # the first frames are often dark while the camera adjusts
                frame = read(cap)
            return frame
        finally:
            cap.release()


def faces(frame: Any) -> list[tuple[int, int, int, int]]:
    """Frontal faces (x, y, w, h), the biggest first."""
    global _cascade
    import cv2

    if _cascade is None:
        _cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if getattr(frame, "ndim", 2) == 3 else frame
    found = _cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=6, minSize=(60, 60))
    return sorted(((int(x), int(y), int(w), int(h)) for x, y, w, h in found), key=lambda f: -f[2] * f[3])


def looking(found: list[tuple[int, int, int, int]], width: int) -> bool:
    """Exactly one person, facing the screen, close enough to be the one at the PC."""
    return len(found) == 1 and found[0][2] >= width * 0.12


def jpeg(frame: Any, quality: int = 80) -> bytes:
    import cv2

    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return bytes(buf) if ok else b""


def log_use(rt: Any, tool: str, what: str = "") -> None:
    try:
        from . import shield

        shield.log_access(rt, tool, "camera", {"target": what})
    except Exception:  # noqa: BLE001
        pass


class LookWatcher:
    """Looks once a second while "mluv bez Hey Jarvis" is on: is one person looking at the screen right now?"""

    def __init__(self, rt: Any, every: float = 1.0):
        self.rt = rt
        self.every = every
        self.seen_at = 0.0
        self.last: tuple | None = None           # (the face or None, width, height, monotonic time) – the posture check reuses it
        self.error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def wanted(self) -> bool:
        v = getattr(self.rt.cfg, "voice", None)
        return bool(v and getattr(v, "look_to_talk", False) and v.enabled)

    def ok(self, within: float = 1.6) -> bool:
        return time.monotonic() - self.seen_at <= within

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="look-to-talk")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        logged = 0.0
        cap = None
        try:
            while not self._stop.is_set() and self.wanted():
                try:
                    if cap is None:                  # kept open while watching (opening it each second is slow)
                        cap = open_camera(int(getattr(self.rt.cfg.voice, "camera_index", 0) or 0))
                    frame = read(cap)
                    found = faces(frame)
                    self.last = (found[0] if len(found) == 1 else None, int(frame.shape[1]), int(frame.shape[0]), time.monotonic())
                    if looking(found, frame.shape[1]):
                        self.seen_at = time.monotonic()
                    self.error = ""
                    if time.time() - logged > 600:   # the access log: once per 10 min while it watches
                        logged = time.time()
                        log_use(self.rt, "look_to_talk", "mluv bez Hey Jarvis")
                except NoCamera as e:
                    self.error = str(e)
                    if cap is not None:
                        cap.release()
                        cap = None
                    self._stop.wait(30)
                except Exception as e:  # noqa: BLE001
                    self.error = f"{type(e).__name__}: {e}"
                    self._stop.wait(10)
                self._stop.wait(self.every)
        finally:
            if cap is not None:
                cap.release()
