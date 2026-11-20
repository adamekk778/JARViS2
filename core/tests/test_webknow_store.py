"""JARVIS knows the internet – the local store of what JARVIS saw (spec 2026-11-20 §5.1)."""
import time

from jarvis.webknow.store import Doc, normalize_url


def test_normalize_url_strips_tracking():
    assert normalize_url("https://WWW.Example.com/a?utm_source=x&id=5&fbclid=y#top") == "https://www.example.com/a?id=5"


def test_add_dedupes_and_finds_inflected_czech(rt):
    a = rt.webknow.add(Doc(url="https://x.cz/a?utm_source=1", title="Wimbledon vyhrála Vondroušová", kind="news",
                           snippet="Česká tenistka slaví."))
    assert rt.webknow.add(Doc(url="https://x.cz/a", title="Wimbledon vyhrála Vondroušová", kind="news")) == a
    hits = rt.webknow.search("kdo vyhrál wimbledonu")
    assert hits[0]["id"] == a and hits[0]["matched"] == 2


def test_same_headline_from_two_sources_is_one_news_doc(rt):
    a = rt.webknow.add(Doc(url="https://a.cz/1", title="Vláda schválila rozpočet", kind="news"))
    assert rt.webknow.add(Doc(url="https://b.cz/2", title="Vláda schválila rozpočet", kind="news")) == a


def test_private_mode_stores_nothing(rt):
    rt.memory.set_private(True)
    assert rt.webknow.add(Doc(url="https://x.cz/p", title="tajné", kind="read")) is None
    assert rt.webknow.stats()["by_kind"] == {}


def test_prune_by_kind_age_and_forget_domain(rt):
    old = time.time() - 40 * 86400
    n = rt.webknow.add(Doc(url="https://a.cz/n", title="stará zpráva", kind="news"))
    s = rt.webknow.add(Doc(url="https://a.cz/s", title="staré hledání", kind="search"))
    rt.db.exec("UPDATE web_docs SET fetched=? WHERE id IN (?,?)", (old, n, s))
    assert rt.webknow.prune() == 1 and rt.webknow.get(n) is None and rt.webknow.get(s)
    assert rt.webknow.forget(domain="a.cz") == 1 and rt.webknow.search("hledání") == []


def test_cap_drops_oldest_news_first(rt):
    rt.webknow.add(Doc(url="https://a.cz/1", title="zprava jedna", kind="news", text="x" * 5000))
    keep = rt.webknow.add(Doc(url="https://a.cz/2", title="clanek", kind="read", text="y" * 10))
    rt.webknow.prune(cap_bytes=1000)
    assert rt.webknow.stats()["by_kind"].get("news", 0) == 0 and rt.webknow.get(keep)


def test_interval_never_below_15(rt):
    from jarvis import config
    assert config.apply_patch(rt.cfg, {"webknow": {"interval_min": 1}}).webknow.interval_min == 15


def test_digest_and_notes_roundtrip(rt):
    rt.webknow.add_digest("sport", "Sparta vyhrála.")
    rt.webknow.add_digest("", "Celkově klid.")
    assert rt.webknow.latest_digest("sport")["text"] == "Sparta vyhrála." and rt.webknow.latest_digest()["text"] == "Celkově klid."
    a = rt.webknow.set_notes("Valorant", "první")
    assert rt.webknow.set_notes("valorant", "druhý") == a and rt.webknow.notes("Valorant")["text"] == "druhý"
