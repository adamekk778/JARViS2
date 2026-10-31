"""Wave F3: blue-screen dumps read without a debugger (015), attachments found by content (545), suggestions for the app
in front (501), the chance of recovering data (703) and adaptive difficulty for any practice (451)."""
import struct
import time

from jarvis import comms, crashdump, proactive, secutils, tools

tools.load_builtin()


def _dump64(code: int, params=(1, 2, 3, 4), drivers=("nvlddmkm.sys", "ntoskrnl.exe", "rtwlane.sys")) -> bytes:
    h = bytearray(0x2000)
    h[0:8] = b"PAGEDU64"
    struct.pack_into("<I", h, 0x0C, 22631)
    struct.pack_into("<I", h, 0x38, code)
    struct.pack_into("<4Q", h, 0x40, *params)
    pos = 0x1000
    for d in drivers:
        b = d.encode("utf-16-le")
        h[pos:pos + len(b)] = b
        pos += len(b) + 16
    return bytes(h)


def test_parse_dump_header_and_drivers(tmp_path):
    r = crashdump.parse_header(_dump64(0xD1, (0x10, 2, 0, 0xFFFFF80000001234)))
    assert r["code"] == "0x000000D1" and r["name"] == "DRIVER_IRQL_NOT_LESS_OR_EQUAL" and "síťov" in r["meaning"]
    assert r["params"][3] == "0xFFFFF80000001234" and r["build"] == 22631 and r["bits"] == 64
    p = tmp_path / "Mini1.dmp"
    p.write_bytes(_dump64(0x116))
    a = crashdump.analyze(p)
    assert a["name"] == "VIDEO_TDR_FAILURE" and "nvlddmkm.sys" in a["drivers"] and "rtwlane.sys" in a["drivers"]
    assert "ntoskrnl.exe" not in a["drivers"]
    assert "MDMP" in crashdump.parse_header(b"MDMP" + b"\0" * 200)["error"] or "aplikace" in crashdump.parse_header(b"MDMP" + b"\0" * 200)["error"]
    assert "není" in crashdump.parse_header(b"hello" * 40)["error"]
    (tmp_path / "Mini2.dmp").write_bytes(_dump64(0x116))
    (tmp_path / "Mini3.dmp").write_bytes(_dump64(0x1A))
    items = crashdump.recent(tmp_path)
    s = crashdump.summary(items)
    assert "VIDEO_TDR_FAILURE (2×)" in s and "grafiky" in s
    assert "Žádné" in crashdump.summary([])
    assert crashdump.parse_header(_dump64(0x12345))["name"] == "neznámý kód"


def test_attachment_matching(tmp_path):
    same = tmp_path / "kopie_pod_jinym_jmenem.pdf"
    same.write_bytes(b"%PDF-1.4 binary identical content")
    old = tmp_path / "smlouva_v1.txt"
    old.write_text("Smlouva o dílo mezi firmou Alfa a firmou Beta. Předmětem je dodávka webu do konce roku. Cena je 50 000 Kč. "
                   "Platba do 14 dnů od předání.", encoding="utf-8")
    other = tmp_path / "recept.txt"
    other.write_text("Bábovka: mouka, cukr, vejce, mléko, kakao. Péct 50 minut.", encoding="utf-8")
    atts = [("faktura.pdf", same.read_bytes()),
            ("smlouva_v2.txt", ("Smlouva o dílo mezi firmou Alfa a firmou Beta. Předmětem je dodávka webu do konce roku. Cena je 60 000 Kč. "
                                "Platba do 14 dnů od předání.").encode("utf-8"))]
    r = comms.match_attachments(atts, [same, old, other])
    assert r[0]["same"] == [str(same)]
    assert r[1]["similar"] and r[1]["similar"][0]["path"] == str(old) and r[1]["similar"][0]["similarity"] >= 50
    assert all(x["path"] != str(other) for x in r[1]["similar"])


def test_app_context_suggestions(rt):
    s = proactive.app_context("Microsoft Excel")
    assert any("tabulc" in x["text"] or "graf" in x["text"] for x in s)
    assert proactive.app_context("") == [] and proactive.app_context("Neznámá appka") == []
    assert any("pauzu" in x["text"] for x in proactive.app_context("Visual Studio Code", 150))
    first = proactive.next_actions(rt, app="Zoom")[0]
    assert "zápis" in first["text"].lower()


def test_recovery_odds():
    healthy = {"physical": [{"DeviceId": 0, "FriendlyName": "Samsung SSD", "Health": "Healthy", "Status": "OK"}],
               "reliability": [{"DeviceId": 0, "ReadErrors": 0, "WriteErrors": 0}], "io_events": []}
    o = secutils.recovery_odds(healthy)[0]
    assert o["level"] == "vysoká" and o["reasons"] == ["žádné známky poškození"]
    sick = {"physical": [{"DeviceId": 1, "FriendlyName": "WD HDD", "Health": "Warning", "Status": "OK"}],
            "reliability": [{"DeviceId": 1, "ReadErrors": 120}], "io_events": [{"Id": 7}] * 30}
    o = secutils.recovery_odds(sick)[0]
    assert o["level"] == "nízká" and o["percent"].startswith("40") and "firmu" in o["advice"]
    cable = {"physical": [{"DeviceId": 2, "FriendlyName": "USB disk", "Health": "Healthy", "Status": "OK"}],
             "reliability": [], "io_events": [{"Id": 129}] * 3}
    assert any("kabel" in r for r in secutils.recovery_odds(cable)[0]["reasons"])


def test_adaptive_level(rt):
    L = rt.learning
    assert L.adaptive_level("zlomky")["level"] == "střední"
    for sc in (90, 85, 100):
        L.record_answer("matika", "zlomky", "q", sc, "bez chyby")
        time.sleep(0.001)
    a = L.adaptive_level("zlomky")
    assert a["level"] == "pokročilá" and "3 dobré" in a["why"] and a["success_pct"] == 100
    for sc in (30, 20):
        L.record_answer("matika", "zlomky", "q", sc, "neúplná odpověď")
        time.sleep(0.001)
    assert L.adaptive_level("zlomky")["level"] == "střední"
    assert "crash_dumps" in tools.REGISTRY
