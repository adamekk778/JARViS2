"""OMEGA wave 11 (workspaces): save / restore / compare with a fake window manager, monitor move, crashed apps,
shortcuts, command history."""
import time

from jarvis import tools, workspace

tools.load_builtin()


class Desk:
    """A tiny fake window manager for the NullPlatform."""

    def __init__(self, wins):
        self.wins = {w["hwnd"]: dict(w) for w in wins}
        self.opened = []

    def layout(self):
        return [dict(w) for w in self.wins.values()]

    def place(self, hwnd, x, y, w, h, state="normal"):
        self.wins[hwnd].update(x=x, y=y, w=w, h=h, state=state)
        return True

    def open_path(self, path):
        self.opened.append(path)
        hwnd = max(self.wins) + 1
        self.wins[hwnd] = {"hwnd": hwnd, "title": "Nový dokument", "exe": path.split("\\")[-1], "path": path, "app": "", "x": 0, "y": 0, "w": 300, "h": 200, "state": "normal"}


def install(rt, desk):
    rt.platform.window_layout = desk.layout
    rt.platform.place_window = desk.place
    rt.platform.open_path = desk.open_path


WINS = [{"hwnd": 1, "title": "Rozpočet.xlsx - Excel", "exe": "EXCEL.EXE", "path": "C:\\Office\\EXCEL.EXE", "app": "Excel", "x": 0, "y": 0, "w": 960, "h": 1040, "state": "normal"},
        {"hwnd": 2, "title": "Inbox - Outlook", "exe": "OUTLOOK.EXE", "path": "C:\\Office\\OUTLOOK.EXE", "app": "Outlook", "x": 960, "y": 0, "w": 960, "h": 1040, "state": "normal"}]


async def test_save_compare_restore(rt, monkeypatch):
    import os

    desk = Desk(WINS)
    install(rt, desk)
    assert (await tools.call("workspace_save", {"name": "Práce"}, rt)).ok
    # later: Outlook closed, Excel moved, Spotify opened
    del desk.wins[2]
    desk.wins[1].update(x=300, state="maximized")
    desk.wins[7] = {"hwnd": 7, "title": "Spotify", "exe": "Spotify.exe", "path": "C:\\S\\Spotify.exe", "app": "Spotify", "x": 0, "y": 0, "w": 800, "h": 600, "state": "normal"}
    c = await tools.call("workspace_compare", {"name": "práce"}, rt)
    assert "chybí Outlook" in c.summary and "posunuté Excel" in c.summary and "navíc Spotify" in c.summary
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    r = await tools.call("workspace_restore", {"name": "Práce"}, rt)
    assert r.ok and desk.opened == ["C:\\Office\\OUTLOOK.EXE"] and r.data["placed"] == 2
    assert desk.wins[1]["x"] == 0 and desk.wins[1]["state"] == "normal"
    new = next(w for w in desk.wins.values() if w["exe"] == "OUTLOOK.EXE")
    assert (new["x"], new["w"]) == (960, 960)
    assert "Práce (2 oken)" in (await tools.call("workspace_list", {}, rt)).summary
    assert (await tools.call("workspace_delete", {"name": "Práce"}, rt)).ok
    assert not (await tools.call("workspace_restore", {"name": "Práce"}, rt)).ok


async def test_window_to_monitor(rt, monkeypatch):
    from jarvis.desktop import pet, platforms

    desk = Desk(WINS)
    install(rt, desk)
    monkeypatch.setattr(platforms, "monitors", lambda: [(pet.Rect(0, 0, 1920, 1080), pet.Rect(0, 0, 1920, 1040)),
                                                        (pet.Rect(1920, 0, 1280, 1024), pet.Rect(1920, 0, 1280, 984))])
    r = await tools.call("window_to_monitor", {"app": "outlook", "monitor": 2}, rt)
    assert r.ok and desk.wins[2]["x"] == 1920 + (1280 - 960) // 2
    assert not (await tools.call("window_to_monitor", {"app": "outlook", "monitor": 3}, rt)).ok


def test_crashed_recently():
    now = time.time()
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))  # noqa: E731
    errs = [{"App": "chrome.exe", "Time": iso(now - 600)}, {"App": "game.exe", "Time": iso(now - 7200)}, {"App": "word.exe", "Time": iso(now - 300)}]
    assert workspace.crashed_recently(errs, {"word.exe"}, 60, now) == ["chrome.exe"]


async def test_shortcuts_and_history(rt):
    r = await tools.call("shortcuts", {"app": "WINWORD.EXE"}, rt)
    assert r.data["app"] == "word" and "F7 = kontrola pravopisu" in r.summary
    assert (await tools.call("shortcuts", {"app": "neznámý"}, rt)).data["app"] == "windows"
    rt.memory.add_message("user", "Otevři mi rozpočet v Excelu")
    tid = rt.tasks.begin("rozpočet", rt.memory.current_conversation)
    rt.tasks.log_action("open_file", {"path": "rozpočet.xlsx"}, True, "Otevřeno rozpočet.xlsx", 10)
    h = await tools.call("command_history", {"query": "rozpočet"}, rt)
    assert h.ok and {x["kind"] for x in h.data} == {"akce", "příkaz"} and tid
