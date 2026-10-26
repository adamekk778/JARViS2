"""Every tool's permission area must be a real switch in Nastavení → Oprávnění – a typo would make the tool impossible
to switch off."""
from jarvis import config, permissions, tools

tools.load_builtin()


def test_every_tool_permission_is_a_real_switch():
    real = set(config.Permissions.model_fields)
    bad = {name: permissions.perm_of(spec) for name, spec in tools.REGISTRY.items() if permissions.perm_of(spec) not in real}
    assert not bad, bad
