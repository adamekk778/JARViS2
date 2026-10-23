import pytest

from jarvis import config, tools
from jarvis.permissions import perm_of
from jarvis.redact import looks_secret, redact

tools.load_builtin()


@pytest.mark.parametrize("name,perm", [
    ("open_app", "apps"), ("computer_use", "input"), ("type_text", "input"), ("press_keys", "input"),
    ("screenshot", "screen"), ("read_text_file", "files_read"), ("list_folder", "files_read"),
    ("write_text_file", "files_write"), ("run_shell", "shell"), ("run_python", "shell"), ("create_skill", "shell"),
    ("web_search", "network"), ("browser_open", "network"), ("system_power", "system"),
    ("clipboard_get", "apps"), ("get_time", "apps"),
])
def test_default_mapping(name, perm):
    assert perm_of(tools.REGISTRY[name]) == perm


def test_schemas_filtered():
    cfg = config.Config.model_validate({"permissions": {"shell": False}})
    names = {s["function"]["name"] for s in tools.schemas((), cfg)}
    assert "run_shell" not in names and "open_app" in names
    assert "run_shell" in {s["function"]["name"] for s in tools.schemas()}


async def test_call_refused(ctx):
    ctx.cfg = config.Config.model_validate({"permissions": {"input": False}})
    res = await tools.call("type_text", {"text": "x"}, ctx)
    assert not res.ok and "Oprávnění" in res.summary
    assert not any(c[0] == "type_text" for c in ctx.platform.calls)


def test_migration():
    assert config.Config.model_validate({"tools": {"computer_use": False}}).permissions.input is False
    assert config.Config.model_validate({}).permissions.input is True
    explicit = {"tools": {"computer_use": False}, "permissions": {"input": True}}
    assert config.Config.model_validate(explicit).permissions.input is True


def test_redact():
    out = redact("klíč sk-abcdefghijklmnop1234 a token=ABCDEF0123456789abcdef")
    assert "sk-abcdefghijklmnop1234" not in out and "ABCDEF0123456789abcdef" not in out and "•••" in out
    assert looks_secret("heslo je Tajne123!")
    assert not looks_secret("mám rád pizzu")


def test_redact_literal():
    from jarvis import redact as r

    r.add_literal("PAIRTOKEN_xyz_987654")
    assert "PAIRTOKEN_xyz_987654" not in redact("ws?token=PAIRTOKEN_xyz_987654&a=1")
