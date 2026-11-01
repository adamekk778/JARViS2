"""The notch's window outline animated by JARVIS itself, in step with the screen (3.12).

With the window cut to the notch shape (the reliable mode), what you see IS the window region – the black shape
inside is the same colour as everything around it. So the animation is only as smooth as the region updates.
The page used to send a new outline every frame through the pywebview bridge (a thread per call, frames arriving
unevenly), which made the notch stutter. Now the page sends one plan per movement – where the spring starts, its
speed, where it goes – and this thread runs the very same spring, one outline per screen refresh (DwmFlush waits
for the compositor), straight into Windows. The geometry is a port of web/src/shared/region.ts.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

Poly = list[tuple[int, int]]
D = math.pi / 180


def _arc(cx: float, cy: float, r: float, a0: float, a1: float, steps: int) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / steps), cy + r * math.sin(a0 + (a1 - a0) * i / steps)) for i in range(steps + 1)]


def _js_round(v: float) -> int:
    return math.floor(v + 0.5)              # Math.round (Python's round() rounds halves to even)


def _scale(pts: list[tuple[float, float]], k: float) -> Poly:
    return [(_js_round(x * k), _js_round(y * k)) for x, y in pts]


def round_rect(left: float, top: float, right: float, bottom: float, radius: float, dpr: float, pad: float = 0) -> Poly:
    L, T, R, B = left - pad, top - pad, right + pad, bottom + pad
    rad = max(0.0, min(radius, (B - T) / 2, (R - L) / 2))
    return _scale(_arc(R - rad, T + rad, rad, -90 * D, 0, 4) + _arc(R - rad, B - rad, rad, 0, 90 * D, 4)
                  + _arc(L + rad, B - rad, rad, 90 * D, 180 * D, 4) + _arc(L + rad, T + rad, rad, 180 * D, 270 * D, 4), dpr)


def notch_outline(left: float, top: float, right: float, bottom: float, radius: float, ear: float, dpr: float, pad: float = 0) -> Poly:
    L, R, T, B = left - pad, right + pad, top, bottom + pad
    rad = max(0.0, min(radius + pad, (B - T) / 2, (R - L) / 2))
    pts = ([(L - ear, T), (R + ear, T)] + _arc(R + ear, T + ear, ear, -90 * D, -180 * D, 12)
           + _arc(R - rad, B - rad, rad, 0, 90 * D, 18) + _arc(L + rad, B - rad, rad, 90 * D, 180 * D, 18)
           + _arc(L - ear, T + ear, ear, 0, -90 * D, 12))
    return _scale(pts, dpr)


def outline(plan: dict, w: float, h: float, r: float) -> list[Poly]:
    """The notch at width w, height h, corner radius r (CSS px) as window polygons in physical px."""
    cx, top, dpr, pad = float(plan["cx"]), float(plan["top"]), float(plan.get("dpr") or 1), float(plan.get("pad") or 0)
    left, right = cx - w / 2, cx + w / 2
    if plan.get("geom") == "notch":
        return [notch_outline(left, top, right, top + h, max(0.0, r), float(plan.get("ear", 14)), dpr, pad)]
    return [round_rect(left, top, right, top + h, max(0.0, r), dpr, pad)]


class Spring:
    """The page's spring (web/src/notch/main.ts springStep), so both draw the same curve."""

    def __init__(self, plan: dict):
        f, t = plan["from"], plan["to"]
        self.x = {k: float(f[k]) for k in ("w", "h", "r")}
        self.v = {k: float(f.get("v" + k, 0)) for k in ("w", "h", "r")}
        self.t = {k: float(t[k]) for k in ("w", "h", "r")}
        self.k, self.c = float(plan.get("k", 300)), float(plan.get("c", 24))

    def step(self, dt: float) -> bool:
        """Advance by dt seconds; False once it has come to rest (exactly on the target)."""
        dt = min(0.034, max(0.0, dt))
        moving = False
        for key in ("w", "h", "r"):
            a = self.k * (self.t[key] - self.x[key]) - self.c * self.v[key]
            self.v[key] += a * dt
            self.x[key] += self.v[key] * dt
            if abs(self.t[key] - self.x[key]) > 0.3 or abs(self.v[key]) > 4:
                moving = True
        if not moving:
            self.x = dict(self.t)
            self.v = {k: 0.0 for k in self.v}
        return moving


def _frame_waiter() -> Callable[[], None]:
    """Wait for the next screen refresh: DwmFlush on Windows (vsync of the compositor), else ~120 Hz."""
    try:
        import ctypes

        flush = ctypes.windll.dwmapi.DwmFlush        # type: ignore[attr-defined]

        def wait() -> None:
            if flush() != 0:                          # composition off / failed: plain timer
                time.sleep(1 / 120)
        return wait
    except (AttributeError, OSError):
        return lambda: time.sleep(1 / 120)


class RegionAnimator:
    def __init__(self, apply: Callable[[list[Poly]], object], wait: Callable[[], None] | None = None, clock=time.perf_counter):
        self.apply, self.wait, self.clock = apply, wait or _frame_waiter(), clock
        self._lock = threading.Lock()
        self._plan: dict | None = None
        self._spring: Spring | None = None
        self._thread: threading.Thread | None = None
        self.frames = 0

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(self, plan: dict) -> None:
        """A new movement (or a new target mid-way): the spring continues from where the page says it is."""
        with self._lock:
            self._plan, self._spring = plan, Spring(plan)
            if self._thread is None:                  # cleared by the thread itself, under this lock, when it ends
                self._thread = threading.Thread(target=self._run, daemon=True, name="notch-region")
                self._thread.start()

    def _run(self) -> None:
        last = self.clock()
        while True:
            self.wait()
            now = self.clock()
            with self._lock:
                spring, plan = self._spring, self._plan
                if spring is None or plan is None:
                    self._thread = None
                    return
                moving = spring.step(now - last)
                polys = outline(plan, spring.x["w"], spring.x["h"], spring.x["r"])
                if not moving:
                    self._spring = None
            last = now
            try:
                self.apply(polys)
                self.frames += 1
            except Exception as e:  # noqa: BLE001
                log.debug("region frame: %s", e)
            if not moving:
                with self._lock:
                    if self._spring is None:          # no new movement arrived meanwhile
                        self._thread = None
                        return
