"""3.0 extras: what's new once per feature version, your own sounds, the wardrobe setting."""
from fastapi.testclient import TestClient

from jarvis import __version__, config
from jarvis.server.app import create_app


def test_whats_new_once_per_feature_version(rt):
    mm = ".".join(__version__.split(".")[:2])
    assert rt.whats_new_due() == mm
    rt.whats_new_seen()
    assert rt.whats_new_due() == ""
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('whats_new_seen', '2.1')")
    assert rt.whats_new_due() == mm


def test_custom_sounds_by_czech_or_english_name(rt):
    d = rt.sounds_dir()
    assert (d / "PRECTI-ME.txt").exists()
    (d / "hotovo.mp3").write_bytes(b"ID3fake")
    (d / "error.wav").write_bytes(b"RIFFfake")
    (d / "random.mp3").write_bytes(b"x")
    assert rt.custom_sounds() == {"done": "hotovo.mp3", "error": "error.wav"}
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c:
        r = c.get("/api/sounds/done")
        assert r.status_code == 200 and r.content == b"ID3fake"
        assert c.get("/api/sounds/wake").status_code == 404
        assert c.get("/api/sounds/..%2Fconfig").status_code == 404
    with TestClient(create_app(rt, manage_runtime=False), client=("192.168.1.9", 5000)) as c:
        assert c.get("/api/sounds/done").status_code == 401


def test_open_sounds_folder_uses_platform(rt):
    rt.open_sounds_folder()
    assert any(c[0] == "open_path" and c[1].endswith("sounds") for c in rt.platform.calls)


def test_outfit_setting_and_voice():
    assert config.Config().character.outfit == "auto"
    assert config.Config.model_validate({"character": {"outfit": "crown"}}).character.outfit == "crown"
    assert "character.outfit" in config.SETTABLE_BY_VOICE and "dictation.cleanup" in config.SETTABLE_BY_VOICE


def test_welcome_carries_30_state(rt):
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c, c.websocket_connect("/ws") as ws:
        w = ws.receive_json()
        assert w["whats_new"] and w["claude_sessions"] == [] and w["claude_pending"] == [] and "sounds" in w
