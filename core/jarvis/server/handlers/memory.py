"""Paměť (návrhy 8, 52, 54, 57): the model for search by meaning, imports, the memory clean-up."""
from __future__ import annotations

from ... import embedder
from . import handles


@handles("embedder_get")
async def embedder_get(c, m: dict) -> None:
    await c.send("embedder", **embedder.status())


@handles("embedder_download", local_only=True, slow=True)
async def embedder_download(c, m: dict) -> None:
    last = {"p": 0.0}

    def progress(p: float) -> None:
        if p - last["p"] >= 0.05 or p >= 1.0:
            last["p"] = p
            c.rt.bus.publish("embedder", **embedder.status(), progress=round(p, 2))
            from ...notchplus import live

            live(c.rt, "embedder", "Model pro hledání", "download-simple", p, done=p >= 1.0)
    try:
        res = await embedder.download(getattr(c.rt, "transport", None), progress)
    except Exception as e:  # noqa: BLE001 – offline, blocked…
        res = {"ok": False, "error": str(e)[:200]}
    if not res.get("ok"):
        await c.send("error", message=f"Model pro hledání podle významu se nestáhl: {res.get('error')}")
    await c.send("embedder", **embedder.status())


# ---------- 3.14 návrhy 52–57 ----------
def _path_of(c, m: dict) -> str:
    att = c.rt.store.get(str(m.get("attachment_id", ""))) if m.get("attachment_id") else None
    return str(getattr(att, "path", "") or m.get("path", ""))


@handles("memory_cleanup_get", slow=True)
async def memory_cleanup_get(c, m: dict) -> None:
    import asyncio

    from ... import memplus, paths

    s = await asyncio.to_thread(memplus.cleanup_suggestions, c.rt)
    await c.send("memory_cleanup", **s, encrypted=memplus.encryption_state(paths.data_dir()))


@handles("memory_cleanup_apply", local_only=True)
async def memory_cleanup_apply(c, m: dict) -> None:
    from ... import memplus

    memplus.apply_cleanup(c.rt, [int(i) for i in (m.get("ids") or []) if str(i).lstrip("-").isdigit()])
    await memory_cleanup_get(c, {})


@handles("memory_import_preview", local_only=True, slow=True)
async def memory_import_preview(c, m: dict) -> None:
    import asyncio

    from ... import memplus

    path = _path_of(c, m)
    try:
        prev = await asyncio.to_thread(memplus.preview_import, path)
    except (ValueError, OSError, KeyError) as e:
        await c.send("error", message=f"Tenhle soubor neumím načíst: {e}")
        return
    await c.send("memory_import", preview=prev, path=path)


@handles("memory_import_run", local_only=True, slow=True)
async def memory_import_run(c, m: dict) -> None:
    import asyncio

    from ... import memplus

    res = await asyncio.to_thread(memplus.run_import, c.rt, _path_of(c, m), str(m.get("source", "")))
    await c.send("memory_import", done=res)


@handles("data_encrypt", local_only=True, slow=True)
async def data_encrypt(c, m: dict) -> None:
    import asyncio

    from ... import memplus, paths

    r = await asyncio.to_thread(memplus.encrypt_data_folder, paths.data_dir())
    await c.send("data_encrypt_result", **r, state=memplus.encryption_state(paths.data_dir()))
