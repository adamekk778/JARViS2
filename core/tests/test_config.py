import pytest

from jarvis import config, secrets


def test_defaults():
    cfg = config.load()
    assert cfg.brain.chain == ["omniroute", "ollama"]
    assert cfg.phone.port == 8765
    assert cfg.brain.providers[0].base_url == "http://localhost:20128/v1"
    assert cfg.voice.tts_voice == "cs-CZ-AntoninNeural"
    assert len(cfg.phone.token) > 30


def test_roundtrip():
    cfg = config.load()
    cfg.general.user_name = "Adam"
    config.save(cfg)
    assert config.load().general.user_name == "Adam"


def test_patch_merges():
    cfg = config.load()
    new = config.apply_patch(cfg, {"voice": {"tts_rate": "+10%"}})
    assert new.voice.tts_rate == "+10%"
    assert new.voice.tts_voice == cfg.voice.tts_voice


def test_patch_invalid():
    cfg = config.load()
    with pytest.raises(ValueError):
        config.apply_patch(cfg, {"voice": {"speak_mode": "sometimes"}})
    with pytest.raises(ValueError):
        config.apply_patch(cfg, {"nonsense": {}})


def test_public_dump_hides_token():
    assert "token" not in config.public_dump(config.load())["phone"]


def test_broken_config_recovers(jarvis_home):
    jarvis_home.mkdir(parents=True, exist_ok=True)
    (jarvis_home / "config.toml").write_text("this is [[[ not toml")
    assert config.load().phone.port == 8765


def test_secrets_file_fallback():
    secrets.set("groq", "abc")
    assert secrets.get("groq") == "abc"
    secrets.set("groq", "")
    assert secrets.get("groq") == ""


def test_2_1_defaults():
    from jarvis import config

    c = config.Config()
    assert c.notch.pinned is False and c.appearance.sounds is True and c.appearance.sound_volume == 30
    assert c.hotkeys.stop_all == "ctrl+alt+x" and c.agent.mode is False and c.brain.local_mode == "balanced"
