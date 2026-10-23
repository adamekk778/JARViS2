"""MCP client: every configured MCP server's tools become JARVIS tools (mcp__server__tool)."""
from __future__ import annotations

import asyncio
import logging
import os
import re

from ..tools.base import REGISTRY, ToolResult, ToolSpec, register, unregister_source

log = logging.getLogger(__name__)
WRITE_WORDS = re.compile(r"(send|delete|remove|create|write|post|update|move|rename|pay|buy|edit|set|insert|drop|kill)", re.I)


def _safe(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s)


def _content_text(result) -> tuple[str, bool]:
    parts = []
    for c in getattr(result, "content", None) or []:
        t = getattr(c, "text", None)
        if t:
            parts.append(t)
        elif getattr(c, "type", "") == "image":
            parts.append("[obrázek]")
        elif getattr(c, "resource", None) is not None:
            parts.append(str(getattr(c.resource, "text", "") or getattr(c.resource, "uri", "")))
    sc = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if not parts and sc:
        parts.append(str(sc))
    return "\n".join(parts), bool(getattr(result, "isError", False) or getattr(result, "is_error", False))


class McpManager:
    def __init__(self, rt):
        self.rt = rt
        self._tasks: dict[str, asyncio.Task] = {}
        self._stops: dict[str, asyncio.Event] = {}
        self._status: dict[str, dict] = {}

    def status(self) -> list[dict]:
        return [{"name": s.name, **self._status.get(s.name, {"ok": False, "error": "nepřipojeno", "tools": 0})}
                for s in self.rt.cfg.integrations.mcp]

    async def start(self) -> None:
        for s in self.rt.cfg.integrations.mcp:
            if s.enabled and (s.command or s.url) and s.name not in self._tasks:
                self._stops[s.name] = asyncio.Event()
                self._tasks[s.name] = asyncio.get_running_loop().create_task(self._serve(s))

    async def stop(self) -> None:
        for ev in self._stops.values():
            ev.set()
        for t in self._tasks.values():
            t.cancel()
        self._tasks.clear()
        self._stops.clear()

    def on_config(self, cfg) -> None:
        async def restart():
            await self.stop()
            await self.start()

        self.rt.call_soon(lambda: asyncio.get_running_loop().create_task(restart()))

    async def _connect(self, s):
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        if s.url:
            try:
                from mcp.client.streamable_http import streamable_http_client as http_client
            except ImportError:  # mcp < 2
                from mcp.client.streamable_http import streamablehttp_client as http_client
            if s.url.rstrip("/").endswith("/sse"):
                from mcp.client.sse import sse_client

                return sse_client(s.url)
            return http_client(s.url)
        errlog = open(os.devnull, "w")  # windowed app has no stderr
        return stdio_client(StdioServerParameters(command=s.command, args=list(s.args), env={**os.environ, **s.env}), errlog=errlog)

    async def _serve(self, s) -> None:
        from mcp import ClientSession

        source = f"mcp:{s.name}"
        backoff = 5
        while not self._stops[s.name].is_set():
            try:
                async with self._connect_cm(s) as streams:
                    read, write = streams[0], streams[1]
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        unregister_source(source)
                        for t in listed.tools:
                            self._register(s.name, source, session, t)
                        n = sum(1 for v in REGISTRY.values() if v.source == source)
                        self._status[s.name] = {"ok": True, "tools": n, "error": None}
                        log.info("MCP %s: %d tools", s.name, n)
                        backoff = 5
                        await self._stops[s.name].wait()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("MCP %s failed: %s", s.name, e)
                self._status[s.name] = {"ok": False, "tools": 0, "error": str(e)[:200]}
                unregister_source(source)
                try:
                    await asyncio.wait_for(self._stops[s.name].wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    backoff = min(backoff * 2, 300)
        unregister_source(source)

    def _connect_cm(self, s):
        return _LazyCM(self._connect, s)

    def _register(self, server: str, source: str, session, t) -> None:
        name = f"mcp__{_safe(server)}__{_safe(t.name)}"[:64]
        ann = getattr(t, "annotations", None)
        read_only = bool(getattr(ann, "readOnlyHint", False) or getattr(ann, "read_only_hint", False))
        destructive = getattr(ann, "destructiveHint", None) or getattr(ann, "destructive_hint", None)
        danger = bool(destructive) or (not read_only and bool(WRITE_WORDS.search(t.name)))
        schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {"type": "object", "properties": {}}

        async def call(ctx, **args):
            res = await session.call_tool(t.name, args)
            text, is_err = _content_text(res)
            return ToolResult(not is_err, text[:200] or ("chyba" if is_err else "hotovo"), data=text[:10000])

        register(ToolSpec(name, f"[{server}] {t.description or t.name}"[:1000], call, schema, danger, None, f"MCP: {server}", source))


class _LazyCM:
    """Await the factory, then use the returned async context manager."""

    def __init__(self, factory, s):
        self.factory, self.s, self.cm = factory, s, None

    async def __aenter__(self):
        self.cm = await self.factory(self.s)
        return await self.cm.__aenter__()

    async def __aexit__(self, *exc):
        return await self.cm.__aexit__(*exc)
