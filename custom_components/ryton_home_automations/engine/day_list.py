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
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .actions import cycle_moments, cycle_of, latest_state
from .away import (
    OFF,
    ROOMS,
    Mode,
    away_changes,
    check_away_dates,
    has_away,
    mode_at,
    preset_schedule,
    rollover_at,
    switch_moments,
)
from .alongside import alongside_for
from .changes import (
    DAY_PARTY,
    MEAL_OUT,
    ROOM,
    SHABBOS,
    SIMCHA,
    TIME,
    active_changes,
    rooms_off_for,
)
from .calendar_snapshot import CalendarDataError
from .calendar_source import CalendarSource
from .day_resolver import ResolvedDay, UnresolvedDayError, resolve_day
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
    # For one moment of a cycle: the automation that started the cycle.
    part_of: str | None = None
    # Its rooms may hold a scene and entities together, and nothing fades:
    # it brings rooms straight to a state, as when away mode starts or ends.
    merged: bool = False
    # The away preset it belongs to, where it is not the regular schedule's.
    preset: str | None = None

    @property
    def key(self) -> str:
        """What tells it from every other moment of its date.

        A preset's automation may share its identifier with one of the
        regular schedule's, and both can be in one date's list when away
        mode starts or ends during the day.
        """
        return f"{self.preset}:{self.id}" if self.preset else self.id


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
    # Every later moment of the cycles the automations start, each switching
    # one entity on or off. They run like automations but are not shown.
    cycle_steps: tuple[ScheduledAutomation, ...] = ()
    # The moments at which away mode starts, ends or changes, each bringing
    # the rooms to where they should then be. They run but are not shown.
    switches: tuple[ScheduledAutomation, ...] = ()
    # When Night would run with no simcha: what a room's own Night is counted from.
    night_usual: datetime | None = None
    # The rooms the schedule gives a Night time of their own, each with that
    # time: what the client's child or adult night mode is counted from.
    night_rooms: Mapping[str, datetime] = field(default_factory=dict)

    @property
    def moments(self) -> tuple[ScheduledAutomation, ...]:
        """Everything that runs on this date, in time order."""
        if not self.cycle_steps and not self.switches:
            return self.automations
        # A switch comes first where it shares its moment with an automation.
        return tuple(
            sorted(
                (*self.switches, *self.automations, *self.cycle_steps),
                key=lambda a: a.time,
            )
        )


def _cycle_steps(automation: ScheduledAutomation) -> list[ScheduledAutomation]:
    """The later moments of every cycle an automation starts."""
    steps: list[ScheduledAutomation] = []
    for room, body in automation.rooms.items():
        entities = body.get("entities") if isinstance(body, Mapping) else None
        if not isinstance(entities, Mapping):
            continue
        for entity_id, action in entities.items():
            cycle = cycle_of(entity_id, action)
            if cycle is None:
                continue
            for number, (when, state) in enumerate(cycle_moments(cycle, automation.time), 1):
                steps.append(
                    ScheduledAutomation(
                        f"{automation.id}#{entity_id}#{number}",
                        f"{automation.name} (cycle)",
                        when,
                        0,
                        {room: {"entities": {entity_id: {"state": state}}}},
                        automation.alongside,
                        automation.id,
                    )
                )
    return steps


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
    check_away_dates(schedule)


def _day_entry(
    schedule: Mapping[str, Any], day_id: str, lenient: bool = False
) -> Mapping[str, Any]:
    entry = schedule["days"].get(day_id)
    if not isinstance(entry, Mapping):
        if lenient:
            # A preset does not have this day: it runs nothing.
            return {}
        raise ScheduleError(f"The schedule has no day {day_id!r}")
    return entry


def resolve_schedule_day(
    schedule: Mapping[str, Any],
    day: date,
    source: CalendarSource,
    lenient: bool = False,
) -> Any:
    """Return which of the schedule's days ``day`` is. No times are worked out.

    ``lenient`` is for a preset, which may lack days: a combination day it
    does not have counts as switched off.
    """
    settings = schedule["settings"]
    table = table_for(settings.get("yom_tov_days"), settings.get("purim"))
    return resolve_day(
        day,
        source,
        table,
        lambda day_id: bool(_day_entry(schedule, day_id, lenient).get("enabled")),
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
    house_rooms: Mapping[str, Collection[str]] | None = None,
    away: bool = True,
    room_night: Mapping[str, Any] | None = None,
) -> DayList:
    """Return the fixed list for ``day``, with away mode taken into account.

    While the house is away, the automations of the regular schedule are
    left out and, where a preset runs, the preset's are put in their place.
    Each moment at which away mode starts, ends or changes is added as a
    switch that brings the rooms to where they should then be.

    ``house_rooms`` holds, for each room of the house, the entities that are
    switched on and off. It is what "everything off" switches off. ``away``
    false gives the regular schedule whatever the away dates say.
    """
    changes = list(changes)
    regular = _base_list(
        schedule, day, source, tz,
        one_week=one_week, simcha=simcha, changes=changes, rooms_off=rooms_off,
        room_night=room_night,
    )
    if not away or not has_away(schedule, changes):
        return regular

    client = away_changes(schedule, changes)

    def mode(moment: datetime) -> Mode | None:
        return mode_at(schedule, client, moment, tz)

    bases: dict[tuple[str | None, date], DayList | None] = {(None, day): regular}

    def base(preset_id: str | None, of: date) -> DayList | None:
        """The whole list of the regular schedule or a preset for a date, if it can be fixed."""
        key = (preset_id, of)
        if key not in bases:
            try:
                if preset_id is None:
                    bases[key] = _base_list(
                        schedule, of, source, tz, changes=changes, rooms_off=rooms_off,
                        room_night=room_night,
                    )
                else:
                    bases[key] = _base_list(
                        preset_schedule(schedule, preset_id), of, source, tz,
                        one_week=one_week if of == day else None,
                        simcha=simcha and of == day,
                        changes=changes, rooms_off=rooms_off, lenient=True,
                        room_night=room_night,
                    )
            except _LIST_FAILS:
                bases[key] = None
        return bases[key]

    def kept(automation: ScheduledAutomation, of: Mode | None) -> ScheduledAutomation | None:
        """The automation as it runs in the mode at its own time, or None."""
        now = mode(automation.time)
        if now is None or now.run != ROOMS:
            return automation if now == of else None
        if of is not None:
            return None  # only the regular schedule runs in the rooms that stay on
        rooms = {room: body for room, body in automation.rooms.items() if room in now.rooms}
        return replace(automation, rooms=rooms)

    def of_preset(automation: ScheduledAutomation, preset_id: str) -> ScheduledAutomation | None:
        found = kept(automation, Mode(preset_id))
        return None if found is None else replace(found, preset=preset_id)

    switches = switch_moments(schedule, client, day, tz)
    preset_ids = {
        found.run
        for found in (mode(rollover_at(day, schedule, tz)), *(after for _, after in switches))
        if found is not None and found.run not in (OFF, ROOMS)
    }

    automations = [a for a in (kept(a, None) for a in regular.automations) if a is not None]
    for preset_id in sorted(preset_ids):
        listed = base(preset_id, day)
        if listed is not None:
            automations += [
                a for a in (of_preset(a, preset_id) for a in listed.automations) if a is not None
            ]
    automations.sort(key=lambda a: a.time)

    cycle_steps = []
    for automation in automations:
        running = mode(automation.time)
        cycle_steps += [
            replace(step, preset=automation.preset)
            for step in _cycle_steps(automation)
            if mode(step.time) == running
        ]

    def state_at(preset_id: str | None, moment: datetime) -> dict[str, Any]:
        """Where a schedule has each room at a moment, from this date and the one before."""
        lists = [base(preset_id, of) for of in (day - timedelta(days=1), day)]
        ran = [
            item
            for listed in lists
            if listed is not None
            for item in listed.moments
            if item.time <= moment
        ]
        ran.sort(key=lambda a: a.time)
        try:
            return latest_state([item.rooms for item in ran])
        except ScheduleError:
            return {}

    def everything_off(but: Collection[str] = ()) -> dict[str, Any]:
        return {
            room: {"entities": {entity_id: {"state": "off"} for entity_id in entities}}
            for room, entities in (house_rooms or {}).items()
            if room not in but and entities
        }

    made = []
    for moment, after in switches:
        if after is None:
            name, rooms = "Away mode ends", state_at(None, moment)
        elif after.run == OFF:
            name, rooms = "Away mode starts", everything_off()
        elif after.run == ROOMS:
            staying = state_at(None, moment)
            rooms = {
                **everything_off(but=after.rooms),
                **{room: body for room, body in staying.items() if room in after.rooms},
            }
            name = "Away mode starts"
        else:
            name, rooms = "Away mode starts", state_at(after.run, moment)
        if rooms:
            made.append(
                ScheduledAutomation(
                    f"away#{moment.isoformat()}", name, moment, 0, rooms,
                    part_of="away", merged=True,
                )
            )

    return replace(
        regular,
        automations=tuple(automations),
        cycle_steps=tuple(sorted(cycle_steps, key=lambda a: a.time)),
        switches=tuple(made),
    )


# What can stop a date's list from being fixed.
_LIST_FAILS = (
    ScheduleError,
    PastRolloverError,
    ZmanUnavailableError,
    UnresolvedDayError,
    CalendarDataError,
)


def _base_list(
    schedule: Mapping[str, Any],
    day: date,
    source: CalendarSource,
    tz: tzinfo,
    *,
    one_week: Mapping[str, Any] | None = None,
    simcha: bool = False,
    changes: Iterable[Any] = (),
    rooms_off: Collection[str] = (),
    lenient: bool = False,
    room_night: Mapping[str, Any] | None = None,
) -> DayList:
    """Return the fixed list of one schedule for ``day``, away mode aside.

    ``lenient`` is for a preset: a day it does not have runs nothing.

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
    resolved = resolve_schedule_day(schedule, day, source, lenient)
    entry = _day_entry(schedule, resolved.day_id, lenient)

    active = active_changes(changes, day, resolved.day_id)
    # The meals the family is out for on this date.
    meals_out = [change["meal"] for change in active if change["kind"] == MEAL_OUT]
    skipped: list[tuple[str, str]] = []
    used: set[str] = set()
    week_changes = [change for change in active if change["kind"] == SHABBOS]
    simcha_changes = [change for change in active if change["kind"] == SIMCHA]
    party_changes = [change for change in active if change["kind"] == DAY_PARTY]
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

    def out_for_meal(automation: Mapping[str, Any]) -> Mapping[str, Any]:
        """The automation's rooms, with those set differently when out for a meal."""
        rooms = automation.get("rooms", {})
        when_out = automation.get("when_out")
        if not meals_out or not isinstance(when_out, Mapping):
            return rooms
        for meal in meals_out:
            if isinstance(when_out.get(meal), Mapping):
                rooms = {**rooms, **when_out[meal]}
        return rooms

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
    night_usual: datetime | None = None
    room_times: Any = None
    night_rooms: dict[str, datetime] = {}
    simcha_at: datetime | None = None
    simcha_rooms: set[str] = set()
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

        if automation_id == NIGHT:
            night_usual = when
            room_times = automation.get("room_times")
        if automation_id == NIGHT and (simcha or simcha_changes):
            simcha_set = settings.get("simcha") or {}
            night_time = simcha_set.get("night_time")
            # The time the client entered when turning it on; the latest one made wins.
            asked = next(
                (c["at"] for c in reversed(simcha_changes) if isinstance(c.get("at"), str)), None
            )

            def simcha_when() -> datetime:
                if asked is not None:
                    late = _clock_on(day, asked, day_start, tz)
                    check_rollover(late, day, tz, rollover, allow)
                    return late
                if night_time is None:
                    raise ScheduleError("The schedule has no simcha time")
                return fix(night_time, allow)

            late: datetime | None = None
            if simcha:
                if night_time is None:
                    raise ScheduleError("Simcha mode is on but the schedule has no simcha time")
                late = fix(night_time, allow)
            else:
                # Asked for by the client: where it cannot be done, Night
                # keeps its time.
                try:
                    late = simcha_when()
                except _CHANGE_FAILS as error:
                    skipped.extend((change["id"], str(error)) for change in simcha_changes)
                used.update(change["id"] for change in simcha_changes)
            if late is not None:
                # Only the simcha rooms the schedule names are late, and the
                # house's Night keeps its time. A schedule that names none,
                # as one made before simcha rooms, has no late rooms.
                rooms = simcha_set.get("rooms")
                simcha_at = late
                simcha_rooms = (
                    {room for room in rooms if isinstance(room, str)}
                    if isinstance(rooms, list)
                    else set()
                )

        automations.append(
            ScheduledAutomation(
                automation_id,
                automation.get("name", automation_id),
                when,
                automation.get("fade_seconds", 0),
                changed_rooms(automation_id, out_for_meal(automation)),
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
                changed_rooms(applies.id, out_for_meal(automation)),
                alongside=True,
            )
        )

    # A change that names an automation this date does not have is skipped.
    for change in (*time_changes, *room_changes, *simcha_changes):
        if change["id"] not in used:
            skipped.append((change["id"], "This day has no such automation"))

    if party_changes:
        # The latest one made gives the time.
        asked_party = party_changes[-1]["at"]
        party = (settings.get("day_party") or {}).get("rooms")
        try:
            party_at = _clock_on(day, asked_party, day_start, tz)
            check_rollover(party_at, day, tz, rollover, day_allows)
            if not any(a.id == AFTER_DAY_SEUDA and not a.alongside for a in automations):
                raise ScheduleError("This day has no such automation")
            automations = _with_party_rooms(
                automations, party_at,
                {room for room in party if isinstance(room, str)} if isinstance(party, list) else set(),
            )
        except _CHANGE_FAILS as error:
            skipped.extend((change["id"], str(error)) for change in party_changes)
    late_rooms: set[str] = set()
    if simcha_at is not None:
        automations, late_rooms = _with_simcha_rooms(automations, simcha_at, simcha_rooms)
    if night_usual is not None and (room_night or room_times):
        # Simcha wins: a room that is late for the simcha has no other time that night.
        automations, night_rooms = _with_room_nights(
            automations,
            {room: how for room, how in (room_night or {}).items() if room not in late_rooms},
            night_usual, day, day_start, tz,
            {
                room: how
                for room, how in (room_times if isinstance(room_times, Mapping) else {}).items()
                if room not in late_rooms
            },
        )
    automations.sort(key=lambda a: a.time)
    cycle_steps = [step for automation in automations for step in _cycle_steps(automation)]
    return DayList(
        day,
        resolved,
        shabbos_start,
        tuple(automations),
        rooms_off_for(active, rooms_off),
        tuple(skipped),
        tuple(sorted(cycle_steps, key=lambda a: a.time)),
        night_usual=night_usual,
        night_rooms=night_rooms,
    )


AFTER_DAY_SEUDA = "after_day_seuda"
PARTY_AFTER = "after_day_seuda#party"


def _with_party_rooms(
    automations: list[ScheduledAutomation], party_at: datetime, party_rooms: Collection[str]
) -> list[ScheduledAutomation]:
    """Move After day seuda in the day party rooms to the party time.

    The house's After day seuda keeps its time and leaves those rooms as
    they are. What it has for them runs at the party time. A room that
    another automation sets in between is not set again at the party
    time: that automation has already taken it further. A party time that
    is not later than After day seuda changes nothing.
    """
    after = next((a for a in automations if a.id == AFTER_DAY_SEUDA and not a.alongside), None)
    if after is None or party_at <= after.time:
        return automations
    held = {room: body for room, body in after.rooms.items() if room in party_rooms}
    if not held:
        return automations
    rest = {room: body for room, body in after.rooms.items() if room not in held}
    late = {
        room: body
        for room, body in held.items()
        if not any(
            room in a.rooms and after.time < a.time <= party_at for a in automations if a is not after
        )
    }
    automations = [replace(a, rooms=rest) if a is after else a for a in automations]
    if late:
        automations.append(
            ScheduledAutomation(
                PARTY_AFTER, "After day seuda, party rooms", party_at, after.fade_seconds, late,
                part_of=AFTER_DAY_SEUDA,
            )
        )
    return automations


SIMCHA_NIGHT = "night#simcha"


def _with_simcha_rooms(
    automations: list[ScheduledAutomation], simcha_at: datetime, simcha_rooms: Collection[str]
) -> tuple[list[ScheduledAutomation], set[str]]:
    """Move the Night of the simcha rooms to the simcha time. Also the rooms it moved.

    The house's Night keeps its time and leaves those rooms as they are.
    What Night has for them runs at the simcha time. A simcha time that
    is not later than Night changes nothing: simcha only makes Night later.
    """
    night = next((a for a in automations if a.id == NIGHT and not a.alongside), None)
    if night is None or simcha_at <= night.time:
        return automations, set()
    late = {room: body for room, body in night.rooms.items() if room in simcha_rooms}
    if not late:
        return automations, set()
    rest = {room: body for room, body in night.rooms.items() if room not in late}
    automations = [replace(a, rooms=rest) if a is night else a for a in automations]
    automations.append(
        ScheduledAutomation(
            SIMCHA_NIGHT, "Night, simcha rooms", simcha_at, night.fade_seconds, late, part_of=NIGHT,
        )
    )
    return automations, set(late)


ROOM_NIGHT = "night#own:"
ROOM_NIGHT_MODES = ("child", "adult")
_ROOM_NIGHT_WORDS = "A room's own Night is so many minutes from the house's Night, or a clock time"


def check_room_night(how: Any) -> None:
    """Refuse a room's own Night setting the engine does not understand.

    ``mode`` is "child", earlier than the house's Night, or "adult", later.
    With no mode it is a child's.
    """
    if not isinstance(how, Mapping) or not set(how) <= {"mode", "minutes", "at"}:
        raise ScheduleError(_ROOM_NIGHT_WORDS)
    if how.get("mode", "child") not in ROOM_NIGHT_MODES:
        raise ScheduleError("A room's own Night is a child's, earlier, or an adult's, later")
    if ("minutes" in how) == ("at" in how):
        raise ScheduleError(_ROOM_NIGHT_WORDS)
    if "minutes" in how:
        minutes = how["minutes"]
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 720:
            raise ScheduleError("A room's own Night is between 1 minute and 12 hours away")
    else:
        if not isinstance(how["at"], str):
            raise ScheduleError("A room's own Night clock time is not understood")
        try:
            _clock(how["at"])
        except ValueError:
            raise ScheduleError("A room's own Night clock time is not understood") from None


def check_room_time(how: Any) -> None:
    """Refuse a room's Night time in a schedule that the engine does not understand.

    It is ``{"minutes": n}``, so many minutes after the house's Night or,
    below zero, before it; or ``{"at": "HH:MM"}``, a clock time.
    """
    words = "A room's Night time is so many minutes before or after Night, or a clock time"
    if not isinstance(how, Mapping) or len(how) != 1:
        raise ScheduleError(words)
    if "minutes" in how:
        minutes = how["minutes"]
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= abs(minutes) <= 720:
            raise ScheduleError("A room's Night time is between 1 minute and 12 hours from Night")
    elif "at" in how and isinstance(how["at"], str):
        try:
            _clock(how["at"])
        except ValueError:
            raise ScheduleError("A room's Night clock time is not understood") from None
    else:
        raise ScheduleError(words)


def _clock_on(day: date, at: str, day_start: datetime, tz: tzinfo) -> datetime:
    """A clock time in the schedule's ``day``: one before the day's start is after midnight."""
    moment = datetime.combine(day, _clock(at), tz)
    return moment + timedelta(days=1) if moment < day_start else moment


def room_night_time(
    how: Any,
    night_usual: datetime,
    day: date,
    day_start: datetime,
    tz: tzinfo,
    night: datetime | None = None,
    room_time: Any = None,
) -> tuple[datetime | None, datetime | None]:
    """When a room has its own Night on ``day``, and the time the schedule gives the room.

    The first is None where the room runs with the house. The second is
    None where the schedule gives the room no time of its own.

    The schedule may give the room a time (``room_time``): so many minutes
    from the Night's usual time, or a clock time. The client's child or
    adult night mode (``how``) is counted from that time, or from the
    Night's usual time where the room has none; its clock time is that
    clock time whatever the schedule says.

    A time before the Night's usual time has to fall after the day's
    start. A later one has to fall after the Night as it runs that date
    (``night``, later than usual on a simcha night) and before the day
    starts over. A child's clock time has to be earlier than Night and an
    adult's later. A time that does not fit is dropped: the client's
    first, leaving the schedule's, and then the room runs with the house.
    """
    night_runs = max(night_usual, night or night_usual)
    day_end = datetime.combine(day + timedelta(days=1), day_start.timetz().replace(tzinfo=None), tz)

    def fits(moment: datetime) -> bool:
        return day_start < moment < night_usual or night_runs < moment < day_end

    base: datetime | None = None
    try:
        check_room_time(room_time)
    except ScheduleError:
        pass
    else:
        if "minutes" in room_time:
            base = night_usual + timedelta(minutes=room_time["minutes"])
        else:
            base = _clock_on(day, room_time["at"], day_start, tz)
        if not fits(base):
            base = None

    moment = base
    try:
        check_room_night(how)
    except ScheduleError:
        pass
    else:
        adult = how.get("mode") == "adult"
        if "minutes" in how:
            step = timedelta(minutes=how["minutes"])
            asked = (base or night_usual) + (step if adult else -step)
            if fits(asked):
                moment = asked
        else:
            asked = _clock_on(day, how["at"], day_start, tz)
            if fits(asked) and (asked > night_runs) == adult:
                moment = asked
    return moment, base


def _with_room_nights(
    automations: list[ScheduledAutomation],
    room_night: Mapping[str, Any],
    night_usual: datetime,
    day: date,
    day_start: datetime,
    tz: tzinfo,
    room_times: Mapping[str, Any] | None = None,
) -> tuple[list[ScheduledAutomation], dict[str, datetime]]:
    """Give each room that has one its own Night. Also the times the schedule gives rooms.

    The room's Night settings run at its own time, and the house's Night
    no longer runs in that room. Where its own Night is earlier: from then
    until the house's, automations skip the room, so it stays as its own
    Night left it. Where it is later: the house's Night leaves the room as
    it is, and its own Night runs afterwards.
    """
    room_times = room_times or {}
    bases: dict[str, datetime] = {}
    night = next((a for a in automations if a.id == NIGHT and not a.alongside), None)
    if night is None:
        return automations, bases
    for room in sorted({*room_night, *room_times}):
        how = room_night.get(room)
        body = night.rooms.get(room)
        if body is None:
            continue
        moment, base = room_night_time(
            how, night_usual, day, day_start, tz, night.time, room_times.get(room)
        )
        if base is not None:
            bases[room] = base
        if moment is None:
            continue
        later = moment > night.time
        automations = [
            replace(a, rooms={r: b for r, b in a.rooms.items() if r != room})
            if room in a.rooms and (a is night if later else moment <= a.time <= night.time)
            else a
            for a in automations
        ]
        night = next(a for a in automations if a.id == NIGHT and not a.alongside)
        if moment == base:
            name = "Night, the room's own time"
        else:
            name = "Night, adult's room" if how.get("mode") == "adult" else "Night, child's room"
        automations.append(
            ScheduledAutomation(
                f"{ROOM_NIGHT}{room}", name, moment, night.fade_seconds, {room: body}, part_of=NIGHT,
            )
        )
    return automations, bases
