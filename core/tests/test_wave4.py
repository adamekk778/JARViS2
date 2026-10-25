"""OMEGA wave 4 (Ultra Memory): categories, sources, contradictions, projects with isolation and resume, the timeline,
search over everything (full text without diacritics, by meaning with a local embedding model), privacy."""
import datetime as dt
import time

import httpx
from conftest import FakeRouter

from jarvis import knowledge, privacy, tools

tools.load_builtin()


def test_categories_and_subject_value():
    assert knowledge.category("Moje manželka se jmenuje Jana") == "Rodina"
    assert knowledge.category("Mám alergii na ořechy") == "Zdraví"
    assert knowledge.category("Nemám rád koriandr") == "Preference"
    assert knowledge.category("Bydlím v Brně na Kounicově ulici") == "Domov"
    assert knowledge.subject_value("Moje auto je modré") == ("moje auto je", "modre")
    assert knowledge.subject_value("Bydlím v Brně") == ("bydlim", "v brne")
    assert knowledge.subject_value("Jmenuji se Adam") == ("jmenuji se", "adam")
    assert knowledge.subject_value("ahoj") is None


async def test_remember_with_source_category_and_conflict(rt):
    r = await tools.call("remember", {"fact": "Bydlím v Brně"}, rt)
    assert r.ok and "Domov" in r.summary
    f = rt.knowledge.facts()[0]
    assert f["category"] == "Domov" and f["source"].startswith("řekl jsi v konverzaci")
    again = await tools.call("remember", {"fact": "Bydlím v Brně"}, rt)
    assert "už vím" in again.summary and len(rt.knowledge.facts()) == 1
    c = await tools.call("remember", {"fact": "Bydlím v Praze"}, rt)
    assert "dřív jsem si zapsal: „Bydlím v Brně“" in c.summary
    cs = rt.knowledge.open_conflicts()
    assert len(cs) == 1 and cs[0]["old_text"] == "Bydlím v Brně"
    r = await tools.call("resolve_memory_conflict", {"id": cs[0]["id"], "keep": "new"}, rt)
    assert r.ok and [x["text"] for x in rt.knowledge.facts()] == ["Bydlím v Praze"] and not rt.knowledge.open_conflicts()


async def test_no_secrets_and_nothing_in_private_mode(rt):
    assert not (await tools.call("remember", {"fact": "Moje heslo je Tajne123!"}, rt)).ok
    rt.memory.set_private(True)
    r = await tools.call("remember", {"fact": "Mám rád jazz"}, rt)
    assert not r.ok and "soukromém" in r.summary and rt.knowledge.facts() == []
    rt.memory.set_private(False)


async def test_projects_isolate_facts_in_the_prompt(rt):
    await tools.call("remember", {"fact": "Jmenuji se Adam"}, rt)
    await tools.call("project_create", {"name": "Web pro pekárnu", "note": "e-shop s chlebem, termín v listopadu"}, rt)
    await tools.call("remember", {"fact": "Klient chce zelenou barvu"}, rt)
    await tools.call("project_create", {"name": "Diplomka", "switch": True}, rt)
    assert rt.knowledge.for_prompt() == ["Jmenuji se Adam"]                       # the bakery's facts stay out
    await tools.call("project_switch", {"name": "web pro pekárnu"}, rt)
    assert set(rt.knowledge.for_prompt()) == {"Jmenuji se Adam", "Klient chce zelenou barvu"}
    rt.router = FakeRouter(["Jasně."])
    await rt.agent.handle("ahoj", [], "chat")
    system = rt.router.calls[0]["messages"][0]["content"]
    assert "Klient chce zelenou barvu" in system and "Aktuální projekt: Web pro pekárnu" in system and "chlebem" in system
    bad = await tools.call("project_switch", {"name": "nic"}, rt)
    assert not bad.ok and "Diplomka" in bad.summary


async def test_project_resume(rt, tmp_path):
    folder = tmp_path / "pekarna"
    folder.mkdir()
    (folder / "menu.html").write_text("<h1>Chleba</h1>")
    rt.knowledge.create_project("Pekárna", str(folder))
    cid = rt.memory.current_conversation
    rt.db.exec("UPDATE conversations SET folder='Pekárna', title='Návrh webu' WHERE id=?", (cid,))
    rt.memory.add_message("user", "udělej menu")
    rt.memory.add_message("assistant", "Menu je hotové, chybí ceny.")
    tid = rt.tasks.begin("Pekárna: doplnit ceny do menu", cid)
    r = await tools.call("project_resume", {"name": "pekárna"}, rt)
    assert r.ok and "Návrh webu" in r.summary and "chybí ceny" in r.summary and "menu.html" in r.summary
    assert "Rozdělané mise: Pekárna: doplnit ceny" in r.summary and "Další krok: Dokončit misi" in r.summary
    assert rt.knowledge.current_project() == "Pekárna" and tid


async def test_timeline_of_a_day(rt):
    rt.memory.add_message("user", "plánujeme dovolenou")
    rt.knowledge.add_fact("Mám rád hory", "test")
    rt.tasks.begin("Najdi chatu v Tatrách", rt.memory.current_conversation)
    rt.db.exec("CREATE TABLE IF NOT EXISTS app_usage (day TEXT, app TEXT, seconds REAL, PRIMARY KEY (day, app))")
    rt.db.exec("INSERT INTO app_usage VALUES (?,?,?)", (dt.date.today().isoformat(), "Chrome", 3600))
    r = await tools.call("memory_timeline", {"day": "dnes"}, rt)
    kinds = [e["kind"] for e in r.data]
    assert r.ok and {"chat", "fact", "mission", "apps"} <= set(kinds) and "Chrome 60 min" in r.summary
    y = await tools.call("memory_timeline", {"day": "včera"}, rt)
    assert y.ok and y.data == []


async def test_search_everything_without_diacritics(rt):
    rt.memory.add_message("user", "Potřebuji vyřešit nájemní smlouvu na byt v Brně")
    rt.knowledge.add_fact("Můj pronajímatel se jmenuje Novák", "test")
    rt.db.exec("CREATE TABLE IF NOT EXISTS dictations (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, text TEXT, raw TEXT, app TEXT, words INTEGER, ms INTEGER)")
    rt.db.exec("INSERT INTO dictations(ts, text) VALUES (?,?)", (time.time(), "Diktuji poznámku o smlouvách s nájemníky"))
    hits = rt.knowledge.search("najemni smlouva")
    kinds = {h["kind"] for h in hits}
    assert "chat" in kinds and "dictation" in kinds
    assert rt.knowledge.search("pronajimatel")[0]["kind"] == "fact"
    rt.memory.delete_conversation(rt.memory.current_conversation)
    assert all(h["kind"] != "chat" for h in rt.knowledge.search("najemni smlouva"))    # deleted = not found any more
    r = await tools.call("search_memory", {"query": "Novák"}, rt)
    assert r.ok and "paměť" in r.summary


async def test_search_by_meaning_with_a_local_model(rt):
    vec = {"kočka": [1, 0, 0], "psa": [0.9, 0.1, 0], "autem": [0, 0, 1]}

    def handler(req):
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3:8b"}, {"name": "nomic-embed-text:latest"}]})
        body = req.read().decode()
        import json

        texts = json.loads(body)["input"]
        out = []
        for t in texts:
            out.append(next((v for k, v in vec.items() if k in t), [0, 1, 0]))
        return httpx.Response(200, json={"embeddings": out})
    rt.transport = httpx.MockTransport(handler)
    rt.knowledge.add_fact("Mám doma psa Rexe", "test")
    rt.knowledge.add_fact("Jezdím autem do práce", "test")
    sem = await rt.knowledge.semantic("kočka")
    assert sem["available"] and sem["model"] == "nomic-embed-text:latest"
    assert sem["hits"][0]["snippet"] == "Mám doma psa Rexe" and all("autem" not in h["snippet"] for h in sem["hits"])


async def test_no_embedding_model_means_full_text_only(rt):
    rt.transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"models": [{"name": "llama3:8b"}]}))
    assert (await rt.knowledge.semantic("cokoli")) == {"available": False, "hits": []}


def test_prune_and_reset_drop_the_index(rt):
    rt.memory.add_message("user", "starý tajný plán")
    rt.knowledge.search("plan")
    old = time.time() - 400 * 86400
    rt.db.exec("UPDATE messages SET created=?", (old,))
    privacy.prune(rt, keep_days=30)
    assert rt.knowledge.search("tajny plan") == []
    rt.knowledge.create_project("X")
    privacy.reset_all(rt)
    assert rt.knowledge.projects() == [] and rt.db.one("SELECT COUNT(*) AS n FROM search_idx")["n"] == 0


def test_memory_page(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    rt.knowledge.add_fact("Bydlím v Brně", "test")
    rt.knowledge.add_fact("Bydlím v Praze", "test")
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c, c.websocket_connect("/ws") as ws:
        def recv(t):
            return next(x for x in iter(ws.receive_json, None) if x["type"] == t)
        ws.send_json({"type": "knowledge_get"})
        k = recv("knowledge")
        assert len(k["conflicts"]) == 1 and k["embed"] == ""
        ws.send_json({"type": "conflict_resolve", "id": k["conflicts"][0]["id"], "keep": "old"})
        assert [f["text"] for f in recv("knowledge")["facts"]] == ["Bydlím v Brně"]
        ws.send_json({"type": "project_set", "action": "create", "name": "Dovolená"})
        assert recv("knowledge")["current"] == "Dovolená"
        ws.send_json({"type": "knowledge_search", "q": "brne"})
        assert recv("knowledge_hits")["hits"][0]["kind"] == "fact"
        ws.send_json({"type": "timeline_get"})
        assert any(e["kind"] == "fact" for e in recv("timeline")["events"])
