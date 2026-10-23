import random

from jarvis.desktop.pet import GRAVITY, SLEEP_AFTER, PetSim, Rect

WORK = Rect(0, 0, 1920, 1040)  # taskbar top at y=1040


def run(sim, seconds, platforms=None, dt=1 / 30):
    frames = []
    for _ in range(int(seconds / dt)):
        frames.append(sim.step(dt, platforms))
    return frames


def test_walks_and_turns_at_screen_edge():
    sim = PetSim(WORK, rng=random.Random(1), start_x=60)
    sim.action, sim.facing, sim.timer = "walk", -1, 100
    sim.last_interaction = 0
    run(sim, 3)
    assert sim.facing == 1 and sim.x >= 48  # turned around instead of leaving the screen


def test_never_leaves_work_area_negative_monitor():
    work = Rect(-1920, 0, 1920, 1080)
    sim = PetSim(work, rng=random.Random(2))
    for _ in range(30):
        frames = run(sim, 10)
        sim.interact()
        assert all(-1920 + 48 <= f.x <= -48 and f.y <= 1080 for f in frames)


def test_falls_when_window_disappears_and_lands_on_taskbar():
    win = Rect(500, 600, 600, 400)
    sim = PetSim(WORK, rng=random.Random(3), start_x=800)
    sim.set_platforms([win])
    sim.y = 600
    sim.action, sim.timer = "sit", 100
    run(sim, 0.2, [win])
    assert sim.y == 600  # sitting on the window
    run(sim, 2, [])       # window closed
    assert sim.y == WORK.bottom and sim.action in ("idle", "walk", "sit", "jump")


def test_jumps_onto_window_within_reach():
    win = Rect(700, 800, 600, 300)
    rng = random.Random(4)
    sim = PetSim(WORK, rng=rng, start_x=650)
    sim.set_platforms([win])
    tx, ty = sim._jump_target()
    assert ty == 800
    sim._start_jump(tx, ty)
    run(sim, 1.0, [win])
    assert abs(sim.y - 800) < 1 and 700 <= sim.x <= 1300


def test_ignores_maximized_like_or_tiny_windows():
    sim = PetSim(WORK)
    sim.set_platforms([Rect(0, 0, 1920, 1040), Rect(100, 500, 120, 300)])
    assert len(sim.surfaces) == 1  # only the taskbar


def test_drag_release_falls_and_lands():
    sim = PetSim(WORK, rng=random.Random(5))
    sim.grab()
    sim.drag_to(300, 400)
    assert (sim.x, sim.y) == (300, 400) and sim.action == "held"
    assert sim.release() == "landed"
    run(sim, (2 * (1040 - 400) / GRAVITY) ** 0.5 + 0.3)
    assert sim.y == WORK.bottom


def test_release_near_notch_returns_home():
    sim = PetSim(WORK, notch_point=(960, 0))
    sim.grab()
    sim.drag_to(965, 130)
    assert sim.release() == "return"
    run(sim, 1.5)
    assert sim.docked


def test_focus_only_sits():
    sim = PetSim(WORK, rng=random.Random(6))
    sim.set_focus(True)
    actions = {f.action for f in run(sim, 60)}
    assert actions <= {"idle", "sit"}


def test_sleeps_after_inactivity_and_wakes():
    sim = PetSim(WORK, rng=random.Random(7))
    run(sim, SLEEP_AFTER + 30, dt=0.1)
    assert sim.action == "sleep"
    sim.interact()
    assert sim.action == "idle"
