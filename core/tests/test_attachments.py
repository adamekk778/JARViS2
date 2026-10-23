import io

import pytest

from jarvis.attachments import AttachmentStore
from jarvis.memory import DB


@pytest.fixture
def store(tmp_path):
    return AttachmentStore(tmp_path / "files", DB(tmp_path / "a.db"))


async def test_text_file(store):
    a = await store.save("poznámky.txt", "Ahoj světe".encode(), "text/plain")
    parts = await store.llm_parts(a.id)
    assert "Ahoj světe" in parts[0]["text"] and a.kind == "text"


async def test_docx(store):
    import docx

    d = docx.Document()
    d.add_paragraph("Smlouva o dílo")
    buf = io.BytesIO()
    d.save(buf)
    a = await store.save("smlouva.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert "Smlouva o dílo" in (await store.ensure(a.id)).text


async def test_pdf(store):
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(200, 200)
    buf = io.BytesIO()
    w.write(buf)
    a = await store.save("prazdne.pdf", buf.getvalue(), "application/pdf")
    att = await store.ensure(a.id)
    assert att.kind == "pdf" and "strana 1" in att.text


async def test_garbage_pdf_still_answers(store):
    a = await store.save("rozbite.pdf", b"%PDF-garbage\x00\x01", "application/pdf")
    att = await store.ensure(a.id)
    assert att.error
    parts = await store.llm_parts(a.id)
    assert "nepodařilo přečíst" in parts[0]["text"]


async def test_truncation(store):
    a = await store.save("dlouhy.txt", ("x" * 20000).encode(), "text/plain")
    t = (await store.llm_parts(a.id))[0]["text"]
    assert "read_attachment" in t and len(t) < 8400


async def test_image_vision_and_fallback(store):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(buf, "PNG")
    a = await store.save("foto.png", buf.getvalue(), "image/png")
    parts = await store.llm_parts(a.id, vision=True)
    assert parts[1]["type"] == "image_url" and parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert store.thumb_path(a.id).name == "thumb.jpg"
    no_vision = await store.llm_parts(a.id, vision=False)
    assert no_vision[0]["type"] == "text"


async def test_audio_without_transcriber(store):
    a = await store.save("hlasovka.ogg", b"OggS....", "audio/ogg")
    att = await store.ensure(a.id)
    assert att.kind == "audio" and "přepis" in att.error


async def test_audio_with_transcriber(tmp_path):
    s = AttachmentStore(tmp_path / "f", DB(tmp_path / "b.db"), transcribe=lambda p: "ahoj z hlasovky")
    a = await s.save("hlasovka.ogg", b"OggS....", "audio/ogg")
    assert (await s.ensure(a.id)).text == "ahoj z hlasovky"


async def test_unsafe_filename(store):
    a = await store.save("../../evil\\name?.txt", b"x", "text/plain")
    assert "/" not in a.name and "\\" not in a.name and "?" not in a.name
