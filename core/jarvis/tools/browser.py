"""Browser automation (Playwright) in a separate JARVIS browser profile, visible to the user."""
from __future__ import annotations

import asyncio
import re
import sys
from typing import Annotated

from .. import paths
from .base import ToolResult, tool

RISKY_LABEL = re.compile(r"(koupit|zaplatit|objednat|odeslat|potvrdit objednávku|buy|pay|order|checkout|purchase|submit|"
                         r"smazat|delete|odhlásit)", re.I)

INDEX_JS = r"""
() => {
  const sel = 'a[href], button, input, select, textarea, [role=button], [role=link], [role=tab], [role=menuitem], [contenteditable=true], summary';
  const out = [];
  let i = 0;
  document.querySelectorAll('[data-jarvis-idx]').forEach(e => e.removeAttribute('data-jarvis-idx'));
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none') continue;
    if (r.bottom < 0 || r.top > innerHeight * 3) continue;
    el.setAttribute('data-jarvis-idx', String(i));
    const label = (el.getAttribute('aria-label') || el.innerText || el.value || el.placeholder || el.title || el.name || '').trim().replace(/\s+/g, ' ').slice(0, 80);
    out.push({i, tag: el.tagName.toLowerCase(), type: el.type || '', label, href: el.href ? String(el.href).slice(0, 120) : undefined});
    if (++i >= 150) break;
  }
  return out;
}
"""


class BrowserSession:
    def __init__(self):
        self._pw = None
        self.ctx = None
        self.page = None
        self._lock = asyncio.Lock()

    async def ensure(self):
        if self.page and not self.page.is_closed():
            return self.page
        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()
        profile = paths.sub("browser")
        import os

        kw = {"headless": os.environ.get("JARVIS_HEADLESS") == "1", "viewport": None, "args": ["--start-maximized"]}
        if os.environ.get("JARVIS_CHROMIUM"):
            kw["executable_path"] = os.environ["JARVIS_CHROMIUM"]
        channels = ["msedge", "chrome", None] if sys.platform == "win32" else [None]
        last = None
        for ch in channels:
            try:
                self.ctx = await self._pw.chromium.launch_persistent_context(str(profile), channel=ch, **kw) if ch else \
                    await self._pw.chromium.launch_persistent_context(str(profile), **kw)
                break
            except Exception as e:
                last = e
        if self.ctx is None:
            raise RuntimeError(f"Prohlížeč se nepodařilo spustit: {last}")
        self.page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
        return self.page

    async def snapshot(self, max_chars: int = 4000) -> dict:
        page = self.page
        await page.wait_for_load_state("domcontentloaded")
        els = await page.evaluate(INDEX_JS)
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        return {"url": page.url, "title": await page.title(), "text": re.sub(r"\n{3,}", "\n\n", text)[:max_chars],
                "elements": els}

    async def close(self):
        try:
            if self.ctx:
                await self.ctx.close()
        finally:
            self.ctx = self.page = None


SESSION = BrowserSession()


@tool("browser_open", "Otevře stránku v ovladatelném prohlížeči JARVISe a vrátí text + očíslované prvky (odkazy, tlačítka, "
      "pole). Pak použij browser_click / browser_type s číslem prvku.", category="prohlížeč")
async def browser_open(ctx, url: str) -> ToolResult:
    async with SESSION._lock:
        page = await SESSION.ensure()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(1.0)
        snap = await SESSION.snapshot()
    return ToolResult(True, f"Otevřeno: {snap['title']}", data=snap)


@tool("browser_click", "Klikne na prvek v prohlížeči podle čísla z posledního přehledu. label = text prvku.",
      danger_if=lambda a: bool(RISKY_LABEL.search(str(a.get("label", "")))), category="prohlížeč")
async def browser_click(ctx, index: int, label: Annotated[str, "text prvku, na který klikáš"] = "") -> ToolResult:
    async with SESSION._lock:
        page = await SESSION.ensure()
        await page.click(f'[data-jarvis-idx="{index}"]', timeout=10000)
        await asyncio.sleep(1.2)
        snap = await SESSION.snapshot()
    return ToolResult(True, f"Kliknuto, teď: {snap['title']}", data=snap)


@tool("browser_type", "Napíše text do pole v prohlížeči (podle čísla prvku), volitelně stiskne Enter.", category="prohlížeč")
async def browser_type(ctx, index: int, text: str, submit: bool = False) -> ToolResult:
    async with SESSION._lock:
        page = await SESSION.ensure()
        loc = page.locator(f'[data-jarvis-idx="{index}"]')
        await loc.fill(text, timeout=10000)
        if submit:
            await loc.press("Enter")
            await asyncio.sleep(1.5)
        snap = await SESSION.snapshot()
    return ToolResult(True, "Napsáno", data=snap)


@tool("browser_read", "Přečte aktuální stránku v prohlížeči JARVISe (text + prvky).", category="prohlížeč")
async def browser_read(ctx, max_chars: int = 8000) -> ToolResult:
    async with SESSION._lock:
        await SESSION.ensure()
        snap = await SESSION.snapshot(max_chars)
    return ToolResult(True, snap["title"], data=snap)


@tool("browser_scroll", "Posune stránku v prohlížeči dolů (kladné) nebo nahoru (záporné).", category="prohlížeč")
async def browser_scroll(ctx, pages: float = 1.0) -> ToolResult:
    async with SESSION._lock:
        page = await SESSION.ensure()
        await page.evaluate(f"window.scrollBy(0, innerHeight * {float(pages)})")
        await asyncio.sleep(0.6)
        snap = await SESSION.snapshot()
    return ToolResult(True, "Posunuto", data=snap)


@tool("browser_screenshot", "Snímek stránky v prohlížeči do chatu.", category="prohlížeč")
async def browser_screenshot(ctx) -> ToolResult:
    async with SESSION._lock:
        page = await SESSION.ensure()
        png = await page.screenshot()
    att = await ctx.store.save("stranka.png", png, "image/png")
    return ToolResult(True, "Snímek stránky", attachments=[att.id])


@tool("browser_close", "Zavře prohlížeč JARVISe.", category="prohlížeč")
async def browser_close(ctx) -> ToolResult:
    await SESSION.close()
    return ToolResult(True, "Prohlížeč zavřen")
