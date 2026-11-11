"""3.12 Zeptej se na obrazovku: pick an area (Windows snipping), the notch offers what to do, JARVIS answers about it."""
import io
import json

import httpx
from PIL import Image

from jarvis import screenask
from jarvis.config import Brain, ProviderCfg
from jarvis.llm.router import Router


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (400, 120), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


async def test_picked_area_is_offered_and_asked_about_with_the_picture(rt, monkeypatch):
    seq = [1]
    monkeypatch.setattr(rt.platform, "clipboard_seq", lambda: seq[0], raising=False)
    opened = []

    def open_snip():
        opened.append(1)
        seq[0] = 2                      # you picked an area → the picture lands in the clipboard

    events = []
    q = rt.bus.subscribe()
    st = await screenask.start(rt, open_snip=open_snip, grab=png_bytes)
    while not q.empty():
        m = q.get_nowait()
        if m.get("type") == "screen_ask":
            events.append(m)
    assert opened and st["att"] and [e["state"] for e in events] == ["picking", "ready"]
    assert events[-1]["thumb"].startswith("data:image/jpeg") and {a["key"] for a in events[-1]["actions"]} >= {"explain", "translate"}

    asked = []

    async def fake_handle(text, atts, source, **kw):
        asked.append((text, atts, source))
        return "To je chybová hláška…"

    monkeypatch.setattr(rt.agent, "handle", fake_handle)
    await screenask.act(rt, "translate")
    await screenask.act(rt, "", "Co znamená ta červená?")
    assert asked[0][1] == [st["att"]] and "Přelož" in asked[0][0]
    assert asked[1][0].startswith("Co znamená ta červená?")


async def test_nothing_picked_means_nothing_happens(rt, monkeypatch):
    monkeypatch.setattr(rt.platform, "clipboard_seq", lambda: 1, raising=False)
    monkeypatch.setattr(screenask, "PICK_TIMEOUT_S", 0.6)
    assert await screenask.start(rt, open_snip=lambda: None, grab=png_bytes) == {}


async def test_a_picture_goes_to_groqs_model_that_can_see():
    seen = []

    def handler(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        seen.append(json.loads(req.content)["model"])
        body = 'data: {"choices":[{"delta":{"content":"vidim"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())

    r = Router(Brain(providers=[ProviderCfg(id="groq", preset="groq", model="openai/gpt-oss-120b")], chain=["groq"]),
               lambda _: "gsk_x", httpx.MockTransport(handler))
    msgs = [{"role": "user", "content": [{"type": "text", "text": "co to je"},
                                         {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
    async for _ in r.stream(msgs, None, need_vision=True):
        pass
    assert seen == ["meta-llama/llama-4-scout-17b-16e-instruct"]
