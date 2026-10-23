"""Attachment storage + background extraction."""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from ..memory import DB
from . import extract as ex

log = logging.getLogger(__name__)
INLINE_LIMIT = 8000
TRUNC_NOTE = "[zkráceno – zbytek si přečti nástrojem read_attachment(id={id}, offset={off})]"


@dataclass
class Attachment:
    id: str
    name: str
    mime: str
    size: int
    kind: str
    path: str
    text: str | None = None
    error: str | None = None
    conv_id: str | None = None

    def public(self) -> dict:
        d = asdict(self)
        d.pop("path")
        d.pop("text")
        d["has_text"] = bool(self.text)
        d["url"] = f"/api/files/{self.id}"
        d["thumb"] = f"/api/files/{self.id}/thumb" if self.kind == "image" else None
        return d


def _safe_name(name: str) -> str:
    name = Path(name or "soubor").name
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:150] or "soubor"


class AttachmentStore:
    def __init__(self, root: Path, db: DB, transcribe=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.transcribe = transcribe
        self._pending: dict[str, asyncio.Task] = {}

    def _row_to(self, r: dict) -> Attachment:
        return Attachment(r["id"], r["name"], r["mime"], r["size"], r["kind"], r["path"], r["text"], r["error"], r["conv_id"])

    def get(self, aid: str) -> Attachment | None:
        r = self.db.one("SELECT * FROM attachments WHERE id=?", (aid,))
        return self._row_to(r) if r else None

    def _insert(self, att: Attachment) -> None:
        self.db.exec("INSERT INTO attachments VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (att.id, att.conv_id, att.name, att.mime, att.size, att.kind, att.path, att.text, att.error, time.time()))

    async def save(self, name: str, data: bytes, mime: str = "application/octet-stream", conv_id: str | None = None) -> Attachment:
        aid = uuid.uuid4().hex[:16]
        name = _safe_name(name)
        d = self.root / aid
        d.mkdir(parents=True, exist_ok=True)
        path = d / name
        await asyncio.to_thread(path.write_bytes, data)
        return self._register(aid, name, mime, path, conv_id)

    async def save_path(self, src: Path, mime: str, conv_id: str | None = None) -> Attachment:
        aid = uuid.uuid4().hex[:16]
        name = _safe_name(src.name)
        d = self.root / aid
        d.mkdir(parents=True, exist_ok=True)
        path = d / name
        await asyncio.to_thread(shutil.copy2, src, path)
        return self._register(aid, name, mime, path, conv_id)

    def _register(self, aid: str, name: str, mime: str, path: Path, conv_id: str | None) -> Attachment:
        kind = ex.kind_of(name, mime)
        att = Attachment(aid, name, mime, path.stat().st_size, kind, str(path), conv_id=conv_id)
        self._insert(att)
        try:
            self._pending[aid] = asyncio.get_running_loop().create_task(self._process(att))
        except RuntimeError:
            pass
        return att

    async def _process(self, att: Attachment) -> None:
        p = Path(att.path)
        text, err = None, None
        try:
            if att.kind == "image":
                await asyncio.to_thread(ex.make_thumb, p, p.parent / "thumb.jpg")
            text = await asyncio.to_thread(ex.extract, p, att.kind, self.transcribe)
        except Exception as e:
            log.warning("extract %s failed: %s", att.name, e)
            err = f"{type(e).__name__}: {e}"[:300]
        self.db.exec("UPDATE attachments SET text=?, error=? WHERE id=?", (text, err, att.id))
        self._pending.pop(att.id, None)

    async def ensure(self, aid: str) -> Attachment | None:
        t = self._pending.get(aid)
        if t:
            try:
                await asyncio.wait_for(asyncio.shield(t), timeout=180)
            except asyncio.TimeoutError:
                pass
        return self.get(aid)

    def thumb_path(self, aid: str) -> Path | None:
        att = self.get(aid)
        if not att:
            return None
        t = Path(att.path).parent / "thumb.jpg"
        return t if t.exists() else (Path(att.path) if att.kind == "image" else None)

    def delete(self, aid: str) -> None:
        att = self.get(aid)
        if att:
            shutil.rmtree(Path(att.path).parent, ignore_errors=True)
            self.db.exec("DELETE FROM attachments WHERE id=?", (aid,))

    async def llm_parts(self, aid: str, vision: bool = True) -> list[dict]:
        """Content parts for the user message: image_url for vision, otherwise text (≤8000 chars)."""
        att = await self.ensure(aid)
        if not att:
            return [{"type": "text", "text": f"[příloha {aid} nenalezena]"}]
        head = f"[Příloha id={att.id}: {att.name} ({att.kind}, {att.size // 1024} kB)]"
        if att.kind == "image":
            if vision:
                try:
                    data = await asyncio.to_thread(ex.to_jpeg_for_llm, Path(att.path))
                    url = "data:image/jpeg;base64," + base64.b64encode(data).decode()
                    return [{"type": "text", "text": head}, {"type": "image_url", "image_url": {"url": url}}]
                except Exception as e:
                    att.error = str(e)
            ocr = await asyncio.to_thread(ex.ocr_bytes, Path(att.path).read_bytes())
            if ocr:
                return [{"type": "text", "text": f"{head}\nText rozpoznaný z obrázku (OCR):\n{ocr[:INLINE_LIMIT]}"}]
            return [{"type": "text", "text": f"{head}\n[obrázek – aktuální model ho nevidí a OCR není k dispozici]"}]
        if att.error and not att.text:
            return [{"type": "text", "text": f"{head}\n[obsah se nepodařilo přečíst: {att.error}] Soubor je uložený, "
                                             f"můžeš ho uložit/otevřít nástrojem save_attachment."}]
        text = att.text or ""
        if not text:
            note = "[video – obsah se neanalyzuje, jen soubor]" if att.kind == "video" else "[binární soubor bez textu]"
            return [{"type": "text", "text": f"{head}\n{note}"}]
        if len(text) > INLINE_LIMIT:
            text = text[:INLINE_LIMIT] + "\n" + TRUNC_NOTE.format(id=att.id, off=INLINE_LIMIT)
        return [{"type": "text", "text": f"{head}\n{text}"}]
