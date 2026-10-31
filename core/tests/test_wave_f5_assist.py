"""Wave F5f: clipboard history on the phone (138 / 408), automation templates (151), power-aware animations (240 / 255 /
764), IoT overview (165), interpreter (269), tone / languages (547 / 548), research notebook (380), spec audit (630),
picture → data (277 / 276 / 278), screenshot → prototype (353)."""
import json
from pathlib import Path

from conftest import FakeRouter

from jarvis import tools
from jarvis.tools import assist_tools as at

tools.load_builtin()


def test_clipboard_history_over_ws(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    rt.activity.clips.appendleft({"text": "Adresa: Lipová 12, Brno", "ts": 1_800_000_000.0, "app": "Word"})
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "clipboard_history_get"})
        m = next(x for x in iter(ws.receive_json, None) if x["type"] == "clipboard_history")
        assert m["items"][0]["text"] == "Adresa: Lipová 12, Brno"
    rt.update_config({"phone": {"allowed": ["apps"]}})
    with TestClient(create_app(rt, manage_runtime=False), client=("192.168.1.9", 5000)) as c, \
            c.websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:
        ws.send_json({"type": "clipboard_history_get"})
        m = next(x for x in iter(ws.receive_json, None) if x["type"] in ("clipboard_history", "error"))
        assert m["type"] == "error"


def test_templates_and_auto_motion_in_ui():
    web = Path(__file__).resolve().parents[2] / "web" / "src"
    a = (web / "dashboard" / "automations.ts").read_text(encoding="utf-8")
    assert "export const TEMPLATES" in a and a.count('a: T("') >= 8
    b = (web / "shared" / "base.ts").read_text(encoding="utf-8")
    assert 'motionPref === "auto" && onBattery' in b and "export function applyPower" in b


def test_power_state_in_welcome(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    rt.on_battery = True
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c, c.websocket_connect("/ws") as ws:
        m = next(x for x in iter(ws.receive_json, None) if x["type"] == "welcome")
        assert m["power"] == {"on_battery": True}
    rt.update_config({"appearance": {"animations": "auto"}})
    assert rt.cfg.appearance.animations == "auto"


async def test_iot_overview_without_home(rt):
    r = await tools.REGISTRY["iot_overview"].func(rt)
    assert r.ok and "síti" in r.summary or "síť" in r.summary


async def test_interpreter_and_tone(rt):
    rt.router = FakeRouter(["Where is the train station?"])
    r = await tools.REGISTRY["interpret"].func(rt, "Kde je nádraží?", speak=False)
    assert r.ok and r.data["from"] == "cs" and r.data["to"] == "en" and "station" in r.summary
    rt.router = FakeRouter([json.dumps({"cs": "Dobrý den, schůzka je 12. 5. v 10 hodin.", "en": "Hello, the meeting is on May 12 at 10 am."})])
    r = await tools.REGISTRY["draft_message"].func(rt, "čau, sraz 12.5. v 10", "formální", ["cs", "en"])
    assert r.ok and set(r.data["versions"]) == {"cs", "en"} and r.data["missing_numbers"] == []


async def test_research_notebook(rt):
    await tools.REGISTRY["research_note"].func(rt, "Baterie", "Li-ion stárnou rychleji v teple.", "https://example.org/a", "40 °C zdvojnásobí stárnutí")
    await tools.REGISTRY["research_note"].func(rt, "baterie", "Nabíjení do 80 % prodlužuje životnost.", "https://example.org/b")
    await tools.REGISTRY["research_note"].func(rt, "Baterie", "Hluboké vybití škodí.", "https://example.org/a")
    r = await tools.REGISTRY["research_note"].func(rt, "Baterie", export=True)
    md = Path(r.data["path"]).read_text(encoding="utf-8")
    assert "- Li-ion stárnou rychleji v teple. [1]" in md and "- Hluboké vybití škodí. [1]" in md and "2. https://example.org/b" in md
    assert "> „40 °C zdvojnásobí stárnutí“" in md


def test_spec_audit():
    items = at.spec_items("# Zadání\n1. Přihlášení uživatele heslem\n2. Export faktur do PDF\n- [ ] Tmavý režim aplikace\n### Platby kartou\n")
    assert items == ["Přihlášení uživatele heslem", "Export faktur do PDF", "Tmavý režim aplikace", "Platby kartou"]
    corpus = "def prihlaseni_uzivatele(heslo): ...  # login s heslem\nexport faktury pdf generator\ntheme: tmavy rezim aplikace"
    r = {x["item"]: x["state"] for x in at.audit_spec(items, corpus)}
    assert r["Export faktur do PDF"] == "nalezeno" and r["Platby kartou"] == "chybí"


async def test_picture_to_table(rt, tmp_path):
    from PIL import Image

    p = tmp_path / "tab.png"
    Image.new("RGB", (10, 10)).save(p)
    rt.router = FakeRouter([json.dumps({"rows": [["Měsíc", "Tržby"], ["leden", "120"], ["únor", "150"]]})])
    r = await tools.REGISTRY["picture_to_data"].func(rt, str(p), "table")
    assert r.ok and Path(r.data["path"]).read_text(encoding="utf-8-sig").splitlines()[1] == "leden;120"
    rt.router = FakeRouter([json.dumps({"title": "Tržby", "series": [{"name": "2026", "points": [[1, 10], [2, 12], [3, 14], [4, 16], [5, 18], [6, 20]]}]})])
    r = await tools.REGISTRY["picture_to_data"].func(rt, str(p), "chart")
    assert r.ok and "Tržby" in r.summary


async def test_screenshot_to_prototype(rt, tmp_path):
    from PIL import Image

    p = tmp_path / "navrh.png"
    Image.new("RGB", (10, 10)).save(p)
    rt.router = FakeRouter(["Nahoře modrá lišta s nadpisem Kavárna, pod ní tlačítko Rezervovat.",
                            "<!doctype html><html><body><h1>Kavárna</h1><button>Rezervovat</button></body></html>"])
    r = await tools.REGISTRY["screenshot_to_prototype"].func(rt, str(p))
    assert r.ok, r.summary
