"""Away mode: which schedule runs at a moment, and the meals of a date.

A house can be away in three ways. ``off``: nothing runs. A preset: a full
second schedule runs in place of the regular one. ``rooms``: only the rooms
named keep running, on the regular schedule.

It is switched on either by the schedule's own yearly dates (``away_dates``)
or by the client, as a temporary change of kind ``away`` kept in the house.
The client's choice wins. The formats are in ``SCHEDULE_FORMAT.md`` and
``TEMPORARY_CHANGES_FORMAT.md``.

Nothing here talks to Home Assistant.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .calendar_source import CalendarSource
from .changes import AWAY, ChangeError, check_change, made_at
from .day_resolver import resolve_day
from .day_tables import SAT, table_for
from .time_resolver import ScheduleError, ZmanUnavailableError, _clock, _in_date_range

OFF = "off"
ROOMS = "rooms"
_PRESET_ID = re.compile(r"^[a-z0-9_]{1,60}$")

NIGHT_MEAL = "night"
DAY_MEAL = "day"
SHALOSH_SEUDOS = "shalosh_seudos"
MEALS = (NIGHT_MEAL, DAY_MEAL, SHALOSH_SEUDOS)

YOM_KIPPUR = "yom_kippur"
# "Until motzei Shabbos" ends this long after havdalah.
AFTER_HAVDALAH = timedelta(hours=1)
# How far ahead the coming Shabbos or Yom Tov is looked for.
_LOOK_AHEAD_DAYS = 8

_TICK = timedelta(microseconds=1)


@dataclass(frozen=True)
class Mode:
    """How the house is away: ``off``, ``rooms`` or a preset's identifier."""

    run: str
    # With ``rooms``: the rooms that keep running.
    rooms: frozenset[str] = frozenset()


def schedule_presets(schedule: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    """Return the schedule's presets by identifier, or raise ScheduleError."""
    listed = (schedule or {}).get("presets", [])
    if not isinstance(listed, list):
        raise ScheduleError("The schedule's presets are not a list")
    presets: dict[str, Mapping[str, Any]] = {}
    for preset in listed:
        if not isinstance(preset, Mapping):
            raise ScheduleError("A preset in the schedule is not understood")
        preset_id = preset.get("id")
        if (
            not isinstance(preset_id, str)
            or not _PRESET_ID.match(preset_id)
            or preset_id in (OFF, ROOMS)
        ):
            raise ScheduleError(f"{preset_id!r} is not a preset identifier")
        if preset_id in presets:
            raise ScheduleError(f"The preset {preset_id} is in the schedule twice")
        if not isinstance(preset.get("days", {}), Mapping):
            raise ScheduleError(f"The preset {preset_id} has days that are not understood")
        if not isinstance(preset.get("alongside", []), list):
            raise ScheduleError(f"The preset {preset_id} has alongside automations that are not understood")
        presets[preset_id] = preset
    return presets


def check_away_dates(schedule: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the schedule's yearly away dates, or raise ScheduleError."""
    listed = schedule.get("away_dates", [])
    if not isinstance(listed, list):
        raise ScheduleError("The schedule's away dates are not a list")
    presets = schedule_presets(schedule)
    for entry in listed:
        if not isinstance(entry, Mapping):
            raise ScheduleError("An away date range is not understood")
        # Raises if the range is not two month-day dates.
        _in_date_range(date(2000, 1, 1), entry.get("from"), entry.get("to"))
        run = entry.get("run")
        if run != OFF and run not in presets:
            raise ScheduleError(f"An away date range runs {run!r}, which is not a preset")
    return listed


def preset_schedule(schedule: Mapping[str, Any], preset_id: str) -> dict[str, Any]:
    """The schedule a preset stands for: its own days, the house's settings and scenes."""
    preset = schedule_presets(schedule)[preset_id]
    variant = {
        key: value
        for key, value in schedule.items()
        if key not in ("presets", "away_dates", "days", "alongside")
    }
    variant["days"] = preset.get("days") or {}
    variant["alongside"] = preset.get("alongside") or []
    return variant


def rollover_at(day: date, schedule: Mapping[str, Any], tz: tzinfo) -> datetime:
    """The moment the schedule's ``day`` begins."""
    clock = (schedule.get("settings") or {}).get("day_rollover", "04:00")
    return datetime.combine(day, _clock(clock), tz)


def schedule_date(moment: datetime, schedule: Mapping[str, Any], tz: tzinfo) -> date:
    """The schedule's date a moment belongs to: the day runs until the rollover."""
    local = moment.astimezone(tz)
    day = local.date()
    return day if local >= rollover_at(day, schedule, tz) else day - timedelta(days=1)


def _moment(change: Mapping[str, Any], key: str) -> datetime:
    return datetime.fromisoformat(change[key])


def away_changes(schedule: Mapping[str, Any], changes: Iterable[Any]) -> list[Mapping[str, Any]]:
    """The client's away changes that can be used, the earliest made first."""
    try:
        presets = schedule_presets(schedule)
    except ScheduleError:
        presets = {}
    found = []
    for change in changes:
        try:
            check_change(change)
        except ChangeError:
            continue
        if change["kind"] != AWAY:
            continue
        if change["run"] not in (OFF, ROOMS) and change["run"] not in presets:
            continue  # a preset the schedule no longer has
        found.append(change)
    found.sort(key=made_at)
    return found


def has_away(schedule: Mapping[str, Any], changes: Iterable[Any]) -> bool:
    """Whether anything at all can put this house in away mode."""
    if schedule.get("away_dates"):
        return True
    return any(isinstance(change, Mapping) and change.get("kind") == AWAY for change in changes)


def mode_at(
    schedule: Mapping[str, Any],
    changes: Iterable[Any],
    moment: datetime,
    tz: tzinfo,
) -> Mode | None:
    """How the house is away at ``moment``, or None while the regular schedule runs.

    ``changes`` is the result of ``away_changes``. The latest one made that
    covers the moment decides it. Otherwise the schedule's yearly dates do.
    """
    for change in reversed(list(changes)):
        if _moment(change, "starts_at") <= moment < _moment(change, "ends_at"):
            if change["run"] == ROOMS:
                return Mode(ROOMS, frozenset(change["rooms"]))
            return Mode(change["run"])
    day = schedule_date(moment, schedule, tz)
    for entry in schedule.get("away_dates") or ():
        if _in_date_range(day, entry.get("from"), entry.get("to")):
            return Mode(entry["run"])
    return None


def switch_moments(
    schedule: Mapping[str, Any],
    changes: Iterable[Any],
    day: date,
    tz: tzinfo,
) -> list[tuple[datetime, Mode | None]]:
    """Each moment of the schedule's ``day`` at which away mode starts, ends or changes.

    With each is the mode from that moment on. ``changes`` is the result of
    ``away_changes``.
    """
    changes = list(changes)
    start = rollover_at(day, schedule, tz)
    end = rollover_at(day + timedelta(days=1), schedule, tz)
    candidates = {start}
    for change in changes:
        for key in ("starts_at", "ends_at"):
            moment = _moment(change, key)
            if start <= moment < end:
                candidates.add(moment)
    found = []
    for moment in sorted(candidates):
        after = mode_at(schedule, changes, moment, tz)
        if after != mode_at(schedule, changes, moment - _TICK, tz):
            found.append((moment, after))
    return found


# --- Shabbos, Yom Tov and their meals ------------------------------------------


def _occasion(schedule: Mapping[str, Any], day: date, source: CalendarSource) -> str | None:
    settings = schedule["settings"]
    table = table_for(settings.get("yom_tov_days"), settings.get("purim"))
    return resolve_day(day, source, table, lambda _day_id: True).occasion


def _is_yom_tov(schedule: Mapping[str, Any], day: date, source: CalendarSource) -> bool:
    """Whether ``day`` is Yom Tov or Yom Kippur."""
    settings = schedule["settings"]
    table = table_for(settings.get("yom_tov_days"), settings.get("purim"))
    return _occasion(schedule, day, source) in table.yom_tov


def is_holy(schedule: Mapping[str, Any], day: date, source: CalendarSource) -> bool:
    """Whether ``day`` is Shabbos, Yom Tov or Yom Kippur."""
    return day.weekday() == SAT or _is_yom_tov(schedule, day, source)


def meals_on(schedule: Mapping[str, Any], day: date, source: CalendarSource) -> list[tuple[str, str]]:
    """The meals that belong to the schedule's ``day``, each with its name.

    The night meal of a Shabbos or Yom Tov belongs to the day before, whose
    list runs through that night. Yom Kippur has no meals.
    """
    tomorrow = day + timedelta(days=1)
    found: list[tuple[str, str]] = []

    def name(of: date, meal: str) -> str:
        if of.weekday() != SAT:
            return f"Yom Tov {meal}"
        return f"Shabbos {meal}"

    if is_holy(schedule, tomorrow, source) and _occasion(schedule, tomorrow, source) != YOM_KIPPUR:
        found.append((NIGHT_MEAL, name(tomorrow, "night")))
    if _occasion(schedule, day, source) != YOM_KIPPUR:
        if is_holy(schedule, day, source):
            found.append((DAY_MEAL, name(day, "day")))
        if day.weekday() == SAT:
            found.append((SHALOSH_SEUDOS, "Shalosh seudos"))
    return found


def motzei_end(
    schedule: Mapping[str, Any], today: date, source: CalendarSource
) -> tuple[date, datetime]:
    """When "until motzei Shabbos or Yom Tov" ends, counted from the schedule's ``today``.

    It is an hour after havdalah on the last day of the coming unbroken run
    of Shabbos and Yom Tov. Havdalah is read from the calendar for that
    date. Returns that last day with the moment.
    """
    first = next(
        (
            today + timedelta(days=n)
            for n in range(_LOOK_AHEAD_DAYS)
            if is_holy(schedule, today + timedelta(days=n), source)
        ),
        None,
    )
    if first is None:
        raise ScheduleError("No Shabbos or Yom Tov was found in the coming week")
    last = first
    while is_holy(schedule, last + timedelta(days=1), source):
        last += timedelta(days=1)
    havdalah = source.zman(last, "havdalah")
    if havdalah is None:
        raise ZmanUnavailableError(f"{last}: no havdalah on this date")
    return last, havdalah + AFTER_HAVDALAH
