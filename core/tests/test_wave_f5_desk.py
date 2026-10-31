"""Wave F5g: error codes (033), form values (530), Windows Search (512), open documents (029), download progress (075),
Explorer copy (074), music tempo (244), room light (741), Blender preview render (665 / 666), slicer (467)."""
import numpy as np
import pytest

from jarvis import bridges, deskhelp, sysplus, tools

tools.load_builtin()


def test_error_codes():
    codes = deskhelp.find_codes("Instalace selhala s chybou 0x80070005. Kód: 1603")
    assert 0x80070005 in codes and 1603 in codes
    assert deskhelp.explain_code(0x80070005)["name"] == "Přístup odepřen"
    assert deskhelp.explain_code(1603)["name"].startswith("Instalace selhala")
    assert deskhelp.explain_code(0x80070070)["known"] and not deskhelp.explain_code(0x12345678)["known"]


@pytest.mark.parametrize("label,value,ok", [
    ("E-mail", "petr@seznam.cz", True), ("E-mail", "petr@seznam", False),
    ("Telefon", "+420 777 123 456", True), ("Telefon", "12345", False),
    ("PSČ", "602 00", True), ("IČO", "25596641", True), ("IČO", "25596642", False),
    ("DIČ", "CZ25596641", True), ("Rodné číslo", "7801011236", False), ("Rodné číslo", "736028/5163", True),
    ("IBAN", "CZ65 0800 0000 1920 0014 5399", True), ("IBAN", "CZ65 0800 0000 1920 0014 5398", False),
    ("Karta", "4111 1111 1111 1111", True), ("Karta", "4111 1111 1111 1112", False),
    ("Datum narození", "29. 2. 2024", True), ("Datum narození", "30. 2. 2024", False)])
def test_form_values(label, value, ok):
    r = deskhelp.check_values({label: value})[0]
    assert r["ok"] is ok, (label, value, r)


def test_open_document_names():
    t = ["Smlouva_v2.docx - Word", "data 2026.xlsx - Excel", "zapis.txt – Poznámkový blok", "Spotify Premium", "faktura.pdf - Adobe Acrobat"]
    assert deskhelp.open_document_names(t) == ["Smlouva_v2.docx", "data 2026.xlsx", "zapis.txt", "faktura.pdf"]


def test_windows_search_off_windows():
    assert deskhelp.windows_search("faktura")["items"] == []


def test_download_progress(tmp_path):
    dw = sysplus.DownloadWatch(tmp_path)
    assert dw.progress({"film.mkv.crdownload": 10 << 20}, 100.0)[0]["speed"] == 0
    p = dw.progress({"film.mkv.crdownload": 30 << 20, "hotovo.zip": 5}, 110.0)
    assert p == [{"file": "film.mkv", "bytes": 30 << 20, "speed": 2 << 20}]
    assert dw.progress({}, 120.0) == [] and dw.sizes == {}


def test_explorer_copy_titles():
    assert sysplus.explorer_copy(["Chrome", "45 % dokončeno"]) == 45
    assert sysplus.explorer_copy(["12% complete"]) == 12 and sysplus.explorer_copy(["Word"]) is None


def test_tempo_from_levels():
    r = 20.0
    t = np.arange(0, 12, 1 / r)
    for bpm in (100, 128):
        lev = np.exp(-((t % (60 / bpm)) / 0.06)) * 0.8 + 0.05
        got, conf = sysplus.tempo_bpm(list(lev), r)
        assert got is not None and abs(got - bpm) <= 3 and conf > 0.3
    assert sysplus.tempo_bpm([0.3] * 240, r) == (None, 0.0)


def test_room_glow():
    assert sysplus.glow_for_lux(None) == 1.0 and sysplus.glow_for_lux(0) == 0.35
    assert 0.35 < sysplus.glow_for_lux(50) < sysplus.glow_for_lux(400) <= 1.0


def test_blender_preview_and_slicer(tmp_path):
    out = tmp_path / "n.png"
    calls = []

    def runner(cmd, **kw):
        import subprocess
        calls.append(cmd)
        script = open(cmd[cmd.index("--python") + 1], encoding="utf-8").read()
        assert "sc.frame_set(60)" in script and "write_still=True" in script
        out.write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0, "JARVIS_RENDER_OK", "")
    assert bridges.render_script_preview("blender", "scena.blend", "import bpy", str(out), 60, runner) == str(out)
    cmd = bridges.slice_cmd("prusa-slicer", "m.stl", "m.gcode", "", 0.15, 30, True)
    assert cmd[:4] == ["prusa-slicer", "--export-gcode", "--output", "m.gcode"] and "30%" in cmd and "--support-material" in cmd
    g = bridges.gcode_summary("; estimated printing time (normal mode) = 1h 23m 5s\n; filament used [mm] = 4523.1\n; filament used [g] = 13.5\n;LAYER_CHANGE\n;LAYER_CHANGE\n")
    assert g == {"time": "1h 23m 5s", "filament_m": 4.52, "filament_g": "13.5", "layers": 2}


async def test_desktop_tools(rt):
    r = await tools.REGISTRY["explain_error"].func(rt, "Chyba 0x80070070 při kopírování")
    assert r.ok and "Málo místa" in r.summary
    r = await tools.REGISTRY["check_form_values"].func(rt, {"E-mail": "x@y", "PSČ": "60200"})
    assert r.ok and "E-mail" in r.summary
    r = await tools.REGISTRY["compare_open_documents"].func(rt)
    assert not r.ok
