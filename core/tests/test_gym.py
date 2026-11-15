"""3.12 Gym deník: sets, the strength line, records, the week, and a set ticks the training habit."""
import asyncio
import datetime as dt

import pytest

from jarvis import gym
from jarvis import habits as hb


def test_names_and_one_rep_max():
    assert gym.name("bench") == gym.name("Bench press") == "Bench press"
    assert gym.name("dřep") == "Dřep" and gym.name("zakopávání") == "Zakopávání"
    assert gym.one_rm(100, 1) == 100 and gym.one_rm(60, 10) == 80.0
    with pytest.raises(ValueError):
        gym.name("  ")


def test_sets_line_records_week_and_training_tick(rt, monkeypatch):
    hb.seed(rt)
    t = dt.date.today()
    monkeypatch.setattr(hb, "today", lambda: t)
    gym.add_set(rt, "bench", 60, 8, day=(t - dt.timedelta(days=14)).isoformat(), sets=3)
    gym.add_set(rt, "bench", 70, 6, day=(t - dt.timedelta(days=7)).isoformat())
    ids = gym.add_set(rt, "benčpres", 75, 6)
    s = gym.snapshot(rt)
    b = next(e for e in s["exercises"] if e["name"] == "Bench press")
    assert b["best"]["weight"] == 75 and b["sets"] == 5 and len(b["points"]) == 3
    assert b["gain"] > 0 and b["pr_today"]
    assert [r["id"] for r in s["today"]] == ids and s["week"]["sets"] >= 1
    training = next(i for i in hb.snapshot(rt)["items"] if i["area"] == "gym")
    assert training["value"] == 1                                     # the set ticked the training habit
    gym.delete_set(rt, ids[0])
    assert gym.snapshot(rt)["today"] == []
    with pytest.raises(ValueError):
        gym.add_set(rt, "bench", 60, 0)
    with pytest.raises(ValueError):
        gym.add_set(rt, "bench", 60, 5, day=(t + dt.timedelta(days=1)).isoformat())


def test_by_voice(rt):
    from jarvis.tools.habit_tools import gym_log

    r = asyncio.run(gym_log(rt, "dřep", 80, 5, sets=3))
    assert r.ok and "Dřep 3× 5" in r.summary
    assert len(gym.snapshot(rt)["today"]) == 3
