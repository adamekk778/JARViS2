"""OMEGA §44 local AI: measure the speed of installed models, which quantisation fits the graphics card, which installed
models fit where (GPU / GPU+CPU / CPU), warm a model up ahead of time, pick the best embedding model, and test the
answers of models on questions with known answers. Only models the user already installed are used – nothing is
downloaded here."""
from __future__ import annotations

import re
import time
from typing import Any

from .comms import fold

QUANTS = [("Q2_K", 2.6, "nouzově – znatelně hloupější"), ("Q3_K_M", 3.9, "malá ztráta kvality"), ("Q4_K_M", 4.85, "nejlepší poměr velikost/kvalita"),
          ("Q5_K_M", 5.7, "skoro bez ztráty"), ("Q6_K", 6.6, "prakticky bez ztráty"), ("Q8_0", 8.5, "bez ztráty"), ("F16", 16.0, "plná přesnost")]


def params_from_name(name: str) -> float | None:
    """'qwen2.5:7b' → 7, 'mixtral:8x7b' → 46.7 (experts share layers), 'phi3:3.8b' → 3.8, '…-1.5b-…' → 1.5."""
    n = name.lower()
    m = re.search(r"(\d+)x(\d+(?:\.\d+)?)b", n)
    if m:
        return round(int(m.group(1)) * float(m.group(2)) * 0.83, 1)
    m = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*b\b", n)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)m\b", n)
    return round(int(m.group(1)) / 1000, 3) if m else None


def kv_cache_gb(params_b: float, ctx: int) -> float:
    """Rough KV-cache size: grows with the model and the context window (fp16 cache, GQA)."""
    return round(0.12 * (params_b / 7) ** 0.8 * ctx / 4096, 2)


def quant_advice(params_b: float, vram_gb: float, ram_gb: float, ctx: int = 4096) -> dict:
    rows = []
    for q, bpw, note in QUANTS:
        size = params_b * bpw / 8 * 1.05                       # + embeddings / metadata
        need = size + kv_cache_gb(params_b, ctx) + 0.3          # + runtime buffers
        where = "GPU" if vram_gb and need <= vram_gb * 0.95 else "GPU+CPU" if vram_gb and need <= vram_gb + ram_gb * 0.6 else \
                "CPU" if need <= ram_gb * 0.7 else "nevejde se"
        rows.append({"quant": q, "size_gb": round(size, 1), "need_gb": round(need, 1), "where": where, "note": note})
    gpu = [r for r in rows if r["where"] == "GPU" and r["quant"] not in ("Q2_K",)]
    order = ["Q4_K_M", "Q5_K_M", "Q3_K_M", "Q2_K"]          # off the GPU: Q4 is the usual speed/quality sweet spot, Q2 a last resort
    best = gpu[-1] if gpu else next((r for q in order for r in rows if r["quant"] == q and r["where"] in ("GPU+CPU", "CPU")), None)
    return {"params_b": params_b, "ctx": ctx, "options": rows, "best": best,
            "speed_hint": "rychlé (celý model v grafice)" if best and best["where"] == "GPU" else
                          "střední (část na procesoru)" if best and best["where"] == "GPU+CPU" else
                          "pomalé (jen procesor)" if best else "na tomhle počítači nepoběží"}


async def installed(rt) -> list[dict]:
    async with rt.http() as c:
        r = await c.get(f"{rt.local.base}/api/tags", timeout=5)
    r.raise_for_status()
    out = []
    for m in r.json().get("models", []):
        d = m.get("details") or {}
        ps = d.get("parameter_size") or ""
        pb = float(re.sub(r"[^\d.]", "", ps)) if re.search(r"\d", ps) and ps.upper().endswith("B") else params_from_name(m["name"])
        if ps.upper().endswith("M") and re.search(r"\d", ps):
            pb = float(re.sub(r"[^\d.]", "", ps)) / 1000
        out.append({"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 2), "params_b": pb, "quant": d.get("quantization_level", ""),
                    "family": d.get("family", ""), "embedding": bool(re.search(r"embed|bge|e5|minilm|gte|nomic", m["name"], re.I))})
    return out


def compatibility(models: list[dict], vram_gb: float, ram_gb: float, ctx: int = 4096) -> list[dict]:
    out = []
    for m in models:
        need = m["size_gb"] + (kv_cache_gb(m["params_b"], ctx) if m["params_b"] else 0.3) + 0.4
        where = "GPU" if vram_gb and need <= vram_gb * 0.92 else "GPU+CPU" if vram_gb and need <= vram_gb + ram_gb * 0.6 else \
                "CPU" if need <= ram_gb * 0.7 else "nevejde se"
        out.append({**m, "need_gb": round(need, 1), "where": where})
    return out


async def benchmark(rt, models: list[str], prompt: str = "Napiš tři věty o tom, proč je důležité spát.", tokens: int = 96) -> list[dict]:
    """Real generation on each model: load time, prompt speed and generation speed (tokens/s) from Ollama's own timers."""
    out = []
    async with rt.http() as c:
        for name in models:
            try:
                r = await c.post(f"{rt.local.base}/api/generate", json={"model": name, "prompt": prompt, "stream": False,
                                                                        "options": {"num_predict": tokens, "temperature": 0}}, timeout=600)
                r.raise_for_status()
                d = r.json()
                ps = (await c.get(f"{rt.local.base}/api/ps", timeout=10)).json().get("models", [])
                vram = next((m.get("size_vram", 0) for m in ps if m.get("name") == name), 0)
                gen_s = (d.get("eval_duration") or 0) / 1e9
                pr_s = (d.get("prompt_eval_duration") or 0) / 1e9
                out.append({"model": name, "ok": True, "tokens": d.get("eval_count", 0),
                            "tok_s": round(d.get("eval_count", 0) / gen_s, 1) if gen_s else None,
                            "prompt_tok_s": round(d.get("prompt_eval_count", 0) / pr_s, 1) if pr_s else None,
                            "load_s": round((d.get("load_duration") or 0) / 1e9, 2), "total_s": round((d.get("total_duration") or 0) / 1e9, 2),
                            "on_gpu": vram > 0, "vram_gb": round(vram / 1e9, 1)})
            except Exception as e:  # noqa: BLE001 – one broken model does not stop the comparison
                out.append({"model": name, "ok": False, "error": str(e)[:200]})
    return sorted(out, key=lambda x: -(x.get("tok_s") or 0))


async def warm_up(rt, model: str, keep_alive: str = "30m") -> dict:
    """Load the model into memory now (empty prompt) so the first real answer is fast; keep it for `keep_alive`."""
    async with rt.http() as c:
        t0 = time.perf_counter()
        r = await c.post(f"{rt.local.base}/api/generate", json={"model": model, "prompt": "", "keep_alive": keep_alive}, timeout=600)
        r.raise_for_status()
        first = time.perf_counter() - t0
        t1 = time.perf_counter()
        await c.post(f"{rt.local.base}/api/generate", json={"model": model, "prompt": "", "keep_alive": keep_alive}, timeout=60)
        second = time.perf_counter() - t1
        ps = (await c.get(f"{rt.local.base}/api/ps", timeout=10)).json().get("models", [])
    m = next((x for x in ps if x.get("name") == model), None)
    return {"model": model, "load_s": round(first, 2), "ready_s": round(second, 3), "loaded": m is not None,
            "until": (m or {}).get("expires_at", ""), "vram_gb": round((m or {}).get("size_vram", 0) / 1e9, 1)}


EMBED_SET = [  # (query, the passage that answers it) – Czech, different wording on purpose
    ("Jak dlouho platí občanský průkaz?", "Občanka je platná deset let od vydání, u dětí do patnácti let pět let."),
    ("Kolik stojí dálniční známka?", "Roční elektronická dálniční známka pro osobní auto stojí 2440 korun."),
    ("Co dělat při úrazu elektrickým proudem?", "Nejdřív vypněte jistič, teprve potom se zraněného dotkněte a zavolejte 155."),
    ("Kdy se platí daň z nemovitosti?", "Daň z nemovitých věcí je splatná do konce května."),
    ("Jak se zbavit vodního kamene v konvici?", "Vařte v konvici roztok octa nebo kyseliny citronové a pak ji vypláchněte."),
    ("Jak často měnit olej v autě?", "Výměna motorového oleje se doporučuje zhruba každých 15 000 km nebo jednou ročně."),
    ("Jaká je teplota varu vody na horách?", "S rostoucí nadmořskou výškou klesá tlak, a voda proto vře při nižší teplotě než sto stupňů."),
    ("Kdy sázet česnek?", "Ozimý česnek se sází na podzim, nejlépe v říjnu, aby zakořenil před mrazy."),
]


async def embedding_compare(rt, models: list[str]) -> list[dict]:
    """Each embedding model on the same Czech mini-test: did the right passage come first (recall@1), dimensions, speed."""
    import numpy as np

    out = []
    qs, ps = [q for q, _ in EMBED_SET], [p for _, p in EMBED_SET]
    async with rt.http() as c:
        for name in models:
            try:
                t0 = time.perf_counter()
                r = await c.post(f"{rt.local.base}/api/embed", json={"model": name, "input": qs + ps}, timeout=300)
                r.raise_for_status()
                secs = time.perf_counter() - t0
                v = np.asarray(r.json()["embeddings"], dtype=np.float32)
                v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
                sims = v[: len(qs)] @ v[len(qs):].T
                hits = int(sum(int(np.argmax(sims[i])) == i for i in range(len(qs))))
                out.append({"model": name, "ok": True, "dims": int(v.shape[1]), "recall_at_1": round(hits / len(qs), 2),
                            "texts_per_s": round((len(qs) + len(ps)) / secs, 1) if secs else None})
            except Exception as e:  # noqa: BLE001
                out.append({"model": name, "ok": False, "error": str(e)[:200]})
    return sorted(out, key=lambda x: (-(x.get("recall_at_1") or 0), -(x.get("texts_per_s") or 0)))


DEFAULT_QA = [("Kolik je 17 krát 3?", ["51"]), ("Jaké je hlavní město Slovenska?", ["bratislav"]), ("Kolik dní má přestupný rok?", ["366"]),
              ("Jak se jmenuje nejvyšší hora České republiky?", ["snezk"]), ("Napiš jen slovo PES pozpátku velkými písmeny.", ["sep"]),
              ("Kolik je 2 na desátou?", ["1024"]), ("Který plyn rostliny pohlcují při fotosyntéze?", ["oxid uhlicit", "co2"]),
              ("Kolik minut má jeden den?", ["1440", "1 440"])]


def grade(answer: str, expected: list[str]) -> bool:
    a = fold(answer).replace(" ", " ")
    return any(fold(e) in a for e in expected)


async def accuracy(rt, models: list[str], tests: list[tuple[str, list[str]]] | None = None) -> list[dict]:
    """Questions with known answers → share answered correctly per model (and which failed)."""
    tests = tests or DEFAULT_QA
    out = []
    async with rt.http() as c:
        for name in models:
            ok, fails, t0 = 0, [], time.perf_counter()
            try:
                for q, exp in tests:
                    r = await c.post(f"{rt.local.base}/api/generate", json={"model": name, "prompt": q + "\nOdpověz stručně česky.",
                                                                            "stream": False, "options": {"temperature": 0, "num_predict": 64}}, timeout=300)
                    r.raise_for_status()
                    ans = r.json().get("response", "")
                    if grade(ans, exp):
                        ok += 1
                    else:
                        fails.append({"q": q, "answer": ans.strip()[:120]})
                out.append({"model": name, "ok": True, "score": round(ok / len(tests), 2), "correct": ok, "total": len(tests),
                            "seconds": round(time.perf_counter() - t0, 1), "failed": fails})
            except Exception as e:  # noqa: BLE001
                out.append({"model": name, "ok": False, "error": str(e)[:200]})
    return sorted(out, key=lambda x: -(x.get("score") or 0))


def hardware() -> dict[str, Any]:
    from .llm.local import detect_hardware

    hw = detect_hardware()
    vram = max((g.get("vram_gb") or 0 for g in hw.get("gpus", [])), default=0)
    return {"vram_gb": vram, "ram_gb": hw.get("ram_gb", 8), "gpus": hw.get("gpus", [])}
