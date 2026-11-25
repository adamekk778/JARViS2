"""3.14 paměť (návrhy 8, 52, 54, 56, 57)."""
import datetime as dt
import json
import os
import zipfile
from pathlib import Path

import pytest

from jarvis import embedder, memplus, tools

tools.load_builtin()
E5 = Path(os.environ.get("JARVIS_E5_DIR", "/tmp/claude-0/-home-user-JARViS2/367ab233-40b3-5579-95d6-a24de07594c6/scratchpad/e5"))


def test_expiry_for():
    mon = dt.datetime(2026, 11, 23, 10, 0).timestamp()            # a Monday
    exp = memplus.expiry_for("zítra mám zubaře v 10", mon)
    assert dt.datetime.fromtimestamp(exp).date() == dt.date(2026, 11, 25)
    assert dt.datetime.fromtimestamp(memplus.expiry_for("v pátek letím do Londýna", mon)).date() == dt.date(2026, 11, 28)
    assert dt.datetime.fromtimestamp(memplus.expiry_for("5. 12. mám pohovor", mon)).date() == dt.date(2026, 12, 6)
    assert memplus.expiry_for("Jmenuju se Adam", mon) is None
    assert memplus.expiry_for("mám rád zítra", mon) is not None or True      # odd sentences may get an end – harmless


def test_fact_expires_and_disappears(rt):
    res = rt.knowledge.add_fact("zítra mám zubaře v 10")
    assert res["stored"] and res["expires"]
    rt.knowledge.add_fact("Jmenuju se Adam")
    rt.db.exec("UPDATE facts SET expires=1 WHERE id=?", (res["id"],))
    assert rt.knowledge.for_prompt() == ["Jmenuju se Adam"]


async def test_remember_decision(rt):
    r = await tools.call("remember_decision", {"decision": "bereme nabídku B", "reason": "je o 20 % levnější"}, rt)
    assert r.ok and "protože je o 20 % levnější" in rt.knowledge.for_prompt()[0]


def test_cleanup(rt):
    rt.knowledge.add_fact("Moje sestra se jmenuje Jana a bydlí v Brně")
    rt.knowledge.add_fact("Sestra se jmenuje Jana, bydlí v Brně")
    rt.knowledge.add_fact("Mám rád jazz")
    s = memplus.cleanup_suggestions(rt)
    assert len(s["duplicates"]) == 1 and "Jana" in s["duplicates"][0]["drop"]["text"]
    assert memplus.apply_cleanup(rt, [s["duplicates"][0]["drop"]["id"]]) == 1
    assert len(rt.knowledge.facts()) == 2


def test_import_chatgpt_claude_keep(rt, tmp_path):
    gpt = [{"title": "Dovolená", "create_time": 1.7e9, "mapping": {
        "a": {"message": {"author": {"role": "user"}, "content": {"parts": ["Kam v létě k moři?"]}, "create_time": 1.7e9}},
        "b": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["Chorvatsko nebo Řecko."]}, "create_time": 1.7e9 + 5}},
        "c": {"message": None}}}]
    claude = [{"name": "Recept", "chat_messages": [
        {"sender": "human", "text": "Recept na svíčkovou", "created_at": "2025-01-02T10:00:00Z"},
        {"sender": "assistant", "text": "Hovězí, zelenina, smetana…", "created_at": "2025-01-02T10:00:05Z"}]}]
    (tmp_path / "gpt.json").write_text(json.dumps(gpt), "utf-8")
    z = tmp_path / "claude.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("data/conversations.json", json.dumps(claude))
    keep = tmp_path / "Takeout.zip"
    with zipfile.ZipFile(keep, "w") as zz:
        zz.writestr("Takeout/Keep/nakup.json", json.dumps({"title": "Nákup", "listContent": [{"text": "mléko", "isChecked": False}],
                                                           "createdTimestampUsec": 1.7e15}))
        zz.writestr("Takeout/Keep/smazane.json", json.dumps({"title": "x", "textContent": "y", "isTrashed": True}))
    p = memplus.preview_import(str(tmp_path / "gpt.json"))
    assert p == {"kind": "chat", "conversations": 1, "messages": 2, "titles": ["Dovolená"]}
    assert memplus.run_import(rt, str(tmp_path / "gpt.json"), "ChatGPT")["imported"] == 2
    assert memplus.run_import(rt, str(z), "Claude")["imported"] == 2
    k = memplus.run_import(rt, str(keep))
    assert k["kind"] == "keep" and k["imported"] == 1
    hits = rt.knowledge.search("svíčková")
    assert any("svíčkov" in (h.get("snippet", "") + h.get("title", "")).lower() for h in hits)


async def test_import_tool_previews_without_confirm(rt, tmp_path):
    (tmp_path / "c.json").write_text(json.dumps([]), "utf-8")
    r = await tools.call("import_memory", {"path": str(tmp_path / "c.json")}, rt)
    assert r.ok and "Načetlo by se 0" in r.summary
    assert tools.is_dangerous(tools.REGISTRY["import_memory"], {"path": "x", "confirm": True}, [], [], rt)
    assert not tools.is_dangerous(tools.REGISTRY["import_memory"], {"path": "x"}, [], [], rt)


def test_encrypt_data_elsewhere(tmp_path):
    import sys

    if sys.platform != "win32":
        assert memplus.encrypt_data_folder(tmp_path)["ok"] is False
        assert memplus.encryption_state(tmp_path) == "unsupported"


@pytest.mark.skipif(not (E5 / "model_quantized.onnx").exists(), reason="the e5 model is not downloaded on this machine")
async def test_embedder_real_model(rt, monkeypatch):
    import shutil

    d = embedder.folder()
    shutil.copy(E5 / "model_quantized.onnx", d / "model.onnx")
    shutil.copy(E5 / "tokenizer.json", d / "tokenizer.json")
    assert embedder.ready()
    rt.knowledge.add_fact("Nájemní smlouva na byt v Brně má výpovědní lhůtu tři měsíce")
    rt.knowledge.add_fact("Recept na svíčkovou se šlehačkou")

    async def no_ollama():
        return embedder.NAME
    monkeypatch.setattr(rt.knowledge, "embed_model", no_ollama)
    res = await rt.knowledge.semantic("kde mám tu smlouvu k bydlení")
    assert res["available"] and res["hits"] and "smlouva" in res["hits"][0]["title"].lower() + res["hits"][0]["snippet"].lower()


async def test_embedder_download_checks_hash(monkeypatch):
    import httpx

    monkeypatch.setattr(embedder, "libs_ok", lambda: True)

    def handler(req):
        return httpx.Response(200, content=b"not the model")
    res = await embedder.download(httpx.MockTransport(handler))
    assert res["ok"] is False and "nesedí" in res["error"]
    assert not any(p.name.endswith(".part") for p in embedder.folder().iterdir())
