"""3.20 Přístupnost+ (461–480)."""
from __future__ import annotations

import json

import pytest

from jarvis import accessx, tools


def test_language_packs(rt):
    sk = accessx.ui_pack("sk")
    assert sk["Nastavení"] == "Nastavenia" and accessx.ui_pack("uk")["Zavřít"] == "Закрити"
    assert accessx.ui_pack("cs") == {} and accessx.ui_pack("xx") == {}
    n = accessx.save_pack("pl", {"Nastavení": "Ustawienia!", "Nová věc": "Nowa rzecz", "<b>": "x", "Zlé": "<script>", "": "y", 5: "z"})
    assert n == 3                                  # the markup one is dropped
    pl = accessx.ui_pack("pl")
    assert pl["Nastavení"] == "Ustawienia!" and pl["Nová věc"] == "Nowa rzecz" and "Zlé" not in pl
    with pytest.raises(ValueError):
        accessx.save_pack("en", {"a": "b"})
    with pytest.raises(ValueError):
        accessx.clean_pack(["nope"])
    assert set(accessx.UI_LANGS) == {"cs", "en", "sk", "de", "pl", "uk"} and accessx.ANSWER_RULE["pl"].startswith("Odpowiadaj")


def test_i18n_routes(rt, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from jarvis import paths
    from jarvis.server.app import create_app

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "i18n-keys.json").write_text(json.dumps(["Nastavení", "Zavřít"]), encoding="utf-8")
    (dist / "i18n-en.json").write_text(json.dumps({"Nastavení": "Settings"}), encoding="utf-8")
    monkeypatch.setattr(paths, "web_dist", lambda: dist)
    c = TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000))
    assert c.get("/api/i18n-keys").json() == ["Nastavení", "Zavřít"]
    assert c.get("/api/i18n/en").json() == {"Nastavení": "Settings"}
    assert c.get("/api/i18n/de").json()["Zavřít"] == "Schließen"
    assert c.get("/api/i18n/xx").status_code == 404
    assert c.post("/api/i18n/de", json={"Zavřít": "Zumachen"}).json() == {"ok": True, "saved": 1}
    assert c.get("/api/i18n/de").json()["Zavřít"] == "Zumachen"
    assert "Překlad rozhraní" in c.get("/translate").text
    guest = TestClient(create_app(rt, manage_runtime=False), client=("85.1.2.3", 5000))
    assert guest.post("/api/i18n/de", json={"Zavřít": "x"}).status_code in (401, 403)


def test_labels_zoom_flash_errors():
    d = accessx.parse_label('Text {"nazev": "Müsli", "cena": "79,90 Kč", "cena_za_jednotku": "159,80 Kč/kg", "slozeni": "ovesné vločky, '
                            'LÍSKOVÉ OŘECHY", "alergeny": ["lepek", "ořechy"], "spotrebujte_do": "12. 3. 2027", "varovani": null}', ["ořechy", "mléko"])
    assert d["pozor"] == ["ořechy"]
    t = accessx.label_text(d)
    assert t.startswith("POZOR") and "79,90 Kč (159,80 Kč/kg)" in t and "12. 3. 2027" in t
    with pytest.raises(ValueError):
        accessx.parse_label("nic")
    assert accessx.zoom_action("přibliž tohle") == "in" and accessx.zoom_action("oddal") == "out" and accessx.zoom_action("vypni lupu") == "off"
    assert accessx.should_flash("Zvonek", "Někdo zvoní", False) and accessx.should_flash("x", "y", True)
    assert not accessx.should_flash("Nová zpráva", "Ahoj", False)
    e = accessx.explain_error(ConnectionError("Name or service not known"))
    assert "internet" in e["what"]
    assert "klíč" in accessx.error_text("HTTP 401 Unauthorized") and "Zkus to znovu" in accessx.error_text("divná věc")


async def test_flash(rt):
    calls = []

    class Home:
        async def service(self, domain, svc, data):
            calls.append((domain, svc, data["entity_id"]))
            if data["entity_id"] == "light.stara":
                if svc == "turn_on":
                    raise RuntimeError("no flash")

    rt.home = Home()
    assert await accessx.flash(rt, ["light.obyvak", "light.stara"]) == 2
    assert calls[0] == ("light", "turn_on", "light.obyvak") and calls.count(("homeassistant", "toggle", "light.stara")) == 3


def test_volume_and_noise():
    assert accessx.volume_for_noise(None) == 50 and accessx.volume_for_noise(30) == 40
    assert accessx.volume_for_noise(70) == 85 and 50 < accessx.volume_for_noise(52) < 85
    import numpy as np

    quiet = accessx.rms_db(np.zeros(100))
    loud = accessx.rms_db(np.full(100, 0.5))
    assert loud > quiet and 80 < loud < 95


def test_auto_volume_in_prosody(rt):
    from jarvis.voice import style

    rt.cfg.voice.auto_volume = True

    class V:
        _floor = 3000.0                          # a noisy room

    rt.voice = V()
    assert style.noise_boost(rt, rt.cfg.voice) > 10
    rt.cfg.voice.auto_volume = False
    assert style.noise_boost(rt, rt.cfg.voice) == 0


def test_predictor(rt):
    p = accessx.Predictor()
    for s in ("zhasni v kuchyni", "zhasni v obýváku", "zhasni v kuchyni a zapni rádio", "zapni rádio Impuls"):
        p.learn(s)
    assert p.next("zhasni v ")[0] == "kuchyni"
    assert p.next("zap") == ["zapni"]
    assert p.next("zapni rádio ") == ["impuls"]
    assert isinstance(accessx.predictor(rt).next("pošli "), list)          # learns from the stored messages (none here)


def test_predict_route(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    rt._predictor = accessx.Predictor()
    rt._predictor.learn("dobré ráno jarvisi")
    import time

    rt._predictor_at = time.time()
    c = TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000))
    assert c.get("/api/predict", params={"q": "dobré "}).json() == {"words": ["ráno"]}


def test_dialect_prompt_and_human_tool_errors(rt):
    assert "šak" in accessx.DIALECT_PROMPT


async def test_tool_errors_are_human(rt):
    from jarvis.tools.base import REGISTRY, tool

    @tool("_boom_test", "test")
    async def boom(ctx) -> None:
        raise PermissionError("Access is denied")

    try:
        r = await tools.call("_boom_test", {}, rt)
        assert not r.ok and r.summary.startswith("Na tohle nemám oprávnění.") and "technicky: PermissionError" in r.summary
    finally:
        REGISTRY.pop("_boom_test", None)


async def test_access_kit(rt):
    r = await tools.call("access_kit", {"action": "zoom", "text": "přibliž"}, rt)
    assert r.ok and ("hotkey", (["win", "+"],)) in rt.platform.calls or any(c[0] == "hotkey" for c in rt.platform.calls)
    r = await tools.call("access_kit", {"action": "language", "text": "polsky"}, rt)
    assert r.ok and rt.cfg.general.language == "pl" and rt.cfg.voice.tts_voice == "pl-PL-MarekNeural"
    r = await tools.call("access_kit", {"action": "language", "text": "čeština"}, rt)
    assert r.ok and rt.cfg.general.language == "cs"
    r = await tools.call("access_kit", {"action": "flash"}, rt)
    assert not r.ok and "Nastav" in r.summary
    r = await tools.call("access_kit", {"action": "label"}, rt)
    assert not r.ok
