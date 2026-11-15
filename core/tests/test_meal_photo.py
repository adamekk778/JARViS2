"""3.12 Jídlo z fotky: the AI's estimate lands in today's meals with kcal and protein; nonsense is refused."""
import asyncio
import datetime as dt

import pytest

from jarvis import habits as hb

IMG = "data:image/jpeg;base64,/9j/4AAQ"


def test_photo_to_meal_with_kcal(rt, monkeypatch):
    seen = {}

    async def fake(msgs, need_vision=False, **kw):
        seen["vision"] = need_vision
        seen["img"] = msgs[0]["content"][1]["image_url"]["url"]
        return 'Tady: {"food": "Kuře s rýží a brokolicí", "kcal": "650 kcal", "protein": 48, "slot": "obed"}'

    monkeypatch.setattr(rt.router, "complete", fake)
    r = asyncio.run(hb.meal_from_photo(rt, IMG))
    assert r == {"slot": "obed", "label": "Oběd", "food": "Kuře s rýží a brokolicí", "kcal": 650, "protein": 48}
    assert seen == {"vision": True, "img": IMG}
    s = hb.snapshot(rt)
    obed = next(m for m in s["meals"] if m["slot"] == "obed")
    assert obed["text"].startswith("Kuře") and obed["kcal"] == 650
    assert s["nutrition"] == {"kcal": 650, "protein": 48, "known": True}


def test_no_food_or_bad_image(rt, monkeypatch):
    async def none(msgs, need_vision=False, **kw):
        return '{"food": ""}'

    monkeypatch.setattr(rt.router, "complete", none)
    with pytest.raises(ValueError):
        asyncio.run(hb.meal_from_photo(rt, IMG))
    with pytest.raises(ValueError):
        asyncio.run(hb.meal_from_photo(rt, "not an image"))


def test_slot_by_time_of_day():
    at = lambda h: dt.datetime(2026, 11, 15, h, 0)   # noqa: E731
    assert [hb._slot_by_time(at(h)) for h in (8, 12, 16, 19)] == ["snidane", "obed", "svacina", "vecere"]
