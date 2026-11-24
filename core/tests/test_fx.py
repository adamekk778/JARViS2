"""3.15 Mega animace: effects tiers, the frame-rate report, the pause over games, the web unit tests."""
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from jarvis import config, diagnostics

WEB = Path(__file__).resolve().parents[2] / "web"


async def test_fx_report_reaches_diagnostics(rt):
    from jarvis.server.handlers.fx import fx_report

    class C:
        pass

    c = C()
    c.rt = rt
    await fx_report(c, {"page": "hud", "fps": 58, "tier": "ultra"})
    await fx_report(c, {"page": "notch", "fps": "x", "tier": "high"})          # nonsense is ignored
    await fx_report(c, {"page": "evil<script>", "fps": 60, "tier": "high"})     # unknown windows too
    await fx_report(c, {"page": "dashboard", "fps": 9999, "tier": "warp"})
    stats = diagnostics.fx_stats(rt)
    assert {s["page"] for s in stats} == {"hud", "dashboard"}
    assert next(s for s in stats if s["page"] == "dashboard") ["fps"] == 500 and next(s for s in stats if s["page"] == "dashboard")["tier"] == ""
    assert diagnostics.fx_stats(rt, now=time.time() + 600) == []                # a closed window disappears


def test_fx_quality_setting():
    c = config.Config()
    assert c.appearance.fx_quality == "auto"
    assert "appearance.fx_quality" in config.SETTABLE_BY_VOICE
    c2 = config.apply_patch(c, {"appearance": {"fx_quality": "ultra"}})
    assert c2.appearance.fx_quality == "ultra"
    with pytest.raises(Exception):
        config.apply_patch(c, {"appearance": {"fx_quality": "insane"}})


def test_protocol_knows_the_new_messages():
    from jarvis.server import ws

    assert "fx_report" in ws.CLIENT_TYPES and "fx_pause" in ws.SERVER_TYPES


@pytest.mark.skipif(shutil.which("node") is None or not (WEB / "node_modules").exists(), reason="no node / web deps here")
def test_web_unit_tests():
    files = sorted(str(p) for p in (WEB / "tests" / "unit").glob("*.test.ts"))
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "--test", *files], cwd=WEB,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
