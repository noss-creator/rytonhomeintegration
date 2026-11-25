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
    lines: list[str] = []
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
            lines.append(f"{room_name(room)}: {', '.join(parts)}")
    return lines
