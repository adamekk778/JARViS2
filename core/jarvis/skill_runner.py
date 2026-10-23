"""Runs one tool of a skill in its own process (spec §10): a crash or hang can't take JARVIS down.

Protocol on stdout: "@@NOTIFY {json}" lines (forwarded as notifications) and one "@@RESULT {json}" line.
This is crash/timeout isolation, not a security sandbox.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from types import SimpleNamespace


class _Denied:
    def __getattr__(self, name):
        raise PermissionError("Tento skill nemá oprávnění ovládat počítač (manifest permissions).")


def _ctx(permissions: list[str]):
    import httpx

    def notify(title, body="", url="", speak=True, target="all"):
        print("@@NOTIFY " + json.dumps({"title": str(title), "body": str(body)}, ensure_ascii=False), flush=True)
        return 1

    platform = _Denied()
    if {"input", "apps"} & set(permissions):
        from .tools.platform import get_platform

        platform = get_platform()
    return SimpleNamespace(http=lambda: httpx.AsyncClient(timeout=30), notify=notify, platform=platform)


def main(argv: list[str]) -> int:
    path, tool_name, args_json = argv[0], argv[1], argv[2] if len(argv) > 2 else "{}"
    from .tools import base
    from .tools.skills import read_manifest

    manifest = read_manifest(path)
    spec = importlib.util.spec_from_file_location("jarvis_skill_run", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_skill_run"] = mod
    spec.loader.exec_module(mod)
    ts = base.REGISTRY.get(tool_name)
    if ts is None:
        raise LookupError(f"nástroj {tool_name} ve skillu není")
    args = json.loads(args_json)
    args = {k: v for k, v in args.items() if k in ts.parameters.get("properties", {})}

    async def run():
        out = ts.func(_ctx(manifest["permissions"]), **args)  # exceptions propagate → "Skill spadl" in the parent
        if asyncio.iscoroutine(out):
            out = await out
        return out if isinstance(out, base.ToolResult) else base.ToolResult(True, str(out) if out is not None else "hotovo")

    res = asyncio.run(run())
    print("@@RESULT " + json.dumps({"ok": res.ok, "summary": res.summary, "data": res.data},
                                   ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:  # reported to the parent via stderr + exit code
        print(f"{type(e).__name__}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
