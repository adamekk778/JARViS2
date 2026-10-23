"""Desktop pet physics (spec §6). Pure logic: no Windows calls, driven by the host at ~30 Hz.

Coordinates are screen pixels; (x, y) is the bottom-centre of the pet (its "feet").
Surfaces are horizontal lines the pet can stand on: the top of the taskbar (bottom of the work area)
and the top edges of normal windows.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

WALK_SPEED = 40.0
GRAVITY = 1800.0
JUMP_REACH_X = 250.0
JUMP_REACH_UP = 400.0
JUMP_TIME = 0.6
IDLE_RANGE = (3.0, 12.0)
SLEEP_AFTER = 300.0
RETURN_SPEED = 900.0
DOCK_RADIUS = 80.0


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


@dataclass(frozen=True)
class Surface:
    left: float
    right: float
    y: float
    ground: bool = False


@dataclass
class PetFrame:
    x: float
    y: float
    action: str
    facing: int


class PetSim:
    def __init__(self, work: Rect, size: int = 96, rng: random.Random | None = None,
                 notch_point: tuple[int, int] | None = None, start_x: float | None = None):
        self.work = work
        self.size = size
        self.rng = rng or random.Random()
        self.notch_point = notch_point or (work.x + work.w // 2, work.y)
        self.x = float(start_x if start_x is not None else work.x + work.w / 2)
        self.y = float(work.bottom)
        self.vx = 0.0
        self.vy = 0.0
        self.facing = 1
        self.action = "idle"
        self.timer = self.rng.uniform(*IDLE_RANGE)
        self.t = 0.0
        self.last_interaction = 0.0
        self.focus = False
        self.docked = False
        self.surfaces: list[Surface] = [self._ground()]

    # ---------- surfaces ----------
    def _ground(self) -> Surface:
        return Surface(self.work.x, self.work.right, self.work.bottom, ground=True)

    def set_platforms(self, platforms: list[Rect]) -> None:
        half = self.size / 2
        out = [self._ground()]
        for p in platforms[:15]:
            left, right = max(p.x, self.work.x), min(p.right, self.work.right)
            # needs room for the pet above it and must be inside the work area
            if right - left < max(200, self.size) or p.y < self.work.y + self.size or p.y >= self.work.bottom - 4:
                continue
            out.append(Surface(left + half * 0.2, right - half * 0.2, float(p.y)))
        self.surfaces = out

    def _support(self) -> Surface | None:
        for s in self.surfaces:
            if abs(self.y - s.y) <= 2 and s.left <= self.x <= s.right:
                return s
        return None

    def _clamp(self) -> None:
        half = self.size / 2
        self.x = min(max(self.x, self.work.x + half), self.work.right - half)
        self.y = min(max(self.y, self.work.y + self.size), self.work.bottom)

    # ---------- user interaction ----------
    def interact(self) -> None:
        self.last_interaction = self.t
        if self.action == "sleep":
            self._set("idle")

    def set_focus(self, on: bool) -> None:
        self.focus = on
        if on and self.action in ("walk", "jump"):
            pass  # finish the current move, then sit

    def grab(self) -> None:
        self.interact()
        self._set("held")
        self.vx = self.vy = 0.0

    def drag_to(self, x: float, y: float) -> None:
        if self.action == "held":
            dx = x - self.x
            if abs(dx) > 1:
                self.facing = 1 if dx > 0 else -1
            self.x, self.y = float(x), float(y)
            self._clamp()

    def release(self) -> str:
        self.interact()
        if math.dist((self.x, self.y - self.size / 2), self.notch_point) < DOCK_RADIUS + self.size / 2:
            self._set("return")
            return "return"
        self._set("fall")
        self.vy = 0.0
        return "landed"

    def go_home(self) -> None:
        self._set("return")

    # ---------- simulation ----------
    def _set(self, action: str, timer: float | None = None) -> None:
        self.action = action
        if timer is not None:
            self.timer = timer

    def _choose(self) -> None:
        if self.focus:
            self._set("sit", self.rng.uniform(*IDLE_RANGE))
            return
        if self.t - self.last_interaction > SLEEP_AFTER:
            self._set("sleep")
            return
        target = self._jump_target()
        options = [("walk", 0.45), ("idle", 0.25), ("sit", 0.15)] + ([("jump", 0.15)] if target else [])
        r = self.rng.random() * sum(w for _, w in options)
        for name, w in options:
            r -= w
            if r <= 0:
                break
        if name == "walk":
            if self.rng.random() < 0.4:
                self.facing *= -1
            self._set("walk", self.rng.uniform(2.0, 8.0))
        elif name == "jump" and target:
            self._start_jump(*target)
        else:
            self._set(name, self.rng.uniform(*IDLE_RANGE))

    def _jump_target(self) -> tuple[float, float] | None:
        cands = []
        for s in self.surfaces:
            if s.ground and abs(self.y - s.y) <= 2:
                continue
            if abs(self.y - s.y) <= 2:
                continue  # same height (the surface we stand on)
            tx = min(max(self.x, s.left + 10), s.right - 10)
            if abs(tx - self.x) <= JUMP_REACH_X and 0 < self.y - s.y <= JUMP_REACH_UP:
                cands.append((tx, s.y))
            elif s.ground is False and s.y > self.y and abs(tx - self.x) <= JUMP_REACH_X:
                cands.append((tx, s.y))  # hop down onto a lower window
        return self.rng.choice(cands) if cands else None

    def _start_jump(self, tx: float, ty: float) -> None:
        T = JUMP_TIME
        self.vx = (tx - self.x) / T
        aim = ty - 24 if ty < self.y else ty  # aim a bit above a higher ledge so we come down onto it
        self.vy = (aim - self.y - 0.5 * GRAVITY * T * T) / T
        if abs(self.vx) > 1:
            self.facing = 1 if self.vx > 0 else -1
        self._set("jump")

    def _airborne(self, dt: float) -> None:
        prev_y = self.y
        self.x += self.vx * dt
        self.y += self.vy * dt + 0.5 * GRAVITY * dt * dt  # exact for constant gravity
        self.vy += GRAVITY * dt
        if self.vy > 0:
            for s in sorted(self.surfaces, key=lambda s: s.y):
                if prev_y <= s.y + 1 and self.y >= s.y and s.left <= self.x <= s.right:
                    self.y = s.y
                    self.vx = self.vy = 0.0
                    self._set("idle", self.rng.uniform(0.6, 2.0))  # small "plop" pause
                    break
        if self.y >= self.work.bottom:  # never fall through the taskbar
            self.y = float(self.work.bottom)
            self.vx = self.vy = 0.0
            if self.action in ("jump", "fall"):
                self._set("idle", self.rng.uniform(0.6, 2.0))

    def step(self, dt: float, platforms: list[Rect] | None = None) -> PetFrame:
        dt = min(dt, 0.1)
        self.t += dt
        if platforms is not None:
            self.set_platforms(platforms)
        a = self.action
        if a == "held":
            pass
        elif a == "return":
            nx, ny = self.notch_point
            ty = ny + self.size  # feet just below the notch
            d = math.dist((self.x, self.y), (nx, ty))
            if d < 12:
                self.x, self.y = float(nx), float(ty)
                self.docked = True
            else:
                k = min(1.0, RETURN_SPEED * dt / d)
                self.x += (nx - self.x) * k
                self.y += (ty - self.y) * k
            return PetFrame(self.x, self.y, "return", self.facing)
        elif a in ("jump", "fall"):
            self._airborne(dt)
        else:
            if self._support() is None:
                self.vx = 0.0
                self.vy = 0.0
                self._set("fall")
                self._airborne(dt)
            elif a == "walk":
                s = self._support()
                half = self.size / 2
                self.x += self.facing * WALK_SPEED * dt
                left, right = s.left + (half if s.ground else 0), s.right - (half if s.ground else 0)
                if self.x <= left or self.x >= right:
                    if s.ground or self.rng.random() < 0.5:
                        self.x = min(max(self.x, left), right)
                        self.facing *= -1
                    # else: walk off the window edge and fall next step
                self.timer -= dt
                if self.timer <= 0:
                    self._set("idle", self.rng.uniform(*IDLE_RANGE))
            elif a == "sleep":
                if self.t - self.last_interaction <= SLEEP_AFTER:
                    self._set("idle", 1.0)
            else:  # idle, sit
                self.timer -= dt
                if self.timer <= 0 or (self.focus and a != "sit"):
                    self._choose()
        self._clamp()
        return PetFrame(self.x, self.y, self.action, self.facing)
