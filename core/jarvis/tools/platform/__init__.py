import sys

from .base import Platform


def get() -> Platform:
    if sys.platform == "win32":
        from .windows import WindowsPlatform

        return WindowsPlatform()
    from .unix import pick                     # 3.20 (488, 489) a Linux desktop or a Mac

    cls = pick(sys.platform)
    if cls is not None:
        return cls()
    from .null import NullPlatform

    return NullPlatform()
