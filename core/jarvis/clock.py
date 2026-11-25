"""3.20 One place to read today's date and the time for the travel parts.

Dated data (a hotel from 11. 12., a free cancellation until 9. 12.) is checked against "today". Reading it here lets
the tests pin the day their example data was written for – without that, the tests would start failing on the
day those dates pass. In the app the offset is always 0, so this is just the real clock.
"""
from __future__ import annotations

import datetime as dt
import time

_offset = 0.0          # seconds added to the real clock (only tests set it)


def now_ts() -> float:
    return time.time() + _offset


def now() -> dt.datetime:
    return dt.datetime.fromtimestamp(now_ts())


def today() -> dt.date:
    return now().date()


def pin(when: dt.datetime | None) -> None:
    """Tests: from now on the clock reads `when` (and goes on from there); None = the real clock again."""
    global _offset
    _offset = 0.0 if when is None else when.timestamp() - time.time()
