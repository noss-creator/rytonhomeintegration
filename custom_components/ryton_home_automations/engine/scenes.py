"""The schedule's own scenes.

A schedule can hold scenes made in the setup form: a name, a room, and the
state of every entity in that room. The house offers each one in Home
Assistant as a scene, and a room in an automation can use one like any other
scene.

When the engine runs a room that uses one of these, it does not ask Home
Assistant to turn a scene on. It sets the scene's entities itself, so the
usual pacing, check and retry apply to each of them.

Nothing here talks to Home Assistant.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .actions import _entity_call
from .time_resolver import ScheduleError

# Every one of these scenes is named this way in Home Assistant, so it can
# never collide with a scene the client made.
_SCENE_ID = re.compile(r"^ryton_[a-z0-9_]{1,80}$")


def entity_id_of(scene_id: str) -> str:
    """The Home Assistant entity of a schedule scene."""
    return f"scene.{scene_id}"


def schedule_scenes(schedule: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Return the schedule's own scenes by identifier, or raise ScheduleError.

    Each has a ``name`` (shown to people, with no prefix), a ``room`` and
    ``entities``: the same actions a room in an automation holds.
    """
    listed = (schedule or {}).get("scenes", [])
    if not isinstance(listed, list):
        raise ScheduleError("The schedule's scenes are not a list")

    scenes: dict[str, dict[str, Any]] = {}
    for scene in listed:
        if not isinstance(scene, Mapping):
            raise ScheduleError("A scene in the schedule is not understood")
        scene_id = scene.get("id")
        if not isinstance(scene_id, str) or not _SCENE_ID.match(scene_id):
            raise ScheduleError(f"{scene_id!r} is not a scene identifier")
        if scene_id in scenes:
            raise ScheduleError(f"The scene {scene_id} is in the schedule twice")
        name = scene.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ScheduleError(f"The scene {scene_id} has no name")
        room = scene.get("room")
        if not isinstance(room, str) or not room:
            raise ScheduleError(f"The scene {scene_id} has no room")
        entities = scene.get("entities")
        if not isinstance(entities, Mapping) or not entities:
            raise ScheduleError(f"The scene {scene_id} sets nothing")
        for entity_id, action in entities.items():
            # Raises if the action does not fit the entity.
            _entity_call(room, entity_id, action, 0)
        scenes[scene_id] = {
            "id": scene_id,
            "name": name.strip(),
            "room": room,
            "entities": dict(entities),
        }
    return scenes


def expand_scenes(
    rooms: Mapping[str, Any], scenes: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Replace each room's use of a schedule scene by that scene's entities.

    A room that uses any other scene is left as it is. Where a room holds a
    scene and entities together, as after a restart, the entities were set
    after the scene and so they win.
    """
    by_entity = {entity_id_of(scene_id): scene for scene_id, scene in scenes.items()}
    expanded: dict[str, Any] = {}
    for room, body in rooms.items():
        scene = body.get("scene") if isinstance(body, Mapping) else None
        if not isinstance(scene, str) or scene not in by_entity:
            expanded[room] = body
            continue
        entities = dict(by_entity[scene]["entities"])
        for entity_id, action in (body.get("entities") or {}).items():
            entities.pop(entity_id, None)
            entities[entity_id] = action
        expanded[room] = {"entities": entities}
    return expanded
