"""The decisions of the sync with the website, with no network and no Home Assistant.

The house only ever fetches a schedule. Whatever arrives is checked here
before it is allowed to replace the one the house is running.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from .day_list import check_schedule
from .time_resolver import ScheduleError

# The kinds of entity a schedule can set.
SCHEDULABLE_DOMAINS = (
    "light", "switch", "cover", "select", "input_select", "input_boolean", "fan",
    "scene",
)


def accept_schedule(
    fetched: Any, house_id: str, have_revision: int | None
) -> dict[str, Any]:
    """Return ``fetched`` if the house may run it, or raise ScheduleError.

    It must be a schedule in a format the engine knows, belong to this
    house, and be newer than the one the house has.
    """
    if not isinstance(fetched, Mapping):
        raise ScheduleError("The website did not send a schedule")
    check_schedule(fetched)
    if str(fetched.get("house_id")) != str(house_id):
        raise ScheduleError("The schedule belongs to another house")
    revision = fetched.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ScheduleError("The schedule has no revision number")
    if have_revision is not None and revision <= have_revision:
        raise ScheduleError(
            f"The schedule (revision {revision}) is not newer than the house's "
            f"(revision {have_revision})"
        )
    return dict(fetched)


def fingerprint(value: Any) -> str:
    """A short, stable mark of a value, to tell whether it changed."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_inventory(
    floors: Iterable[Mapping[str, Any]],
    areas: Iterable[Mapping[str, Any]],
    entities: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Arrange the house's floors, rooms and schedulable entities for the website.

    ``floors`` have ``id``, ``name`` and ``level``. ``areas`` have ``id``,
    ``name`` and ``floor_id``. ``entities`` have ``entity_id``, ``name``,
    ``area_id`` and whatever the entity supports (``options``, ``dimmable``,
    ``position``). Entities of other kinds are left out. Everything is sorted,
    so the same house always gives the same result.
    """
    by_room: dict[str | None, list[dict[str, Any]]] = {}
    for entity in entities:
        entity_id = entity["entity_id"]
        if entity_id.split(".", 1)[0] not in SCHEDULABLE_DOMAINS:
            continue
        record = {"entity_id": entity_id, "name": entity.get("name") or entity_id}
        for key in ("options", "dimmable", "position"):
            if entity.get(key):
                record[key] = entity[key]
        by_room.setdefault(entity.get("area_id"), []).append(record)

    def room(area: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": area["id"],
            "name": area.get("name") or area["id"],
            "entities": sorted(by_room.get(area["id"], []), key=lambda e: e["entity_id"]),
        }

    known_areas = list(areas)
    known_floor_ids = set()
    result_floors = []
    for floor in sorted(floors, key=lambda f: (f.get("level") is None, f.get("level") or 0, f["id"])):
        known_floor_ids.add(floor["id"])
        result_floors.append(
            {
                "id": floor["id"],
                "name": floor.get("name") or floor["id"],
                "level": floor.get("level"),
                "rooms": sorted(
                    (room(a) for a in known_areas if a.get("floor_id") == floor["id"]),
                    key=lambda r: r["id"],
                ),
            }
        )

    known_area_ids = {a["id"] for a in known_areas}
    return {
        "floors": result_floors,
        "rooms_with_no_floor": sorted(
            (room(a) for a in known_areas if a.get("floor_id") not in known_floor_ids),
            key=lambda r: r["id"],
        ),
        # A schedulable entity with no room. The form shows these under "Whole house".
        "entities_with_no_room": sorted(
            (
                e
                for area_id, found in by_room.items()
                if area_id not in known_area_ids
                for e in found
            ),
            key=lambda e: e["entity_id"],
        ),
    }
