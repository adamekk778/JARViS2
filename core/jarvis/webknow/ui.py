"""Spec 2026-11-20 §5.7: what the dashboard shows for Nastavení → Internet a znalosti and the "Co je nového" card."""
from __future__ import annotations

from . import sources
from .semantic import EMBED_MODEL


def snapshot(rt) -> dict:
    store = rt.webknow
    cfg = rt.cfg.webknow
    return {"stats": store.stats(), "topics": rt.topics.list(), "digest": store.latest_digest(""),
            "digests": {k: store.latest_digest(k) for k in sources.CATEGORY_NAMES if k in cfg.categories},
            "categories": sources.CATEGORY_NAMES, "cfg": cfg.model_dump(), "embed_model": EMBED_MODEL}
