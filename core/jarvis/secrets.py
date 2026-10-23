"""API keys: Windows Credential Manager via keyring, file fallback elsewhere."""
from __future__ import annotations

import json

from . import paths

SERVICE = "JARVIS2"


def _file():
    return paths.data_dir() / "secrets.json"


def _file_data() -> dict:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _keyring():
    try:
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def get(name: str) -> str:
    kr = _keyring()
    if kr:
        try:
            v = kr.get_password(SERVICE, name)
            if v:
                return v
        except Exception:
            pass
    return _file_data().get(name, "")


def set(name: str, value: str) -> None:  # noqa: A001
    kr = _keyring()
    if kr:
        try:
            if value:
                kr.set_password(SERVICE, name, value)
            else:
                kr.delete_password(SERVICE, name)
            return
        except Exception:
            pass
    data = _file_data()
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    _file().write_text(json.dumps(data), encoding="utf-8")


def has(name: str) -> bool:
    return bool(get(name))
