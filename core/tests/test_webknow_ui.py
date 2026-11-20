"""Spec 2026-11-20 §5.7: what the dashboard shows – Nastavení → Internet a znalosti and the "Co je nového" card."""


def test_snapshot_shape(rt):
    from jarvis.webknow import ui
    rt.webknow.add_digest("", "Klid.")
    rt.webknow.add_digest("sport", "Sparta.")
    rt.topics.watch("GTA 6")
    s = ui.snapshot(rt)
    assert s["digest"]["text"] == "Klid." and "svet" in s["categories"] and s["cfg"]["interval_min"] == 60
    assert s["digests"]["sport"]["text"] == "Sparta." and s["digests"]["svet"] is None
    assert s["topics"][0]["label"] == "GTA 6" and s["embed_model"] == "paraphrase-multilingual"


async def test_ws_messages(rt):
    from jarvis.server.ws import CLIENT_TYPES, SERVER_TYPES
    assert {"webknow_get", "webknow_topic", "webknow_study_now", "webknow_forget"} <= set(CLIENT_TYPES)
    assert "webknow" in SERVER_TYPES
