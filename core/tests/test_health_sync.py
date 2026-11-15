"""3.12 spánek a kroky z telefonu: sleep fills the sleep habit, steps make (once) and fill a steps habit, never lower."""
from jarvis import habits as hb


def test_sleep_and_steps_from_the_phone(rt):
    hb.seed(rt)
    out = hb.health_sync(rt, None, steps=6400, sleep_h=7.36)
    assert out == {"sleep": 7.4, "steps": 6400}
    items = {i["name"]: i for i in hb.snapshot(rt)["items"]}
    assert items["Spánek"]["value"] == 7.4 and items["Spánek"]["done"]
    assert items["Kroky"]["value"] == 6400 and items["Kroky"]["target"] == 8000 and not items["Kroky"]["done"]
    assert hb.health_sync(rt, None, steps=5000, sleep_h=6) == {}            # less than already there: kept
    hb.health_sync(rt, None, steps=9100)
    items = {i["name"]: i for i in hb.snapshot(rt)["items"]}
    assert items["Kroky"]["done"] and sum(1 for n in items if n == "Kroky") == 1   # one steps habit, not a new one
    assert hb.health_sync(rt, None, steps=-3, sleep_h=40) == {}             # nonsense ignored
