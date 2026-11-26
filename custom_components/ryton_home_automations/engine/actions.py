"""Turns one automation's rooms into the ordered steps that carry it out.

Scenes go first, one at a time. Entities follow in groups, with a pause
between groups. The numbers are the house's pacing settings. Each call also
says what the entity should look like afterwards, so the result can be
checked and the misses retried.

Nothing here talks to Home Assistant. It only decides what to ask for.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from .time_resolver import ScheduleError

# Domains that are not simply switched on and off.
_COVER = "cover"
_SELECTS = ("select", "input_select")
_SCENE = "scene"

# How far a reported brightness or position may be from the one asked for.
_BRIGHTNESS_TOLERANCE = 3  # out of 255
_POSITION_TOLERANCE = 2  # percent


@dataclass(frozen=True)
class Expected:
    """What an entity should report once a call has taken effect."""

    states: tuple[str, ...] = ()
    attribute: str | None = None
    value: float | None = None
    tolerance: float = 0

    def is_met(self, state: str | None, attributes: Mapping[str, Any]) -> bool:
        if self.states and state not in self.states:
            return False
        if self.attribute is not None:
            reported = attributes.get(self.attribute)
            if not isinstance(reported, (int, float)) or isinstance(reported, bool):
                return False
            if abs(reported - self.value) > self.tolerance:
                return False
        return True


@dataclass(frozen=True)
class Call:
    """One service call. ``expected`` is None where the result cannot be checked."""

    room: str
    entity_id: str
    domain: str
    service: str
    data: Mapping[str, Any] = field(default_factory=dict)
    expected: Expected | None = None


@dataclass(frozen=True)
class Step:
    """Calls made together, followed by a pause before the next step."""

    calls: tuple[Call, ...]
    pause_seconds: float


# The warning blink, in seconds: on, off, three times, then a break, and
# the same again. Afterwards each entity goes back to how it was.
_BLINK_ON = 0.2
_BLINK_OFF = 0.05
_BLINK_BREAK = 0.5
_BLINK_TIMES = 3
_BLINK_ROUNDS = 2
# Added to each of them in a house whose lights cannot keep up.
_BLINK_SLOWER_BY = 0.2


def is_blink(entity_id: str, action: Any) -> bool:
    """Whether an action is the warning blink. Raise where it is not understood."""
    if not isinstance(action, Mapping) or "blink" not in action:
        return False
    if set(action) != {"blink"} or action["blink"] is not True:
        raise ScheduleError(f"{entity_id}: the blink is not understood")
    if entity_id.split(".", 1)[0] in (_COVER, _SCENE, *_SELECTS):
        raise ScheduleError(f"{entity_id}: only something switched on and off can blink")
    return True


def blink_pattern(slow: bool = False) -> list[tuple[str, float]]:
    """The blink as steps: "on" or "off", and how long to wait after it."""
    extra = _BLINK_SLOWER_BY if slow else 0
    steps: list[tuple[str, float]] = []
    for _round in range(_BLINK_ROUNDS):
        for number in range(_BLINK_TIMES):
            steps.append(("on", _BLINK_ON + extra))
            last = number == _BLINK_TIMES - 1
            steps.append(("off", (_BLINK_BREAK if last else _BLINK_OFF) + extra))
    # Nothing is waited for after the last one: the entities are put back.
    steps[-1] = ("off", 0)
    return steps


def blink_entities(rooms: Mapping[str, Any], rooms_off: Collection[str] = ()) -> list[str]:
    """The entities an automation blinks, leaving out rooms switched off."""
    found: list[str] = []
    for room, body in rooms.items():
        if room in rooms_off or not isinstance(body, Mapping):
            continue
        entities = body.get("entities")
        if not isinstance(entities, Mapping):
            continue
        found += [
            entity_id
            for entity_id, action in entities.items()
            if is_blink(entity_id, action) and entity_id not in found
        ]
    return found


@dataclass(frozen=True)
class Cycle:
    """An entity switched on and off in turn, from an automation's time to an end.

    The end is either ``for_minutes`` after the start or the clock time
    ``until``. At the end the entity is switched off.
    """

    on_minutes: int
    off_minutes: int
    for_minutes: int | None = None
    until: time | None = None


# The longest a cycle can run.
MAX_CYCLE_MINUTES = 24 * 60

_CYCLE_KEYS = (
    {"on_minutes", "off_minutes", "for_minutes"},
    {"on_minutes", "off_minutes", "until"},
)


def _whole_minutes(entity_id: str, value: Any, what: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_CYCLE_MINUTES
    ):
        raise ScheduleError(
            f"{entity_id}: a cycle's {what} is a whole number of minutes, "
            f"1 to {MAX_CYCLE_MINUTES}"
        )
    return value


def cycle_of(entity_id: str, action: Any) -> Cycle | None:
    """Return the cycle an action asks for, or None where it asks for none."""
    if not isinstance(action, Mapping) or "cycle" not in action:
        return None
    spec = action["cycle"]
    if set(action) != {"cycle"} or not isinstance(spec, Mapping):
        raise ScheduleError(f"{entity_id}: the cycle is not understood")
    if entity_id.split(".", 1)[0] in (_COVER, _SCENE, *_SELECTS):
        raise ScheduleError(f"{entity_id}: only something switched on and off can cycle")
    if set(spec) not in _CYCLE_KEYS:
        raise ScheduleError(
            f"{entity_id}: a cycle has on_minutes, off_minutes and either "
            "for_minutes or until"
        )
    on = _whole_minutes(entity_id, spec["on_minutes"], "time on")
    off = _whole_minutes(entity_id, spec["off_minutes"], "time off")
    if "for_minutes" in spec:
        length = _whole_minutes(entity_id, spec["for_minutes"], "length")
        return Cycle(on, off, for_minutes=length)
    try:
        until = time.fromisoformat(spec["until"])
    except (TypeError, ValueError):
        raise ScheduleError(f"{entity_id}: a cycle's end is not a clock time") from None
    return Cycle(on, off, until=until)


def cycle_moments(cycle: Cycle, start: datetime) -> list[tuple[datetime, str]]:
    """Every moment after ``start`` at which a cycle switches, with "on" or "off".

    The entity is switched on at ``start`` by the automation itself. The
    last moment is the end, and is always "off". An end at a clock time that
    is not after the start is that time on the next day.
    """
    if cycle.for_minutes is not None:
        end = start + timedelta(minutes=cycle.for_minutes)
    else:
        end = datetime.combine(start.date(), cycle.until, start.tzinfo)
        if end <= start:
            end = datetime.combine(
                start.date() + timedelta(days=1), cycle.until, start.tzinfo
            )
    moments: list[tuple[datetime, str]] = []
    at = start
    while True:
        at += timedelta(minutes=cycle.on_minutes)
        if at >= end:
            break
        moments.append((at, "off"))
        at += timedelta(minutes=cycle.off_minutes)
        if at >= end:
            break
        moments.append((at, "on"))
    moments.append((end, "off"))
    return moments


def _entity_call(
    room: str, entity_id: str, action: Any, automation_fade: float
) -> Call:
    if not isinstance(action, Mapping):
        raise ScheduleError(f"{entity_id}: the action is not understood")
    domain = entity_id.split(".", 1)[0]
    if cycle_of(entity_id, action) is not None:
        # The automation starts the cycle by switching the entity on. The
        # day's list holds every later moment of it.
        return Call(room, entity_id, domain, "turn_on", {}, Expected(("on",)))
    keys = set(action) - {"fade_seconds"}
    fade = action.get("fade_seconds", automation_fade)

    if keys == {"option"}:
        if domain not in _SELECTS:
            raise ScheduleError(f"{entity_id}: only a mode list has options")
        option = action["option"]
        return Call(
            room, entity_id, domain, "select_option", {"option": option},
            Expected(states=(option,)),
        )

    if keys == {"position"}:
        if domain != _COVER:
            raise ScheduleError(f"{entity_id}: only a shade has a position")
        position = action["position"]
        if isinstance(position, bool) or not isinstance(position, (int, float)):
            raise ScheduleError(f"{entity_id}: the position is not a number")
        if not 0 <= position <= 100:
            raise ScheduleError(f"{entity_id}: the position is not 0 to 100")
        return Call(
            room, entity_id, domain, "set_cover_position", {"position": position},
            Expected(
                attribute="current_position", value=position,
                tolerance=_POSITION_TOLERANCE,
            ),
        )

    state = action.get("state")

    if domain == _COVER:
        if keys != {"state"} or state not in ("open", "closed"):
            raise ScheduleError(f"{entity_id}: a shade is open, closed or a position")
        if state == "open":
            return Call(room, entity_id, domain, "open_cover", {}, Expected(("open",)))
        return Call(room, entity_id, domain, "close_cover", {}, Expected(("closed",)))

    if domain in _SELECTS or domain == _SCENE:
        raise ScheduleError(f"{entity_id}: the action does not fit this kind of entity")

    if state == "off" and keys == {"state"}:
        data = {"transition": fade} if domain == "light" and fade else {}
        return Call(room, entity_id, domain, "turn_off", data, Expected(("off",)))

    if state == "on" and keys <= {"state", "brightness_pct"}:
        data: dict[str, Any] = {}
        expected = Expected(("on",))
        if "brightness_pct" in action:
            if domain != "light":
                raise ScheduleError(f"{entity_id}: only a light has a brightness")
            pct = action["brightness_pct"]
            if isinstance(pct, bool) or not isinstance(pct, (int, float)):
                raise ScheduleError(f"{entity_id}: the brightness is not a number")
            if not 1 <= pct <= 100:
                raise ScheduleError(f"{entity_id}: the brightness is not 1 to 100")
            data["brightness_pct"] = pct
            expected = Expected(
                ("on",), "brightness", round(pct * 255 / 100), _BRIGHTNESS_TOLERANCE
            )
        if domain == "light" and fade:
            data["transition"] = fade
        return Call(room, entity_id, domain, "turn_on", data, expected)

    raise ScheduleError(f"{entity_id}: the action is not understood")


def room_fade(room: str, body: Mapping[str, Any], otherwise: float) -> float:
    """The fade of one room: its own if it has one, or the automation's."""
    if "fade_seconds" not in body:
        return otherwise
    fade = body["fade_seconds"]
    if isinstance(fade, bool) or not isinstance(fade, (int, float)) or fade < 0:
        raise ScheduleError(f"{room}: the fade is not a number of seconds")
    return fade


def latest_state(missed: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Combine automations that were missed into the state the house should be in now.

    ``missed`` holds the ``rooms`` of each missed automation, in time order.
    Nothing in between is replayed: each room is brought straight to where
    it should be.

    A scene is a snapshot of its whole room. So for each room the result is
    the latest scene that was set there, if any, followed by the entities
    set after that scene, each in the last state asked for. Entities set
    before the scene are dropped, since the scene replaced them.

    The result has the shape of an automation's ``rooms``, except that a
    room may hold both a scene and entities. Pass it to ``plan_steps`` with
    ``merged=True``.
    """
    combined: dict[str, dict[str, Any]] = {}
    for rooms in missed:
        for room, body in rooms.items():
            if not isinstance(body, Mapping):
                raise ScheduleError(f"{room}: the room is not understood")
            if "scene" in body:
                combined[room] = {"scene": body["scene"], "entities": {}}
            # A room may hold a scene with entities set after it, where the
            # client changed a room that uses a scene.
            now = combined.setdefault(room, {"entities": {}})
            for entity_id, action in (body.get("entities") or {}).items():
                if is_blink(entity_id, action):
                    # A blink leaves the entity as it was.
                    continue
                # Moved to the end, so entities run in the order they
                # were last set.
                now["entities"].pop(entity_id, None)
                now["entities"][entity_id] = action
    return {
        room: {key: value for key, value in body.items() if value}
        for room, body in combined.items()
        if body.get("scene") or body["entities"]
    }


def plan_steps(
    rooms: Mapping[str, Any],
    *,
    fade_seconds: float = 0,
    group_size: int = 5,
    pause_seconds: float = 1,
    rooms_off: Collection[str] = (),
    merged: bool = False,
) -> list[Step]:
    """Return the steps that carry out one automation.

    ``rooms`` is the automation's ``rooms`` from the schedule. ``rooms_off``
    holds the rooms whose scheduling is switched off; they are skipped.

    ``merged`` is for the result of ``latest_state``, where a room may hold
    a scene and entities together. The scene runs first, then the entities.
    """
    if isinstance(group_size, bool) or not isinstance(group_size, int) or group_size < 1:
        raise ScheduleError(f"The group size must be 1 or more, not {group_size!r}")

    scenes: list[Call] = []
    entities: list[Call] = []
    for room, body in rooms.items():
        if room in rooms_off:
            continue
        if not isinstance(body, Mapping):
            raise ScheduleError(f"{room}: the room is not understood")
        has_scene, has_entities = "scene" in body, "entities" in body
        if not (has_scene or has_entities) or (has_scene and has_entities and not merged):
            raise ScheduleError(f"{room}: a room holds either entities or a scene")
        if has_scene:
            scene = body["scene"]
            if not isinstance(scene, str) or not scene.startswith("scene."):
                raise ScheduleError(f"{room}: {scene!r} is not a scene")
            # A scene fades only by the room's own fade.
            own = room_fade(room, body, 0)
            scenes.append(
                Call(room, scene, _SCENE, "turn_on", {"transition": own} if own else {})
            )
        if has_entities:
            fade = room_fade(room, body, fade_seconds)
            for entity_id, action in body["entities"].items():
                if is_blink(entity_id, action):
                    # Blinked by the scheduler, apart from these steps.
                    continue
                entities.append(_entity_call(room, entity_id, action, fade))

    steps = [Step((scene,), pause_seconds) for scene in scenes]
    for start in range(0, len(entities), group_size):
        steps.append(Step(tuple(entities[start : start + group_size]), pause_seconds))
    return steps
