import sys

from .base import Platform


def get() -> Platform:
    if sys.platform == "win32":
        from .windows import WindowsPlatform

        return WindowsPlatform()
    from .null import NullPlatform

    return NullPlatform()
