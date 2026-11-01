"""3.12: the notch outline is animated by JARVIS itself (one plan per movement, one outline per screen refresh)."""
import time

from jarvis.desktop import regionanim as ra

JS_ROUND = [[712, 8], [720, 9], [728, 14], [733, 21], [734, 30], [734, 30], [733, 39], [728, 46], [720, 51], [712, 53], [538, 53],
            [530, 51], [522, 46], [517, 39], [516, 30], [516, 30], [517, 21], [522, 14], [530, 9], [538, 8]]
JS_NOTCH = [[576, 0], [924, 0], [924, 0], [921, 0], [919, 1], [916, 2], [914, 3], [911, 4], [909, 6], [907, 8], [906, 10], [905, 13],
            [904, 16], [903, 18], [903, 21], [903, 27], [903, 29], [903, 32], [902, 34], [901, 36], [900, 38], [899, 41], [898, 42],
            [897, 44], [895, 46], [893, 48], [891, 49], [890, 50], [887, 51], [885, 52], [883, 53], [881, 54], [878, 54], [876, 54],
            [624, 54], [622, 54], [619, 54], [617, 53], [615, 52], [613, 51], [611, 50], [609, 49], [607, 48], [605, 46], [603, 44],
            [602, 42], [601, 41], [600, 38], [599, 36], [598, 34], [597, 32], [597, 29], [597, 27], [597, 21], [597, 18], [596, 16],
            [595, 13], [594, 11], [593, 8], [591, 6], [589, 4], [587, 3], [584, 2], [581, 1], [579, 0], [576, 0]]


def test_outline_matches_the_page_exactly():
    """Same numbers as web/src/shared/region.ts (roundRect / notchOutline), point for point."""
    assert [list(p) for p in ra.round_rect(412.5, 6, 587.5, 42, 18, 1.25)] == JS_ROUND
    assert [list(p) for p in ra.notch_outline(400, 0, 600, 34, 17.3, 14, 1.5, 2)] == JS_NOTCH
    plan = {"geom": "round", "cx": 500, "top": 6, "dpr": 1.25, "pad": 0}
    assert [list(p) for p in ra.outline(plan, 175, 36, 18)[0]] == JS_ROUND


def test_spring_settles_on_target_like_the_page():
    s = ra.Spring({"from": {"w": 176, "h": 36, "r": 18}, "to": {"w": 780, "h": 400, "r": 36}, "k": 300, "c": 24})
    n, peak = 0, 0.0
    while s.step(1 / 60):
        n += 1
        peak = max(peak, s.x["w"])
    assert s.x == {"w": 780, "h": 400, "r": 36} and 10 < n < 90       # well under 1.5 s at 60 Hz
    assert 780 < peak < 830                                            # a little overshoot when it grows (iOS feel)


def test_animator_one_outline_per_frame_and_retarget():
    frames = []
    clock = [0.0]

    def wait():
        clock[0] += 1 / 60
        time.sleep(0.0005)

    anim = ra.RegionAnimator(frames.append, wait=wait, clock=lambda: clock[0])
    plan = {"geom": "round", "cx": 500, "top": 6, "dpr": 1, "pad": 0, "k": 420, "c": 36,
            "from": {"w": 780, "h": 400, "r": 36}, "to": {"w": 176, "h": 36, "r": 18}}
    anim.start(plan)
    for _ in range(400):
        if not anim.running:
            break
        time.sleep(0.005)
    assert not anim.running and len(frames) > 5
    assert frames[-1] == ra.outline(plan, 176, 36, 18)                 # ends exactly on the closed pill
    widths = [max(x for x, _ in f[0]) - min(x for x, _ in f[0]) for f in frames]
    assert widths == sorted(widths, reverse=True)                      # shrinking: no bounce back
    frames.clear()
    anim.start({**plan, "from": {"w": 176, "h": 36, "r": 18}, "to": {"w": 348, "h": 38, "r": 19}})
    for _ in range(400):
        if not anim.running:
            break
        time.sleep(0.005)
    assert frames and frames[-1] == ra.outline(plan, 348, 38, 19)
