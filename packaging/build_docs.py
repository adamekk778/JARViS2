"""3.20 (485) The documentation website: the Markdown in docs/ (and README, SECURITY, CONTRIBUTING) → site/docs/*.html
for GitHub Pages. A small converter on purpose (headings, lists, code, tables as text, links, bold) – no dependencies."""
from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = [("README.md", "Úvod"), ("docs/INTEGRATIONS.md", "Propojení"), ("docs/SERVER.md", "Domácí server"), ("docs/WINGET.md", "Instalace"),
         ("docs/IPHONE.md", "iPhone"), ("docs/SDK.md", "Dovednosti (SDK)"), ("docs/ROADMAP.md", "Roadmapa"), ("SECURITY.md", "Bezpečnost"),
         ("CONTRIBUTING.md", "Jak přispět")]
STYLE = ("body{margin:0;font:16px/1.6 system-ui;background:#0b1118;color:#e8f1f8}nav{padding:14px 20px;background:#0f1922;display:flex;gap:16px;"
         "flex-wrap:wrap}nav a{color:#5fd3ff;text-decoration:none}main{max-width:860px;margin:auto;padding:20px}pre{background:#0f1922;padding:12px;"
         "border-radius:10px;overflow:auto}code{background:#13202c;padding:1px 5px;border-radius:5px}a{color:#5fd3ff}h1,h2,h3{color:#fff}")


def inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+|[\w./#-]+)\)", lambda m: f'<a href="{doc_link(m.group(2))}">{m.group(1)}</a>', s)


def doc_link(target: str) -> str:
    if target.startswith("http"):
        return html.escape(target, quote=True)
    name = Path(target.split("#")[0]).stem.lower()
    return f"{name}.html" if any(Path(p).stem.lower() == name for p, _ in PAGES) else html.escape(target, quote=True)


def convert(md: str) -> str:
    out, para, in_code, in_list = [], [], False, False

    def flush() -> None:
        nonlocal para
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para = []

    for line in md.splitlines():
        if line.startswith("```"):
            flush()
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        li = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)", line)
        if m:
            flush()
            if in_list:
                out.append("</ul>")
                in_list = False
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif li:
            flush()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(li.group(1))}</li>")
        elif not line.strip():
            flush()
            if in_list:
                out.append("</ul>")
                in_list = False
        else:
            para.append(line.strip())
    flush()
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


def build(dest: Path = ROOT / "site" / "docs") -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    nav = "".join(f'<a href="{Path(p).stem.lower()}.html">{t}</a>' for p, t in PAGES if (ROOT / p).exists())
    made = []
    for src, title in PAGES:
        f = ROOT / src
        if not f.exists():
            continue
        page = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{title} – JARVIS</title>"
                f"<style>{STYLE}</style><nav><a href='../index.html'>JARVIS</a>{nav}</nav><main>{convert(f.read_text(encoding='utf-8'))}</main>")
        out = dest / f"{Path(src).stem.lower()}.html"
        out.write_text(page, encoding="utf-8")
        made.append(out)
    (dest / "index.html").write_text((dest / "readme.html").read_text(encoding="utf-8"), encoding="utf-8")
    return made


if __name__ == "__main__":
    print("\n".join(str(p) for p in build()))
