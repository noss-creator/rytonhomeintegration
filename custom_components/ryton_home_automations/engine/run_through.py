"""Lists automations to run one after another, without waiting for the clock.

A run-through carries out automations back to back so a house can be watched
going through every kind of day in minutes. It really switches devices.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .day_list import DayList


@dataclass(frozen=True)
class RunThroughItem:
    """One automation to carry out, and where it came from."""

    label: str  # the day, or the date and day
    automation_id: str
    name: str
    rooms: Mapping[str, Any]
    fade_seconds: float = 0


def every_automation(schedule: Mapping[str, Any]) -> list[RunThroughItem]:
    """Every automation of every day in the schedule, then the alongside ones.

    Days come in the schedule's order, switched-off combination days
    included, and each day's automations in the order they are listed. No
    calendar is involved, so days that will not occur for years are covered.
    """
    items = [
        RunThroughItem(
            day_id,
            automation.get("id", ""),
            automation.get("name", automation.get("id", "")),
            automation.get("rooms", {}),
            automation.get("fade_seconds", 0),
        )
        for day_id, day in schedule.get("days", {}).items()
        for automation in day.get("automations", ())
    ]
    items += [
        RunThroughItem(
            "alongside",
            automation.get("id", ""),
            automation.get("name", automation.get("id", "")),
            automation.get("rooms", {}),
            automation.get("fade_seconds", 0),
        )
        for automation in schedule.get("alongside", ())
    ]
    return items


def automations_of_dates(
    day_lists: Iterable[DayList], *, each_day_once: bool
) -> list[RunThroughItem]:
    """The automations of a span of dates, in time order.

    With ``each_day_once`` a kind of day that already appeared is skipped,
    so a long span runs each kind once.
    """
    items: list[RunThroughItem] = []
    seen: set[str] = set()
    for day_list in day_lists:
        day_id = day_list.day.day_id
        if each_day_once and day_id in seen:
            continue
        seen.add(day_id)
        items += [
            RunThroughItem(
                f"{day_list.date.isoformat()} {day_id}",
                automation.id,
                automation.name,
                automation.rooms,
                automation.fade_seconds,
            )
            for automation in day_list.automations
        ]
    return items
