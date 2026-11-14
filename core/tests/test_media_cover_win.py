"""3.12 the notch showed Spotify's icon instead of the album cover (a real PC). The cover is read the way Windows
hands it over – checked on real Windows (CI) with an in-memory picture behind a stream reference."""
import asyncio
import base64
import sys

import pytest

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows media API")
def test_the_cover_is_read_from_a_windows_stream():
    winsdk = pytest.importorskip("winsdk")
    from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream, RandomAccessStreamReference

    from jarvis.desktop import media

    async def go():
        ms = InMemoryRandomAccessStream()
        w = DataWriter(ms)
        w.write_bytes(PNG)
        await w.store_async()
        await w.flush_async()
        w.detach_stream()
        ms.seek(0)
        ref = RandomAccessStreamReference.create_from_stream(ms)
        return await media._thumb(ref)

    assert winsdk
    url = asyncio.run(go())
    assert url and url.startswith("data:image/") and base64.b64decode(url.split(",", 1)[1]) == PNG
