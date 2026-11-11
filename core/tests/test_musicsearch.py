"""3.12 music search in the notch: Deezer's public catalogue for results, the song opens on the service you pick."""
import httpx

from jarvis import musicsearch


def _transport():
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/search":
            return httpx.Response(200, json={"data": [{"id": 7, "title": "Lucid Dreams", "title_short": "Lucid Dreams", "duration": 239,
                "preview": "https://p/7.mp3", "artist": {"id": 1, "name": "Juice WRLD"}, "album": {"title": "Goodbye", "cover_medium": "https://c/7.jpg"}}]})
        if path == "/search/artist":
            return httpx.Response(200, json={"data": [{"id": 1, "name": "Juice WRLD", "picture_medium": "https://a/1.jpg", "nb_fan": 9}]})
        if path == "/search/album":
            return httpx.Response(200, json={"data": []})
        if path == "/artist/1":
            return httpx.Response(200, json={"id": 1, "name": "Juice WRLD", "picture_medium": "https://a/1.jpg", "nb_album": 4})
        if path == "/artist/1/top":
            return httpx.Response(200, json={"data": [{"id": 7, "title": "Lucid Dreams", "artist": {"id": 1, "name": "Juice WRLD"}, "album": {}}]})
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


async def test_search_artist_first_when_name_matches(rt):
    rt.transport = _transport()
    r = await musicsearch.search(rt, "juice wrld")
    assert r["top"]["kind"] == "artist" and r["top"]["name"] == "Juice WRLD"
    assert r["tracks"][0]["title"] == "Lucid Dreams" and r["tracks"][0]["cover"] == "https://c/7.jpg"
    a = await musicsearch.artist(rt, 1)
    assert a["name"] == "Juice WRLD" and a["tracks"][0]["title"] == "Lucid Dreams"
    assert (await musicsearch.search(rt, "   "))["top"] is None


async def test_play_opens_the_chosen_service(rt):
    t = {"id": 7, "title": "Lucid Dreams", "artist": "Juice WRLD"}
    assert musicsearch.link("spotify", t) == "spotify:search:Juice%20WRLD%20Lucid%20Dreams"
    assert musicsearch.link("deezer", t) == "https://www.deezer.com/track/7"
    assert musicsearch.link("deezer", {**t, "id": "x; rm"}).startswith("https://www.deezer.com/search/")
    r = await musicsearch.play(rt, "youtubemusic", t)
    assert r["ok"] and ("open_url", "https://music.youtube.com/search?q=Juice%20WRLD%20Lucid%20Dreams") in rt.platform.calls
    assert not (await musicsearch.play(rt, "spotify", {"title": ""}))["ok"]
