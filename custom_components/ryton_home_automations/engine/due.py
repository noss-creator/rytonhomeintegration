"""Which automations are still to come, and which were missed."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .day_list import DayList, ScheduledAutomation


def split_due(
    day_lists: Iterable[DayList],
    last_run: datetime | None,
    now: datetime,
) -> tuple[list[ScheduledAutomation], list[ScheduledAutomation]]:
    """Return (missed, upcoming) from the fixed lists, each in time order.

    Upcoming automations are those timed after ``now``. Missed ones were
    timed after ``last_run``, the moment the engine last ran or caught up,
    and up to ``now``. With no ``last_run`` nothing counts as missed, so a
    house is not swept through a whole day's automations the first time the
    engine starts.
    """
    automations = sorted(
        (a for day_list in day_lists for a in day_list.moments),
        key=lambda a: a.time,
    )
    upcoming = [a for a in automations if a.time > now]
    if last_run is None:
        return [], upcoming
    missed = [a for a in automations if last_run < a.time <= now]
    return missed, upcoming
