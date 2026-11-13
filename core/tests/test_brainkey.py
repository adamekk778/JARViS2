"""3.12 Mozek jen z API klíče: the user pasted a Groq key into the OmniRoute card (localhost) and got "nejde"."""
import asyncio

from jarvis import brainkey, secrets


def test_the_key_tells_the_service():
    assert brainkey.detect("gsk_" + "a" * 40) == "groq"
    assert brainkey.detect("AIzaSy" + "b" * 33) == "gemini"
    assert brainkey.detect("sk-ant-api03-" + "c" * 30) == "anthropic"
    assert brainkey.detect("sk-or-v1-" + "d" * 30) == "openrouter"
    assert brainkey.detect("sk-proj-" + "e" * 30) == "openai"
    assert brainkey.detect("hello") is None
    assert brainkey.clean(' "gsk_abc def"\n') == "gsk_abcdef"


def test_paste_sets_everything_up_and_puts_it_first(rt):
    assert rt.cfg.brain.chain[0] == "omniroute"                       # the default: localhost first
    tested = []

    async def test(pid):
        tested.append(pid)
        return {"ok": True, "message": "funguju", "ms": 420}

    key = "  gsk_" + "x" * 48 + "\n"
    r = asyncio.run(brainkey.apply(rt, key, test))
    assert r["ok"] and r["provider"] == "groq" and "Groq" in r["message"]
    assert rt.cfg.brain.chain[0] == "groq" and tested == ["groq"]
    p = next(p for p in rt.cfg.brain.providers if p.id == "groq")
    assert p.base_url == "https://api.groq.com/openai/v1" and p.model and p.enabled
    assert secrets.get("groq") == "gsk_" + "x" * 48                   # cleaned, stored for that service
    assert secrets.get("omniroute") == ""                              # never into the wrong card


def test_a_broken_old_setup_of_the_same_service_is_repaired(rt):
    provs = [p.model_dump() for p in rt.cfg.brain.providers] + [{"id": "gemini", "preset": "gemini", "base_url": "http://localhost:9999",
                                                                 "model": "", "enabled": False}]
    rt.update_config({"brain": {"providers": provs}})

    async def test(pid):
        return {"ok": True, "ms": 300}

    r = asyncio.run(brainkey.apply(rt, "AIzaSy" + "q" * 33, test))
    p = next(p for p in rt.cfg.brain.providers if p.id == "gemini")
    assert r["ok"] and p.enabled and p.base_url.startswith("https://generativelanguage") and p.model
    assert len([x for x in rt.cfg.brain.providers if x.preset == "gemini"]) == 1


def test_errors_in_plain_words(rt):
    async def bad(pid):
        return {"ok": False, "message": "HTTP 401: Invalid API Key"}

    r = asyncio.run(brainkey.apply(rt, "gsk_" + "z" * 48, bad))
    assert not r["ok"] and "odmítla" in r["message"]
    gem = 'gemini: HTTP 400: [{ "error": { "code": 400, "message": "Please pass a valid API key", "status": "INVALID_ARGUMENT" } }]'
    assert brainkey.explain(gem) == (False, brainkey.explain("HTTP 401")[1])               # Google says 400 for a bad key
    assert not brainkey.explain("groq: Groq klíč odmítl – zkopíruj ho znovu")[0]
    assert "odmítla" in brainkey.explain("openai: Poskytovatel odmítl přístup – chybí nebo nesedí API klíč.")[1]
    assert brainkey.explain("gemini: gemini: model overloaded")[1] == "Nepovedlo se: model overloaded"
    assert brainkey.explain("Error 429 rate limit reached")[0] is True                 # the key is fine, only a limit
    assert "internetu" in brainkey.explain("ConnectError: [Errno 11001] getaddrinfo failed")[1]
    assert not asyncio.run(brainkey.apply(rt, "nevim", bad))["ok"]
    assert "Nepoznám" in asyncio.run(brainkey.apply(rt, "xyz" * 10, bad))["message"]


def test_blocked_internet_is_named_not_the_key():
    """A real PC: WinError 10013 – the key was fine, Windows / an antivirus kept JARVIS off the internet."""
    ok, msg = brainkey.explain("gemini: ConnectError: [WinError 10013] Došlo k pokusu o přístup k soketu způsobem zakázaným")
    assert not ok and "Klíč je v pořádku" in msg and "Opravit síť pro JARVIS" in msg
    from jarvis.llm.openai_compat import friendly_error
    assert friendly_error("gemini", "https://x", OSError("[WinError 10013] forbidden by its access permissions")) == brainkey.BLOCKED
