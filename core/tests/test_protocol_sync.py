import re
from pathlib import Path

from jarvis.server.ws import CLIENT_TYPES, SERVER_TYPES

TS = Path(__file__).resolve().parents[2] / "web" / "src" / "shared" / "protocol.ts"


def _ts_list(name: str) -> list[str]:
    src = TS.read_text(encoding="utf-8")
    body = re.search(rf"export const {name} = \[(.*?)\] as const", src, re.S).group(1)
    return re.findall(r'"([a-z_]+)"', body)


def test_client_types_match():
    assert _ts_list("CLIENT_TYPES") == CLIENT_TYPES


def test_server_types_match():
    assert _ts_list("SERVER_TYPES") == SERVER_TYPES


def test_every_published_event_is_declared():
    """Every bus.publish("x") in the core must be a declared server type."""
    root = Path(__file__).resolve().parents[1] / "jarvis"
    published = set()
    for f in root.rglob("*.py"):
        published |= set(re.findall(r'publish(?:_threadsafe)?\("([a-z_]+)"', f.read_text(encoding="utf-8")))
    assert published <= set(SERVER_TYPES), published - set(SERVER_TYPES)
