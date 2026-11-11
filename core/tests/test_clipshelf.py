"""3.12 the notch's Schránka and Snímky: memory-only clips, pins / folders on disk, screenshots only from their folders."""
import time

from jarvis import clipshelf


def _copy(rt, text, ts):
    rt.activity.clips.appendleft({"text": text, "ts": ts, "app": "Chrome"})


def test_clips_pin_folder_unpin_and_clear(rt):
    now = time.time()
    _copy(rt, "první text", now - 20)
    _copy(rt, "druhý text", now - 10)
    st = clipshelf.clips_state(rt)
    assert [i["text"] for i in st["items"]] == ["druhý text", "první text"] and not any(i["saved"] for i in st["items"])
    first = next(i for i in st["items"] if i["text"] == "první text")
    assert clipshelf.clip_action(rt, "pin", first["id"])["ok"]
    st = clipshelf.clips_state(rt)
    assert st["items"][0]["text"] == "první text" and st["items"][0]["pinned"] and st["items"][0]["saved"]   # pinned goes first
    assert len(st["items"]) == 2                                       # no duplicate of the memory copy
    second = next(i for i in st["items"] if i["text"] == "druhý text")
    assert clipshelf.clip_action(rt, "move", second["id"], folder="Práce")["ok"]
    st = clipshelf.clips_state(rt)
    assert "Práce" in st["folders"] and next(i for i in st["items"] if i["text"] == "druhý text")["folder"] == "Práce"
    clipshelf.clip_action(rt, "clear")                                 # memory gone, saved ones stay
    assert {i["text"] for i in clipshelf.clips_state(rt)["items"]} == {"první text", "druhý text"}
    pinned = next(i for i in clipshelf.clips_state(rt)["items"] if i["text"] == "první text")
    clipshelf.clip_action(rt, "unpin", pinned["id"])                    # neither pinned nor filed → not kept on disk
    assert "první text" not in {i["text"] for i in clipshelf.clips_state(rt)["items"]}
    clipshelf.clip_action(rt, "folder_delete", name="Práce")
    assert clipshelf.clips_state(rt)["items"] == [] and clipshelf.clips_state(rt)["folders"] == []


def test_shots_only_from_screenshot_folders(rt, tmp_path):
    shots = tmp_path / "Pictures" / "Screenshots"
    shots.mkdir(parents=True)
    (shots / "Snímek obrazovky 2026-11-11.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "Desktop").mkdir()
    (tmp_path / "Desktop" / "dovolena.jpg").write_bytes(b"x")                 # a normal photo on the desktop: not a shot
    (tmp_path / "Desktop" / "Screenshot 2026.png").write_bytes(b"x")          # named as a screenshot: it is
    st = clipshelf.shots_state(rt, home=tmp_path)
    assert sorted(i["name"] for i in st["items"]) == ["Screenshot 2026.png", "Snímek obrazovky 2026-11-11.png"]
    one = st["items"][0]["path"]
    assert clipshelf.allowed_shot(rt, one, home=tmp_path) is not None
    assert clipshelf.allowed_shot(rt, str(tmp_path / "Desktop" / "dovolena.jpg"), home=tmp_path) is None
    assert clipshelf.allowed_shot(rt, str(tmp_path / "secret.png"), home=tmp_path) is None
    assert clipshelf.shot_action(rt, "pin", one, home=tmp_path)["ok"]
    assert clipshelf.shot_action(rt, "move", one, folder="Hry", home=tmp_path)["ok"]
    st = clipshelf.shots_state(rt, home=tmp_path)
    it = next(i for i in st["items"] if i["path"] == one)
    assert it["pinned"] and it["folder"] == "Hry" and st["folders"] == ["Hry"]
    assert clipshelf.shot_action(rt, "hide", one, home=tmp_path)["ok"]
    assert one not in [i["path"] for i in clipshelf.shots_state(rt, home=tmp_path)["items"]]
    assert not clipshelf.shot_action(rt, "pin", str(tmp_path / "secret.png"), home=tmp_path)["ok"]
