"""3.12 Údržba sama od sebe: a check after an update, a daily key check, a summary without secrets."""
import asyncio

import pytest

from jarvis import secrets, upkeep


@pytest.fixture
def rt(tmp_path, monkeypatch):
    from jarvis.runtime import Runtime

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    r = Runtime(persist_config=False)
    r.notes = []
    monkeypatch.setattr(r, "notify", lambda title, body, **k: r.notes.append((title, body)))
    return r


def test_after_an_update_the_check_runs_once_and_says_what_is_broken(rt, monkeypatch):
    from jarvis import selfcheck

    async def fake_run(rt_, tester):
        return [{"key": "brain", "name": "Mozek (AI)", "ok": False, "detail": "je zapnutý režim Jen offline"},
                {"key": "loopback", "name": "Zvuk z PC", "ok": False, "detail": "nic nehraje"},
                {"key": "internet", "name": "Internet", "ok": True, "detail": "ok"}]

    monkeypatch.setattr(selfcheck, "run", fake_run)
    bad = asyncio.run(upkeep.after_update(rt, delay=0))
    assert [b["key"] for b in bad] == ["brain"]                    # "nothing plays" is no reason for a notice
    assert rt.notes and "1 věc nejde" in rt.notes[0][0] and "Jen offline" in rt.notes[0][1]
    assert asyncio.run(upkeep.after_update(rt, delay=0)) is None   # once per version


def test_daily_key_check_reports_only_broken_keys(rt, monkeypatch):
    from jarvis import brainkey
    from jarvis.llm import quota

    monkeypatch.setattr(quota, "overview", lambda rt_: [
        {"id": "groq", "label": "Groq", "enabled": True, "key": True, "local": False},
        {"id": "gemini", "label": "Gemini", "enabled": True, "key": True, "local": False},
        {"id": "ollama", "label": "Ollama", "enabled": True, "key": True, "local": True}])

    async def fake_test(rt_, pid):
        return {"groq": {"ok": False, "message": "HTTP 401: invalid api key"},
                "gemini": {"ok": False, "message": "HTTP 503: high demand"}}.get(pid, {"ok": True})

    monkeypatch.setattr(brainkey, "provider_test", fake_test)
    broken = asyncio.run(upkeep.check_keys(rt))
    assert [b["id"] for b in broken] == ["groq"]                   # busy Gemini is not broken; Ollama is not tried


def test_summary_never_contains_a_key(rt, monkeypatch):
    store = {"groq": "gsk_THISISASECRETKEY1234567890abcdef", "conn.supabase.token": "sbp_supersecret0000000000"}
    monkeypatch.setattr(secrets, "get", lambda k: store.get(k, ""))
    text = upkeep.summary(rt)
    assert "JARVIS" in text and "Jen offline" in text
    assert "gsk_THISIS" not in text and "sbp_super" not in text
