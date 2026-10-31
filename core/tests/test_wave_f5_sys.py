"""Wave F5e: partitions (289), invisible disks + USB bridges (698 / 693 / 694), gaming (313), decision simulator (005),
connections health (586 / 587), subtitles (128), audio summary (268)."""
import datetime as dt

from jarvis import sysmore, tools
from jarvis.tools.sysmore_tools import shape_subtitles

tools.load_builtin()

PROBE = {"partitions": [{"Disk": 0, "Number": 1, "Letter": "", "Type": "System", "GB": 0.1, "FS": "FAT32", "Label": "", "FreeGB": 0.07, "Health": "Healthy"},
                        {"Disk": 0, "Number": 3, "Letter": "C", "Type": "Basic", "GB": 475.0, "FS": "NTFS", "Label": "Windows", "FreeGB": 95.0,
                         "Health": "Healthy", "Boot": True},
                        {"Disk": 0, "Number": 4, "Letter": "", "Type": "Recovery", "GB": 0.75, "FS": "NTFS", "Label": "", "FreeGB": 0.1}],
         "disks": [{"Number": 0, "FriendlyName": "Samsung SSD 980", "Bus": "NVMe", "Style": "GPT", "Status": "Online", "IsOffline": False},
                   {"Number": 1, "FriendlyName": "WD Elements", "Bus": "USB", "Style": "RAW", "Status": "Online", "IsOffline": False}],
         "pnp": [{"FriendlyName": "Samsung SSD 980", "Status": "OK", "Present": True}, {"FriendlyName": "WD Elements", "Status": "OK", "Present": True},
                 {"FriendlyName": "ST2000 External", "Status": "Error", "Present": True}],
         "usb": [{"FriendlyName": "USB Attached SCSI (UAS) Mass Storage Device", "InstanceId": "USB\\VID_152D&PID_0578\\X", "Status": "OK"}]}


def test_partitions_and_roles():
    p = sysmore.partitions_summary(PROBE)
    assert [x["role"] for x in p] == ["EFI", "systémový", "obnovovací"] and p[1]["used_pct"] == 80


def test_invisible_disks_and_bridges():
    f = sysmore.invisible_disks(PROBE)
    texts = " ".join(x["text"] for x in f)
    assert "ST2000 External" in texts and "RAW" in texts and "JMicron" in texts
    assert sysmore.bridge_of("USB\\VID_174C&PID_55AA") == "ASMedia" and sysmore.bridge_of("PCI\\VEN_1") == ""


def test_gaming_sessions():
    day = dt.date(2026, 10, 30).isoformat()
    rows = [{"day": day, "hour": h, "app": "Steam", "seconds": 3000} for h in (20, 21, 22, 23)] + \
           [{"day": day, "hour": 10, "app": "Excel", "seconds": 3600}, {"day": day, "hour": 15, "app": "Minecraft", "seconds": 1800}]
    r = sysmore.gaming_sessions(rows, 7, dt.date(2026, 10, 31))
    assert r["top"][0]["app"] == "Steam" and r["longest_h"] == 4 and r["late_h"] > 1.6 and "Excel" not in str(r["top"])


def test_decision_simulator():
    r = sysmore.simulate_decision({"bezpečná": {"gain": [10, 12, 14], "cost": [5, 5, 5], "p_success": 1.0},
                                   "riskantní": {"gain": [0, 50, 100], "cost": [10, 10, 10], "p_success": 0.4}})
    a, b = r["options"]["bezpečná"], r["options"]["riskantní"]
    assert a["p_loss"] == 0 and abs(a["expected"] - 7) < 0.2
    assert b["p_loss"] > 55 and r["safest"] == "bezpečná" and b["good_case"] > a["good_case"]


async def test_connections_health(rt):
    r = await tools.REGISTRY["connections_health"].func(rt)
    assert r.ok and any(x["name"] == "Telefon" for x in r.data)


def test_subtitle_shaping():
    segs = [(0.0, 9.0, " ".join(["slovo"] * 40)), (9.0, 10.0, "Krátká věta.")]
    subs = shape_subtitles(segs)
    assert len(subs) >= 3 and all(len(line) <= 42 for s in subs for line in s["text"].split("\n"))
    assert all(s["end"] <= n["start"] for s, n in zip(subs, subs[1:])) and subs[-1]["text"] == "Krátká věta."


async def test_audio_summary(rt):
    class Sp:
        async def synth(self, text, lang="cs", override=None):
            return b"RIFF....WAVE", "audio/wav"
    rt.speaker = Sp()
    r = await tools.REGISTRY["audio_summary"].func(rt, text="Dnes bylo hezky.", title="den")
    assert r.ok and r.data["path"].endswith(".wav")
