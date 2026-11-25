"""3.14 Dosah (návrhy 114–118): English, winget, the web page, anonymous statistics, issue templates."""
import importlib.util
import re
from pathlib import Path

import httpx
import yaml
from conftest import FakeRouter

from jarvis import stats, tools
from jarvis.lang import preferred

tools.load_builtin()
ROOT = Path(__file__).resolve().parents[2]


# ---------- 114: English ----------
def test_answer_language_follows_the_setting():
    assert preferred("hi there", "cs", "en") == "en"                  # short English with the English setting
    assert preferred("jak se máš", "cs", "en") == "cs"                # clearly Czech wins
    assert preferred("what is the time now please", "en", "cs") == "en"
    assert preferred("ako sa máš", "cs", "sk") == "sk"                # Slovak shares Czech letters
    assert preferred("ok", "", "de") == "de"
    assert preferred("ahoj", "cs", "cs") == "cs"


async def test_agent_answers_in_the_chosen_language(rt):
    rt.update_config({"general": {"language": "en"}})
    rt.router = FakeRouter(["Hello."])
    await rt.agent.handle("ok", [], "chat")
    system = rt.router.calls[0]["messages"][0]["content"]
    assert "Odpověz anglicky." in system


def _i18n() -> str:
    return (ROOT / "web/src/shared/i18n.ts").read_text(encoding="utf-8")


def test_every_sidebar_label_has_an_english_name():
    main = (ROOT / "web/src/dashboard/main.ts").read_text(encoding="utf-8")
    nav = re.findall(r'\["[a-z-]+", "[a-z-]+", "([^"]+)"\]', main)
    groups = re.findall(r'\["([^"]+)", \["chat"|\["(Diktování|Systém)", \[', main)
    dic = _i18n()
    assert len(nav) > 30
    missing = [n for n in nav if f'"{n}":' not in dic]
    assert not missing, f"doplň do web/src/shared/i18n.ts: {missing}"
    assert groups and '"Hlavní":' in dic


def test_i18n_keeps_user_content_untouched():
    dic = _i18n()
    assert ".msg" in dic and "textarea" in dic and "contenteditable" in dic
    assert "setLang" in (ROOT / "web/src/shared/ws.ts").read_text(encoding="utf-8")


# ---------- 115: winget ----------
def _winget():
    spec = importlib.util.spec_from_file_location("make_manifest", ROOT / "packaging/winget/make_manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_winget_manifests(tmp_path):
    mm = _winget()
    exe = tmp_path / "JARVIS-Setup.exe"
    exe.write_bytes(b"MZ" + b"\0" * 1000)
    files = mm.write("3.14.7", exe, tmp_path / "out", "owner/repo")
    assert {f.name for f in files} == {"adamekk778.JARVIS.yaml", "adamekk778.JARVIS.installer.yaml",
                                       "adamekk778.JARVIS.locale.cs-CZ.yaml"}
    inst = yaml.safe_load((tmp_path / "out/adamekk778.JARVIS.installer.yaml").read_text(encoding="utf-8"))
    assert inst["PackageVersion"] == "3.14.7" and inst["InstallerType"] == "inno" and inst["Scope"] == "user"
    i = inst["Installers"][0]
    assert i["InstallerUrl"] == "https://github.com/owner/repo/releases/download/v3.14.7/JARVIS-Setup.exe"
    assert i["InstallerSha256"] == mm.sha256(exe) and len(i["InstallerSha256"]) == 64
    for f in files:
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert d["ManifestVersion"] == "1.6.0" and d["PackageIdentifier"] == "adamekk778.JARVIS"


def test_release_attaches_winget_and_checks_english_ui():
    wf = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
    assert "make_manifest.py" in wf and "winget-manifests.zip" in wf and "--lang en" in wf


# ---------- 116: the web page ----------
def test_site_and_pages_workflow():
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    assert "winget install adamekk778.JARVIS" in html and 'name="viewport"' in html
    assert html.count("data-cs") >= 10 and html.count("data-en") >= 10        # both languages
    assert (ROOT / "site/icon.svg").exists()
    wf = yaml.safe_load((ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8"))
    steps = [s.get("uses", "") for s in wf["jobs"]["deploy"]["steps"]]
    assert any(s.startswith("actions/deploy-pages") for s in steps)


# ---------- 117: anonymous statistics ----------
def test_stats_are_off_and_need_an_https_address(rt):
    assert rt.cfg.privacy.share_stats is False and not stats.due(rt)
    rt.update_config({"privacy": {"share_stats": True}})
    assert not stats.due(rt)                                          # no address = nothing is ever sent
    rt.update_config({"privacy": {"stats_url": "http://nesifrovane.example/x"}})
    assert not stats.due(rt)
    rt.update_config({"privacy": {"stats_url": "https://stats.example/x"}})
    assert stats.due(rt)


def test_stats_payload_has_no_personal_data(rt):
    from jarvis import quality

    quality.record_tool(rt, "weather", True, 120)
    quality.record_tool(rt, "weather", False, 80)
    quality.record_tool(rt, "jarvis_skill_tajne_jmeno", True, 10)          # a skill of the user's own: never sent
    rt.memory.add_message("user", "Moje heslo je tajne123")
    p = stats.payload(rt)
    assert p["tools"]["weather"] == {"calls": 2, "fails": 1}
    assert "jarvis_skill_tajne_jmeno" not in p["tools"]
    text = repr(p)
    assert "tajne" not in text and "heslo" not in text
    assert set(p) == {"format", "id", "version", "os", "lang", "days_on", "tools", "ai", "voice_median_ms", "errors"}
    assert re.fullmatch(r"[0-9a-f]{32}", p["id"])


def test_install_id_changes_every_month(rt):
    jan = stats.install_id(rt, 1767225600)          # 2026-01-01
    assert stats.install_id(rt, 1767225600 + 86400 * 10) == jan
    assert stats.install_id(rt, 1769904000) != jan  # 2026-02-01


async def test_stats_send(rt):
    got = []

    def handler(req: httpx.Request) -> httpx.Response:
        got.append(req)
        return httpx.Response(200, text="ok")

    rt.update_config({"privacy": {"share_stats": True, "stats_url": "https://stats.example/x"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await stats.send(rt, c)
    assert got and got[0].url == "https://stats.example/x" and b'"format":1' in got[0].content.replace(b" ", b"")
    assert not stats.due(rt)                                          # sent this week
    failing = httpx.MockTransport(lambda r: httpx.Response(500))
    rt.db.exec("DELETE FROM kv WHERE k='stats_sent'")
    async with httpx.AsyncClient(transport=failing) as c:
        assert not await stats.send(rt, c)
    assert stats.due(rt)


def test_stats_cannot_be_switched_on_by_the_ai():
    from jarvis import config

    src = Path(config.__file__).read_text(encoding="utf-8")
    assert '"privacy.share_stats"' not in src and '"privacy.stats_url"' not in src


# ---------- 118: issue templates ----------
def test_issue_templates():
    d = ROOT / ".github/ISSUE_TEMPLATE"
    bug = yaml.safe_load((d / "bug_report.yml").read_text(encoding="utf-8"))
    idea = yaml.safe_load((d / "feature_request.yml").read_text(encoding="utf-8"))
    cfg = yaml.safe_load((d / "config.yml").read_text(encoding="utf-8"))
    assert bug["labels"] == ["bug"] and idea["labels"] == ["enhancement"]
    assert any(b.get("id") == "version" and b["validations"]["required"] for b in bug["body"])
    assert cfg["blank_issues_enabled"] is True          # the in-app "Nahlásit chybu" opens a blank, prefilled issue
