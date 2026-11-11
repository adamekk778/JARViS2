"""3.12 Offline záloha mozku: a model on this PC, always LAST in the chain; requests fit its small context."""
from jarvis import tools
from jarvis.config import ProviderCfg
from jarvis.llm import budget

tools.load_builtin()


def test_backup_goes_last_and_can_be_switched_off(rt, monkeypatch):
    monkeypatch.setattr(rt, "update_config", lambda patch: setattr(rt, "cfg", __import__("jarvis.config", fromlist=["x"]).apply_patch(rt.cfg, patch)) or rt.cfg)
    rt.cfg.brain.providers = [ProviderCfg(id="groq", preset="groq", model="openai/gpt-oss-120b")]
    rt.cfg.brain.chain = ["groq"]
    st = rt.local.set_backup(True, "qwen2.5:3b")
    assert st["on"] and st["last"] and rt.cfg.brain.chain[-1] == "ollama" and rt.cfg.brain.chain[0] == "groq"
    rt.cfg.brain.chain = ["ollama", "groq"]                       # even if it was first before
    assert rt.local.set_backup(True)["last"] and rt.cfg.brain.chain == ["groq", "ollama"]
    assert rt.local.set_backup(False)["on"] is False


def test_local_model_gets_a_request_that_fits_its_context(rt):
    from jarvis.llm.router import Router

    r = Router(rt.cfg.brain, lambda _: "")
    pc = ProviderCfg(id="ollama", preset="ollama", model="qwen2.5:3b")
    limit = r._limit_of(pc, "qwen2.5:3b")
    assert limit in (2048, 4096, 8192)
    msgs = [{"role": "system", "content": "S" * 4700}, {"role": "user", "content": "ahoj"}]
    tools_ = rt.agent._tool_schemas("najdi duplicitní fotky")
    m2, t2, mt = budget.fit(msgs, tools_, 4096, 2048)
    names = [t["function"]["name"] for t in t2]
    assert budget.estimate(m2, t2) + mt <= 4096 * budget.HEADROOM + 50 or len(t2) <= 6
    assert "find_tools" in names                                  # the rest stays reachable
