"""Wave 46: attention-aware notices and focus mode, data lens, mission graph + dry run, agent map events, window navigator,
live captions."""
import datetime as dt
import time

from conftest import FakeRouter, drain
from jarvis import tools, uixplus

tools.load_builtin()


def test_focus_defers_and_summarises(rt):
    q = rt.bus.subscribe()
    rt.attention.focus(30)
    assert rt.notify("Nový e-mail", "Od Petra") == 0
    assert rt.notify("Časovač", "Čaj je hotový", urgent=True) >= 0
    evs = drain(q)
    assert [e["title"] for e in evs if e["type"] == "notify"] == ["Časovač"]
    assert any(e["type"] == "focus" and e.get("waiting") == 1 for e in evs)
    assert rt.attention.flush() is None                                   # still focused
    rt.attention.focus(0)
    s = rt.attention.flush()
    assert s and "1 upozornění" in s["title"] and "Od Petra" in s["body"] and not rt.attention.deferred


def test_meeting_counts_as_busy(rt):
    rt.calendar.add("Porada", dt.datetime.now() - dt.timedelta(minutes=5), 30)
    assert rt.attention.busy_reason() == "schůzka v kalendáři"
    rt.cfg.stark.attention_aware = False
    assert rt.attention.busy_reason() == ""


async def test_focus_tool(rt):
    r = await tools.call("focus_mode", {"minutes": 25}, rt)
    assert r.ok and rt.attention.busy_reason() == "soustředění"
    rt.notify("Zpráva", "ahoj")
    r = await tools.call("focus_mode", {"minutes": 0}, rt)
    assert r.ok and "1 upozornění" in r.summary


def test_lens():
    items = {i["kind"]: i for i in uixplus.lens("Faktura 1 250 EUR, splatná 15. 11. 2026, IČO 27082440, váha 12 kg, barva #4f8dff", dt.date(2026, 11, 1))}
    assert items["měna"]["value"] == "≈ 31 625 Kč" and items["datum"]["value"].startswith("za 14 dní")
    assert items["IČO"]["value"] == "kontrolní číslice sedí" and items["jednotky"]["value"] == "26.46 lb" and items["barva"]["color"] == "#4f8dff"
    bad = {i["kind"]: i for i in uixplus.lens("IČO: 12345678")}
    assert bad["IČO"]["value"].startswith("NEPLATNÉ")
    nums = {i["kind"]: i for i in uixplus.lens("10\n20\n30\n40")}
    assert nums["čísla"]["value"] == "součet 100, průměr 25, min 10, max 40"
    iban = {i["kind"]: i for i in uixplus.lens("Účet CZ65 0800 0000 1920 0014 5399")}
    assert iban["IBAN"]["value"] == "platný"
    assert uixplus.lens("ahoj") == []
    t = {i["kind"]: i for i in uixplus.lens("Teplota 100 °F venku")}
    assert t["jednotky"]["value"] == "37.78 °C"


async def test_selection_carries_lens(rt, monkeypatch):
    from jarvis import powers

    monkeypatch.setattr(powers, "grab_selection", lambda rt_: ("Cena 99 USD", {"app": "Chrome"}))
    q = rt.bus.subscribe()
    await powers.selection_menu(rt)
    ev = next(e for e in drain(q) if e["type"] == "selection")
    assert ev["lens"][0]["kind"] == "měna"
    r = await tools.call("data_lens", {"text": "Cena 99 USD"}, rt)
    assert r.ok and "Kč" in r.summary


def test_step_layers_and_sim():
    steps = [{"tool": "web_search", "args": {}}, {"tool": "open_app", "args": {}, "needs": []}, {"say": "hotovo", "needs": [0, 1]},
             {"ask": "shrň", "needs": [2]}]
    g = uixplus.step_layers(steps)
    assert g["layers"] == [[0, 1], [2], [3]] and g["parallel"] == 2 and {"from": 0, "to": 2} in g["edges"] and not g["problems"]
    seq = uixplus.step_layers([{"tool": "a"}, {"tool": "b"}, {"tool": "c"}])
    assert seq["layers"] == [[0], [1], [2]]
    loop = uixplus.step_layers([{"tool": "a", "needs": [1]}, {"tool": "b", "needs": [0]}, {"tool": "c", "needs": [7]}])
    assert any("smyčka" in p for p in loop["problems"]) and any("neexistující krok 8" in p for p in loop["problems"])
    sim = uixplus.simulate(steps, lambda n, a: f"udělá {n}", lambda n, a: n == "open_app", lambda n: "Aplikace")
    assert sim[1]["asks"] and sim[3]["kind"] == "úkol pro AI" and sim[2]["label"] == "Řekne: hotovo"
    assert uixplus.critical_seconds(sim, g) == 6 + 2 + 20                      # parallel start: max(6, 3), then 2, then 20


async def test_mission_simulate_ws(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "mission_simulate", "id": "rano"})
        for _ in range(30):
            m = ws.receive_json()
            if m["type"] == "mission_sim":
                break
        assert m["name"] and m["steps"][0]["label"] and m["graph"]["layers"]


async def test_agent_activity_events(rt):
    from jarvis import agents

    rt.router = FakeRouter(["Hotová analýza."])
    q = rt.bus.subscribe()
    r = await agents.run(rt, "vyzkum", "zjisti cenu mléka")
    evs = [e for e in drain(q) if e["type"] == "agent_activity"]
    assert r["ok"] and [e["state"] for e in evs] == ["start", "done"] and evs[0]["name"] == "Výzkum" and evs[1]["ok"]


def test_window_navigator():
    wins = [{"hwnd": 1, "title": "Word", "app": "Word", "x": 0, "y": 0, "w": 960, "h": 1080, "state": "normal"},
            {"hwnd": 2, "title": "Chrome", "app": "Chrome", "x": 960, "y": 0, "w": 960, "h": 540, "state": "normal"},
            {"hwnd": 3, "title": "Spotify", "app": "Spotify", "x": 960, "y": 540, "w": 960, "h": 540, "state": "normal"},
            {"hwnd": 4, "title": "Skryté", "app": "X", "x": 0, "y": 0, "w": 100, "h": 100, "state": "minimized"}]
    m = uixplus.window_map(wins, (1920, 1080))
    assert [w["hwnd"] for w in m] == [1, 2, 3] and m[1]["x"] == 0.5 and m[2]["h"] == 0.5
    assert uixplus.neighbour(m, 1, "right")["hwnd"] == 2
    assert uixplus.neighbour(m, 2, "down")["hwnd"] == 3 and uixplus.neighbour(m, 3, "up")["hwnd"] == 2
    assert uixplus.neighbour(m, 3, "left")["hwnd"] == 1 and uixplus.neighbour(m, 1, "left") is None


async def test_window_switch_tool(rt, monkeypatch):
    wins = [{"hwnd": 1, "title": "A", "app": "A", "x": 0, "y": 0, "w": 960, "h": 1080}, {"hwnd": 2, "title": "B", "app": "B", "x": 960, "y": 0, "w": 960, "h": 1080}]
    monkeypatch.setattr(rt.platform, "window_layout", lambda: wins)
    monkeypatch.setattr(rt.platform, "foreground_info", lambda: {"hwnd": 1})
    seen = []
    monkeypatch.setattr(rt.platform, "focus_window", lambda h_: seen.append(h_) or True)
    r = await tools.call("window_switch", {"direction": "vpravo"}, rt)
    assert r.ok and seen == [2]


def test_captions():
    ch = uixplus.caption_chunks("Dobré ráno. Dnes bude slunečno a teplo kolem dvaceti stupňů, odpoledne přijde vítr od západu a večer možná přeháňky.", 50)
    assert ch[0] == "Dobré ráno." and all(len(c) <= 50 for c in ch) and " ".join(ch).endswith("přeháňky.")
    t = uixplus.caption_timing(ch)
    assert t[0]["at"] == 0 and t[1]["at"] == t[0]["duration"] and all(x["duration"] >= 1.2 for x in t)


def test_speak_publishes_captions_only_when_enabled(rt):
    q = rt.bus.subscribe()
    rt.speaker = None
    rt.speak("Ahoj.")
    assert not [e for e in drain(q) if e["type"] == "caption"]
    rt.cfg.appearance.captions = True
    rt.speak("Ahoj, jak se máš?")
    caps = [e for e in drain(q) if e["type"] == "caption"]
    assert caps and caps[0]["lines"][0]["text"] == "Ahoj, jak se máš?" and time.time()
