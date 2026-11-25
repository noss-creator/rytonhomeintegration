"""Builds a date's fixed list: each automation, its time, and its rooms.

This puts the pieces together for one date: the day it resolves to, Shabbos
start, each automation's clock time, simcha mode, and the running-alongside
automations. It can run for any date, which is how the year preview and the
upcoming schedule are produced.

Not handled here: the client's temporary changes and the room switches.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Any

from .alongside import alongside_for
from .calendar_source import CalendarSource
from .day_resolver import ResolvedDay, resolve_day
from .scenes import schedule_scenes
from .day_tables import CHOL_HAMOED, table_for
from .time_resolver import (
    ScheduleError,
    check_rollover,
    resolve_shabbos_start,
    resolve_time,
)

FORMAT_VERSION = 1
NIGHT = "night"


@dataclass(frozen=True)
class ScheduledAutomation:
    """One automation of a date, with its time already fixed."""

    id: str
    name: str
    time: datetime
    fade_seconds: float
    rooms: Mapping[str, Any]
    alongside: bool = False


@dataclass(frozen=True)
class DayList:
    """A date's fixed list, in time order."""

    date: date
    day: ResolvedDay
    shabbos_start: datetime | None
    automations: tuple[ScheduledAutomation, ...]


def check_schedule(schedule: Mapping[str, Any]) -> None:
    """Refuse a schedule the engine does not understand."""
    version = schedule.get("format_version")
    if version != FORMAT_VERSION:
        raise ScheduleError(f"Schedule format version {version!r} is not understood")
    for key in ("settings", "days"):
        if not isinstance(schedule.get(key), Mapping):
            raise ScheduleError(f"The schedule has no {key}")
    schedule_scenes(schedule)


def _day_entry(schedule: Mapping[str, Any], day_id: str) -> Mapping[str, Any]:
    entry = schedule["days"].get(day_id)
    if not isinstance(entry, Mapping):
        raise ScheduleError(f"The schedule has no day {day_id!r}")
    return entry


def resolve_schedule_day(
    schedule: Mapping[str, Any], day: date, source: CalendarSource
) -> Any:
    """Return which of the schedule's days ``day`` is. No times are worked out."""
    settings = schedule["settings"]
    table = table_for(settings.get("yom_tov_days"), settings.get("purim"))
    return resolve_day(
        day, source, table, lambda day_id: bool(_day_entry(schedule, day_id).get("enabled"))
    )


def build_day_list(
    schedule: Mapping[str, Any],
    day: date,
    source: CalendarSource,
    tz: tzinfo,
    *,
    one_week: Mapping[str, Any] | None = None,
    simcha: bool = False,
) -> DayList:
    """Return the fixed list for ``day``.

    ``one_week`` is the client's one-week Shabbos switch for this week, and
    ``simcha`` says whether simcha mode is on for this date. Both are stored
    in the house.
    """
    check_schedule(schedule)
    settings = schedule["settings"]
    rollover = settings.get("day_rollover", "04:00")

    table = table_for(settings.get("yom_tov_days"), settings.get("purim"))
    resolved = resolve_schedule_day(schedule, day, source)
    entry = _day_entry(schedule, resolved.day_id)

    rules = settings.get("early_shabbos_rules", ())
    if resolved.occasion in table.yom_tov:
        # There is no early Shabbos on a Friday that is itself Yom Tov:
        # neither the rules nor the client's one-week switch apply.
        rules = ()
        one_week = None
    # Below, the rules are skipped but the client's one-week early switch
    # still applies.
    elif resolved.occasion in table.friday_before_yom_tov:
        # The Shabbos that follows is Yom Tov, and early Shabbos never
        # applies to Yom Tov.
        rules = ()
    elif resolved.occasion in CHOL_HAMOED and not settings.get(
        "early_shabbos_on_chol_hamoed", False
    ):
        # A regular Shabbos on Chol Hamoed, unless the house chose early.
        rules = ()
    shabbos_start = resolve_shabbos_start(day, source, tz, rules, one_week=one_week)

    def fix(spec: Any, allow_past_rollover: bool) -> datetime:
        if not isinstance(spec, Mapping):
            raise ScheduleError(f"{resolved.day_id}: an automation has no time")
        when = resolve_time(spec, day, source, tz, shabbos_start)
        check_rollover(when, day, tz, rollover, allow_past_rollover)
        return when

    automations: list[ScheduledAutomation] = []
    seen: set[str] = set()
    day_allows = bool(entry.get("allow_past_rollover"))

    for automation in entry.get("automations", ()):
        automation_id = automation.get("id")
        if not automation_id or automation_id in seen:
            raise ScheduleError(
                f"{resolved.day_id}: automation identifier {automation_id!r} is "
                "missing or used twice"
            )
        seen.add(automation_id)
        allow = day_allows or bool(automation.get("allow_past_rollover"))
        when = fix(automation.get("time"), allow)

        if simcha and automation_id == NIGHT:
            night_time = (settings.get("simcha") or {}).get("night_time")
            if night_time is None:
                raise ScheduleError("Simcha mode is on but the schedule has no simcha time")
            # Simcha mode only ever makes Night later.
            when = max(when, fix(night_time, allow))

        automations.append(
            ScheduledAutomation(
                automation_id,
                automation.get("name", automation_id),
                when,
                automation.get("fade_seconds", 0),
                automation.get("rooms", {}),
            )
        )

    set_up = {a.get("id"): a for a in schedule.get("alongside", ())}
    for applies in alongside_for(day, source, settings.get("selichos", {})):
        automation = set_up.get(applies.id)
        if automation is None:
            continue  # the house has not set this one up
        if applies.time_key is None:
            spec = automation.get("time")
        else:
            spec = (automation.get("times") or {}).get(applies.time_key)
        automations.append(
            ScheduledAutomation(
                applies.id,
                automation.get("name", applies.id),
                fix(spec, bool(automation.get("allow_past_rollover"))),
                automation.get("fade_seconds", 0),
                automation.get("rooms", {}),
                alongside=True,
            )
        )

    automations.sort(key=lambda a: a.time)
    return DayList(day, resolved, shabbos_start, tuple(automations))
