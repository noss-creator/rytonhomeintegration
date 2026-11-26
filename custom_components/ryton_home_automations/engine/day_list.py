"""Builds a date's fixed list: each automation, its time, and its rooms.

This puts the pieces together for one date: the day it resolves to, Shabbos
start, each automation's clock time, simcha mode, and the running-alongside
automations. It can run for any date, which is how the year preview and the
upcoming schedule are produced.

The client's temporary changes and room switches are laid on top here, when
they are passed in. A change that cannot be applied is skipped and noted; it
never stops the schedule itself from running.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .alongside import alongside_for
from .changes import ROOM, SHABBOS, SIMCHA, TIME, active_changes, rooms_off_for
from .calendar_source import CalendarSource
from .day_resolver import ResolvedDay, resolve_day
from .scenes import expand_scenes, schedule_scenes
from .day_tables import CHOL_HAMOED, table_for
from .time_resolver import (
    PastRolloverError,
    ScheduleError,
    ZmanUnavailableError,
    _clock,
    check_rollover,
    resolve_shabbos_start,
    resolve_time,
    runs_on,
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
    # The rooms that automations skip on this date: each room's own switch,
    # with the client's timed changes to it.
    rooms_off: frozenset[str] = frozenset()
    # The client's changes that could not be applied on this date, each as
    # its identifier and the reason.
    skipped_changes: tuple[tuple[str, str], ...] = ()


# What can go wrong applying one of the client's changes. The change is then
# skipped and the schedule's own value kept.
_CHANGE_FAILS = (ScheduleError, PastRolloverError, ZmanUnavailableError)


def _with_room_change(
    rooms: Mapping[str, Any],
    change: Mapping[str, Any],
    scenes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return ``rooms`` with one room change of the client's laid on top.

    An entity given a setting is set to it, and added where the room did not
    list it. An entity given as None is left as is. Where the room uses a
    scene made in the form, the scene's entities are changed. Where it uses
    a scene made in Home Assistant the scene still runs, then the entities;
    such a scene's own entities cannot be left as is.
    """
    room = change["room"]
    changed = dict(rooms)
    body = expand_scenes({room: rooms[room]}, scenes)[room] if room in rooms else {}
    body = dict(body) if isinstance(body, Mapping) else {}
    entities = dict(body.get("entities") or {})
    for entity_id, action in change["entities"].items():
        entities.pop(entity_id, None)
        if action is not None:
            entities[entity_id] = action
    body["entities"] = entities
    changed[room] = body
    return changed


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
        day,
        source,
        table,
        lambda day_id: bool(_day_entry(schedule, day_id).get("enabled")),
        lambda day_id: isinstance(schedule["days"].get(day_id), Mapping),
    )


def build_day_list(
    schedule: Mapping[str, Any],
    day: date,
    source: CalendarSource,
    tz: tzinfo,
    *,
    one_week: Mapping[str, Any] | None = None,
    simcha: bool = False,
    changes: Iterable[Any] = (),
    rooms_off: Collection[str] = (),
) -> DayList:
    """Return the fixed list for ``day``.

    ``one_week`` is a one-week Shabbos switch for this week, and ``simcha``
    says whether simcha mode is on for this date. ``changes`` holds the
    client's temporary changes and ``rooms_off`` the rooms whose own switch
    is off; both are stored in the house. The changes that apply to this
    date are laid on top of the schedule. Where two touch the same thing,
    the one made later wins.
    """
    check_schedule(schedule)
    settings = schedule["settings"]
    rollover = settings.get("day_rollover", "04:00")

    table = table_for(settings.get("yom_tov_days"), settings.get("purim"))
    resolved = resolve_schedule_day(schedule, day, source)
    entry = _day_entry(schedule, resolved.day_id)

    active = active_changes(changes, day, resolved.day_id)
    skipped: list[tuple[str, str]] = []
    used: set[str] = set()
    week_changes = [change for change in active if change["kind"] == SHABBOS]
    simcha_changes = [change for change in active if change["kind"] == SIMCHA]
    time_changes = [change for change in active if change["kind"] == TIME]
    room_changes = [change for change in active if change["kind"] == ROOM]
    day_start = datetime.combine(day, _clock(rollover), tz)

    rules = settings.get("early_shabbos_rules", ())
    if resolved.occasion in table.yom_tov:
        # There is no early Shabbos on a Friday that is itself Yom Tov:
        # neither the rules nor the client's one-week switch apply.
        rules = ()
        one_week = None
        week_changes = []
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
    shabbos_start = None
    # The client's latest Shabbos change for this date, where it can be used.
    for change in reversed(week_changes):
        asked = (
            {"kind": "late"}
            if change["week"] == "late"
            else {"kind": "early", "start": change["start"]}
        )
        try:
            shabbos_start = resolve_shabbos_start(day, source, tz, rules, one_week=asked)
        except _CHANGE_FAILS as error:
            skipped.append((change["id"], str(error)))
            continue
        break
    else:
        shabbos_start = resolve_shabbos_start(day, source, tz, rules, one_week=one_week)

    def changed_time(automation_id: str, when: datetime, allow: bool) -> datetime:
        """The automation's time after the client's latest usable time change."""
        for change in reversed(time_changes):
            if change["automation"] != automation_id:
                continue
            used.add(change["id"])
            try:
                if "time" in change:
                    asked = fix(change["time"], allow)
                else:
                    asked = when + timedelta(minutes=change["shift_minutes"])
                    check_rollover(asked, day, tz, rollover, allow)
                if asked < day_start:
                    raise ScheduleError("The time is before this day begins")
            except _CHANGE_FAILS as error:
                skipped.append((change["id"], str(error) or type(error).__name__))
                continue
            return asked
        return when

    def changed_rooms(automation_id: str, rooms: Mapping[str, Any]) -> Mapping[str, Any]:
        """The automation's rooms with the client's room changes laid on top."""
        for change in room_changes:
            if change["automation"] != automation_id:
                continue
            used.add(change["id"])
            try:
                rooms = _with_room_change(rooms, change, schedule_scenes(schedule))
            except _CHANGE_FAILS as error:
                skipped.append((change["id"], str(error)))
        return rooms

    def runs(spec: Any) -> bool:
        """Whether the automation runs on this date. A date range can say no."""
        return not isinstance(spec, Mapping) or runs_on(spec, day, source, tz)

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
        if not runs(automation.get("time")):
            continue
        allow = day_allows or bool(automation.get("allow_past_rollover"))
        when = changed_time(automation_id, fix(automation.get("time"), allow), allow)

        if automation_id == NIGHT and (simcha or simcha_changes):
            night_time = (settings.get("simcha") or {}).get("night_time")
            if simcha:
                if night_time is None:
                    raise ScheduleError("Simcha mode is on but the schedule has no simcha time")
                # Simcha mode only ever makes Night later.
                when = max(when, fix(night_time, allow))
            else:
                # Asked for by the client: where it cannot be done, Night
                # keeps its time.
                try:
                    if night_time is None:
                        raise ScheduleError("The schedule has no simcha time")
                    when = max(when, fix(night_time, allow))
                    used.update(change["id"] for change in simcha_changes)
                except _CHANGE_FAILS as error:
                    skipped.extend((change["id"], str(error)) for change in simcha_changes)
                    used.update(change["id"] for change in simcha_changes)

        automations.append(
            ScheduledAutomation(
                automation_id,
                automation.get("name", automation_id),
                when,
                automation.get("fade_seconds", 0),
                changed_rooms(automation_id, automation.get("rooms", {})),
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
        if not runs(spec):
            continue
        allow = bool(automation.get("allow_past_rollover"))
        automations.append(
            ScheduledAutomation(
                applies.id,
                automation.get("name", applies.id),
                changed_time(applies.id, fix(spec, allow), allow),
                automation.get("fade_seconds", 0),
                changed_rooms(applies.id, automation.get("rooms", {})),
                alongside=True,
            )
        )

    # A change that names an automation this date does not have is skipped.
    for change in (*time_changes, *room_changes, *simcha_changes):
        if change["id"] not in used:
            skipped.append((change["id"], "This day has no such automation"))

    automations.sort(key=lambda a: a.time)
    return DayList(
        day,
        resolved,
        shabbos_start,
        tuple(automations),
        rooms_off_for(active, rooms_off),
        tuple(skipped),
    )
