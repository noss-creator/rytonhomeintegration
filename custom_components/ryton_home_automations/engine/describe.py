"""Says in words what an automation changes, for the calendar and the client's view."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from typing import Any

from .scenes import describe_action, expand_scenes


def describe_rooms(
    rooms: Mapping[str, Any],
    scenes: Mapping[str, Mapping[str, Any]],
    room_name: Callable[[str], str],
    entity_name: Callable[[str], str],
    rooms_off: Collection[str] = (),
) -> list[str]:
    """Return a line for each room an automation changes.

    ``scenes`` holds the schedule's own scenes: a room that uses one is shown
    by what the scene sets. A room that uses a scene made in Home Assistant
    is shown by the scene's name. Rooms whose scheduling is off, and rooms
    in which nothing is set, are left out.
    """
    return [
        f"{room_name(room)}: {words}"
        for room, words in describe_by_room(rooms, scenes, entity_name, rooms_off)
    ]


def describe_by_room(
    rooms: Mapping[str, Any],
    scenes: Mapping[str, Mapping[str, Any]],
    entity_name: Callable[[str], str],
    rooms_off: Collection[str] = (),
) -> list[tuple[str, str]]:
    """Return what an automation changes as (room, words), one for each room."""
    found: list[tuple[str, str]] = []
    for room, body in expand_scenes(rooms, scenes).items():
        if room in rooms_off or not isinstance(body, Mapping):
            continue
        parts: list[str] = []
        scene = body.get("scene")
        if isinstance(scene, str):
            parts.append(f"scene {entity_name(scene)}")
        for entity_id, action in (body.get("entities") or {}).items():
            if isinstance(action, Mapping):
                parts.append(f"{entity_name(entity_id)} {describe_action(action).lower()}")
        if parts:
            found.append((room, ", ".join(parts)))
    return found


_DAY_ENDINGS = (
    ("__friday", " on Friday"),
    ("__shabbos", " on Shabbos"),
)
_DAY_NUMBERS = (("_1", ", first day"), ("_2", ", second day"))


def day_name(day_id: str) -> str:
    """A day's identifier in words, as "Succos, first day on Shabbos"."""
    ending = ""
    for suffix, words in _DAY_ENDINGS:
        if day_id.endswith(suffix):
            day_id, ending = day_id[: -len(suffix)], words
    number = ""
    for suffix, words in _DAY_NUMBERS:
        if day_id.endswith(suffix):
            day_id, number = day_id[: -len(suffix)], words
    words = day_id.replace("_", " ").strip()
    return f"{words[:1].upper()}{words[1:]}{number}{ending}"


def automation_title(automation_id: str, name: str | None) -> str:
    """An automation's name, or its identifier in words where it has none."""
    if name and name != automation_id:
        return name
    words = automation_id.replace("_", " ").strip()
    return f"{words[:1].upper()}{words[1:]}"
