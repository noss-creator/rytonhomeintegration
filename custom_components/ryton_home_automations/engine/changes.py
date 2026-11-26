"""The client's temporary changes: what one may hold, and which apply to a date.

The changes are kept in the house, apart from the schedule, and are never
sent to the website. The format is in ``TEMPORARY_CHANGES_FORMAT.md``.

This module checks a change and picks the ones that apply to a date.
``day_list.build_day_list`` lays them on top of the schedule. A change that
cannot be applied is skipped; it never stops the day's schedule from running.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from .time_resolver import ScheduleError

FORMAT_VERSION = 1

TIME = "time"
ROOM = "room"
ROOM_SWITCH = "room_switch"
SHABBOS = "shabbos"
SIMCHA = "simcha"
AWAY = "away"
MEAL_OUT = "meal_out"
KINDS = (TIME, ROOM, ROOM_SWITCH, SHABBOS, SIMCHA, AWAY, MEAL_OUT)

_MEALS = ("night", "day", "shalosh_seudos", "first_seuda", "seuda_hamafsekes", "seuda")

ALL_DAYS = "all"

Change = Mapping[str, Any]


class ChangeError(ScheduleError):
    """A temporary change is not in a form the engine understands."""


def _date(change: Change, key: str) -> date:
    value = change.get(key)
    if not isinstance(value, str):
        raise ChangeError(f"A temporary change has no {key!r} date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ChangeError(f"{value!r} is not a date") from None


def _text(change: Change, key: str) -> str:
    value = change.get(key)
    if not isinstance(value, str) or not value:
        raise ChangeError(f"A temporary change has no {key!r}")
    return value


def made_at(change: Change) -> datetime:
    """When the change was made. The later of two changes wins."""
    try:
        return datetime.fromisoformat(_text(change, "made_at"))
    except ValueError:
        raise ChangeError(f"{change.get('made_at')!r} is not a date and time") from None


def check_change(change: Any) -> None:
    """Refuse a temporary change the engine does not understand."""
    if not isinstance(change, Mapping):
        raise ChangeError("A temporary change is not understood")
    _text(change, "id")
    made_at(change)
    if _date(change, "until") < _date(change, "from"):
        raise ChangeError("A temporary change ends before it starts")

    days = change.get("days")
    if days != ALL_DAYS and not (
        isinstance(days, Sequence)
        and not isinstance(days, str)
        and days
        and all(isinstance(day_id, str) and day_id for day_id in days)
    ):
        raise ChangeError('A temporary change needs "days": "all" or a list of days')

    kind = change.get("kind")
    if kind == TIME:
        _text(change, "automation")
        has_time, has_shift = "time" in change, "shift_minutes" in change
        if has_time == has_shift:
            raise ChangeError("A time change holds either a time or a shift")
        if has_time:
            spec = change["time"]
            if not isinstance(spec, Mapping) or spec.get("kind") != "clock":
                raise ChangeError("A time change's time is a clock time")
        else:
            shift = change["shift_minutes"]
            if isinstance(shift, bool) or not isinstance(shift, int) or shift == 0:
                raise ChangeError("A shift is a whole number of minutes, not 0")
    elif kind == ROOM:
        _text(change, "automation")
        _text(change, "room")
        if "scene" in change:
            raise ChangeError("A temporary change cannot set a scene")
        entities = change.get("entities")
        if not isinstance(entities, Mapping) or not entities:
            raise ChangeError("A room change sets at least one entity")
        for entity_id, action in entities.items():
            if not isinstance(entity_id, str) or "." not in entity_id:
                raise ChangeError(f"{entity_id!r} is not an entity")
            if entity_id.startswith("scene."):
                raise ChangeError("A temporary change cannot set a scene")
            if action is not None and not (isinstance(action, Mapping) and action):
                raise ChangeError(f"{entity_id}: the setting is not understood")
    elif kind == ROOM_SWITCH:
        _text(change, "room")
        if change.get("scheduling") not in ("off", "on"):
            raise ChangeError('A room switch change says "scheduling": "off" or "on"')
    elif kind == SHABBOS:
        week = change.get("week")
        if week == "early":
            if not isinstance(change.get("start"), Mapping):
                raise ChangeError("An early Shabbos change needs its start time")
        elif week != "late":
            raise ChangeError('A Shabbos change says "week": "early" or "late"')
    elif kind == AWAY:
        _text(change, "run")
        moments = []
        for key in ("starts_at", "ends_at"):
            try:
                moments.append(datetime.fromisoformat(_text(change, key)))
            except ValueError:
                raise ChangeError(f"{change.get(key)!r} is not a date and time") from None
            if moments[-1].tzinfo is None:
                raise ChangeError(f"An away change's {key} has no timezone")
        if moments[1] < moments[0]:
            raise ChangeError("Away mode ends before it starts")
        if change["run"] == "rooms":
            rooms = change.get("rooms")
            if (
                not isinstance(rooms, Sequence)
                or isinstance(rooms, str)
                or not all(isinstance(room, str) and room for room in rooms)
            ):
                raise ChangeError("Away mode by rooms needs its list of rooms")
    elif kind == MEAL_OUT:
        if change.get("meal") not in _MEALS:
            raise ChangeError("Away for a meal names a meal the house knows")
        if change["from"] != change["until"]:
            raise ChangeError("Away for a meal is for one date")
    elif kind != SIMCHA:
        raise ChangeError(f"Unknown kind of temporary change: {kind!r}")


def check_store(store: Any) -> None:
    """Refuse stored temporary changes the engine does not understand."""
    if not isinstance(store, Mapping):
        raise ChangeError("The temporary changes are not understood")
    version = store.get("format_version")
    if version != FORMAT_VERSION:
        raise ChangeError(f"Temporary changes format version {version!r} is not understood")
    rooms_off = store.get("rooms_off", ())
    if isinstance(rooms_off, str) or not all(isinstance(room, str) for room in rooms_off):
        raise ChangeError("The rooms switched off are not understood")
    room_night = store.get("room_night", {})
    if not isinstance(room_night, Mapping) or not all(
        isinstance(room, str) and isinstance(how, Mapping) for room, how in room_night.items()
    ):
        raise ChangeError("The rooms with their own Night are not understood")
    seen: set[str] = set()
    for change in store.get("changes", ()):
        check_change(change)
        if change["id"] in seen:
            raise ChangeError(f"Two temporary changes share the identifier {change['id']!r}")
        seen.add(change["id"])


def covers(change: Change, day: date) -> bool:
    """Whether ``day`` is within the change's dates, both included."""
    return _date(change, "from") <= day <= _date(change, "until")


def active_changes(changes: Iterable[Any], day: date, day_id: str) -> list[Change]:
    """Return the changes that apply to ``day``, the earliest made first.

    ``day_id`` is the day of the schedule that the engine resolved the date
    to. A change that is not understood is left out.
    """
    found: list[Change] = []
    for change in changes:
        try:
            check_change(change)
        except ChangeError:
            continue
        if not covers(change, day):
            continue
        days = change["days"]
        if days != ALL_DAYS and day_id not in days:
            continue
        found.append(change)
    found.sort(key=made_at)
    return found


def still_wanted(changes: Iterable[Any], today: date) -> list[Any]:
    """Return the changes to keep: every one that has not run out by ``today``.

    A change is dropped the day after its last date. One that cannot be read
    is dropped too.
    """
    kept = []
    for change in changes:
        try:
            if _date(change, "until") >= today:
                kept.append(change)
        except (ChangeError, AttributeError):
            continue
    return kept


def rooms_off_for(
    active: Sequence[Change], rooms_off: Collection[str] = ()
) -> frozenset[str]:
    """Return the rooms that automations skip on a date.

    ``rooms_off`` holds the rooms whose plain switch is off. A timed change
    then switches a room off, or back on, for its dates; the later one wins.
    """
    off = set(rooms_off)
    for change in active:
        if change["kind"] != ROOM_SWITCH:
            continue
        if change["scheduling"] == "off":
            off.add(change["room"])
        else:
            off.discard(change["room"])
    return frozenset(off)


def dates_between(first: date, last: date) -> list[date]:
    """Every date from ``first`` to ``last``, both included."""
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]
