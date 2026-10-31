"""Wave F1: watched webs + certificates (708/709), line loss history (719), programs and disks over time (305/309),
waiting Windows updates (013), Mochi's reaction history (085) and the mission graph in the task detail (222)."""
import json
import time

from jarvis import netwatch, tools, winupd

tools.load_builtin()


def test_norm_url_and_domain():
    assert netwatch.norm_url("seznam.cz/") == "https://seznam.cz"
    assert netwatch.norm_url(" http://a.cz/x ") == "http://a.cz/x"
    assert netwatch.domain_of("https://web.cz:8443/a") == "web.cz"
    assert netwatch.norm_url("") == ""


def test_cert_threshold_once_per_step():
    assert netwatch.cert_threshold(90, None) is None
    assert netwatch.cert_threshold(29, None) == 30
    assert netwatch.cert_threshold(25, 30) is None          # 30-day notice already given
    assert netwatch.cert_threshold(13, 30) == 14
    assert netwatch.cert_threshold(0, 3) == 1
    assert netwatch.cert_threshold(None, None) is None


def test_watch_list_and_events(rt):
    nw = rt.netwatch
    assert nw.add("neni adresa")["ok"] is False
    r = nw.add("mojefirma.cz")
    assert r["ok"] and r["url"] == "https://mojefirma.cz"
    assert nw.add("https://mojefirma.cz/")["already"]
    u = r["url"]
    assert nw.apply({"url": u, "up": True, "status": 200, "ms": 120, "days_left": 80}) == []     # first look: no notice
    ev = nw.apply({"url": u, "up": False, "status": 503, "ms": 50, "days_left": 80})
    assert [e["kind"] for e in ev] == ["down"] and "nefunguje" in ev[0]["text"]
    assert nw.apply({"url": u, "up": False, "status": 503, "ms": 50, "days_left": 80}) == []     # still down: quiet
    ev = nw.apply({"url": u, "up": True, "status": 200, "ms": 90, "days_left": 12})
    assert {e["kind"] for e in ev} == {"up", "cert"} and any("12 dní" in e["text"] for e in ev)
    assert nw.apply({"url": u, "up": True, "status": 200, "ms": 90, "days_left": 11}) == []      # same threshold
    ev = nw.apply({"url": u, "up": True, "status": 200, "ms": 90, "days_left": 6})
    assert [e["kind"] for e in ev] == ["cert"]
    nw.apply({"url": u, "up": True, "status": 200, "ms": 90, "days_left": 89})                   # renewed
    assert [e["kind"] for e in nw.apply({"url": u, "up": True, "status": 200, "ms": 90, "days_left": 29})] == ["cert"]
    row = nw.list()[0]
    assert row["up"] is True and row["days_left"] == 29 and 0 < row["uptime_24h"] < 100
    assert len(nw.history(u)) == 8
    nw.remove(u)
    assert nw.list() == [] and nw.history(u) == []


def test_loss_history_summary(rt):
    nw = rt.netwatch
    assert nw.loss_summary()["samples"] == 0
    nw.record_loss({"host": "1.1.1.1", "avg_ms": 20, "jitter_ms": 2, "loss_pct": 0})
    nw.record_loss({"host": "1.1.1.1", "avg_ms": 80, "jitter_ms": 9, "loss_pct": 30})
    nw.record_loss({"host": "1.1.1.1", "avg_ms": None, "jitter_ms": None, "loss_pct": 100})
    s = nw.loss_summary()
    assert s["samples"] == 3 and s["loss_max"] == 100 and s["outages"] == 1 and s["ms_avg"] == 50 and s["bad_rounds"] == 2


def test_process_profile_and_disks(rt):
    p = rt.perf
    now = time.time()
    for i, (cpu, ram) in enumerate(((40, 500), (10, 520), (0.5, 510))):
        rt.db.exec("INSERT INTO perf_procs VALUES (?,?,?,?)", (now - 600 * i, "chrome.exe", cpu, ram))
    rt.db.exec("INSERT INTO perf_procs VALUES (?,?,?,?)", (now, "code.exe", 5, 300))
    prof = p.proc_profile(24)
    assert prof["samples"] == 3 and prof["top"][0]["name"] == "chrome.exe"
    assert prof["top"][0]["cpu_max"] == 40 and prof["top"][0]["seen_pct"] == 100
    assert prof["top"][1]["cpu_avg"] == round(5 / 3, 1)          # one sample in three → averaged over all samples
    one = p.proc_profile(24, "chrome")
    assert len(one["series"]) == 3
    rt.db.exec("INSERT INTO perf_disks VALUES (?,?,?,?)", (now, "C:", 1.5, 0.2))
    assert p.disk_series(24)["C:"][0]["read"] == 1.5
    # a real record writes the history row and, from the second call, per-process and per-disk deltas
    p.record(10, 20)
    p.record(11, 21)
    assert rt.db.one("SELECT COUNT(*) AS n FROM perf_history")["n"] == 2


async def test_watch_tools(rt):
    r = await tools.REGISTRY["line_history"].func(rt)
    assert not r.ok
    rt.netwatch.record_loss({"host": "1.1.1.1", "avg_ms": 30, "jitter_ms": 1, "loss_pct": 10})
    r = await tools.REGISTRY["line_history"].func(rt, hours=24)
    assert r.ok and "ztráta 10" in r.summary
    r = await tools.REGISTRY["process_profile"].func(rt)
    assert not r.ok
    r = await tools.REGISTRY["web_watch"].func(rt, action="list")
    assert r.ok and "nehlídám" in r.summary
    rt.mood.react("volume", {"level": 40, "up": True})
    r = await tools.REGISTRY["mochi_history"].func(rt)
    assert r.ok and "volume" in r.summary
    from jarvis.permissions import READ_ONLY_OK
    assert {"line_history", "process_profile", "mochi_history"} <= READ_ONLY_OK


def test_windows_updates_parse_and_summary():
    out = json.dumps({"updates": {"title": "Kumulativní aktualizace", "kb": "KB5050", "category": "Security Updates",
                                  "severity": "Important", "mb": 120}, "reboot": True})
    r = winupd.parse("garbage " + out)
    assert len(r["updates"]) == 1 and r["security"] == 1 and r["mb"] == 120 and r["reboot"]
    s = winupd.summary(r)
    assert "Čeká 1 aktualizace" in s and "restart" in s and "bezpečnostní" in s
    assert "aktuální" in winupd.summary({"updates": [], "reboot": False})
    assert "nejdou zjistit" in winupd.summary({"updates": [], "error": "x"})
    assert winupd.parse("")["updates"] == []


def test_mood_history_records_reactions_and_moods(rt):
    m = rt.mood
    m.react("joy")
    m._emit()
    h = m.history()
    assert h[0]["kind"] in ("mood", "reaction") and any(x["kind"] == "reaction" and x["name"] == "joy" for x in h)
    assert all(x["kind"] == "reaction" for x in m.history(kind="reaction"))


def test_task_detail_has_mission_graph(rt):
    tid = rt.tasks.begin("mise", "c1")
    rt.tasks.set_spec([{"tool": "a"}, {"tool": "b"}, {"tool": "c", "needs": [0, 1]}])
    d = rt.tasks.get(tid)
    assert d["graph"]["layers"] == [[0, 1], [2]]
