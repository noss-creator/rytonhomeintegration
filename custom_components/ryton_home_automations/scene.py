"""The schedule's own scenes, offered in Home Assistant.

Each scene made in the setup form becomes a scene here, under its plain name
and placed in its room. They are rebuilt from the house's stored copy of the
schedule at every start, so they need no internet.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .engine.scenes import describe_action, entity_id_of, schedule_scenes
from .engine.time_resolver import ScheduleError
from .scheduler import Scheduler

_LOGGER = logging.getLogger(__name__)


def _unique_id(scene_id: str) -> str:
    return f"{DOMAIN}_{scene_id}"


class RytonScene(Scene):
    """One scene from the schedule."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, scheduler: Scheduler, scene: dict[str, Any]) -> None:
        self._scheduler = scheduler
        self._scene_id: str = scene["id"]
        self._room: str = scene["room"]
        self._entities: dict[str, Any] = scene["entities"]
        self._fade: float = scene["fade_seconds"]
        self._attr_name = scene["name"]
        self._attr_unique_id = _unique_id(self._scene_id)
        # The identifier carries the prefix; the name people see does not.
        self.entity_id = entity_id_of(self._scene_id)

    def update_from(self, scene: dict[str, Any]) -> None:
        """Take the scene's new name and contents after the schedule changed."""
        self._room = scene["room"]
        now = (scene["name"], scene["entities"], scene["fade_seconds"])
        if now != (self._attr_name, self._entities, self._fade):
            self._attr_name, self._entities, self._fade = now
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """What the scene does: each entity by name with what it is set to."""
        shown: dict[str, Any] = {}
        for entity_id, action in self._entities.items():
            state = self.hass.states.get(entity_id) if self.hass else None
            name = state.name if state else entity_id
            if name in shown or name in ("entity_id", "fade_seconds", "friendly_name"):
                name = entity_id
            shown[name] = describe_action(action)
        if self._fade:
            shown["fade_seconds"] = self._fade
        # As Home Assistant's own scenes do: the entities the scene sets.
        shown["entity_id"] = list(self._entities)
        return shown

    async def async_added_to_hass(self) -> None:
        """Place the scene in its room, unless someone already moved it."""
        entry = self.registry_entry
        if entry is None or entry.area_id is not None:
            return
        if ar.async_get(self.hass).async_get_area(self._room) is None:
            return
        er.async_get(self.hass).async_update_entity(self.entity_id, area_id=self._room)

    async def async_activate(self, **kwargs: Any) -> None:
        """Set the scene's entities, with the usual pacing, check and retry."""
        # Not waited for: the check and retry take a while, and whoever turned
        # the scene on should not be kept waiting for them.
        self.hass.async_create_task(
            self._scheduler.async_run_scene(self._scene_id, kwargs.get("transition"))
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    scheduler: Scheduler = entry.runtime_data
    registry = er.async_get(hass)
    current: dict[str, RytonScene] = {}

    async def refresh() -> None:
        """Make the scenes in Home Assistant match the schedule's."""
        try:
            wanted = schedule_scenes(scheduler.schedule)
        except ScheduleError as err:
            _LOGGER.warning("The schedule's scenes were not understood: %s", err)
            return

        # Scenes that are no longer in the schedule go, including any left
        # in the registry from before.
        keep = {_unique_id(scene_id) for scene_id in wanted}
        for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
            if registered.domain == "scene" and registered.unique_id not in keep:
                registry.async_remove(registered.entity_id)
        for scene_id in [scene_id for scene_id in current if scene_id not in wanted]:
            del current[scene_id]

        new: list[RytonScene] = []
        for scene_id, scene in wanted.items():
            if scene_id in current:
                current[scene_id].update_from(scene)
            else:
                current[scene_id] = RytonScene(scheduler, scene)
                new.append(current[scene_id])
        if new:
            async_add_entities(new)

    await refresh()
    entry.async_on_unload(scheduler.async_listen(refresh))
