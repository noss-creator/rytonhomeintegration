"""A sensor for the next automation and its time.

It is for showing on a dashboard. Nothing in the engine reads it: every
automation runs from the day's fixed list.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .calendar import describe
from .const import DOMAIN
from .scheduler import Scheduler


class NextAutomationSensor(SensorEntity):
    """The name of the next automation, with its time."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "Ryton next automation"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, scheduler: Scheduler, entry: ConfigEntry) -> None:
        self._scheduler = scheduler
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_next_automation"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._scheduler.async_listen_lists(self._lists_changed))

    @callback
    def _lists_changed(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        found = self._scheduler.next_automation()
        return found[1].name if found else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        found = self._scheduler.next_automation()
        if found is None:
            return {}
        day_list, automation = found
        return {
            "time": automation.time.isoformat(timespec="seconds"),
            "automation": automation.id,
            "day": day_list.day.day_id,
            "date": day_list.date.isoformat(),
            "changes": describe(self.hass, self._scheduler, day_list, automation),
        }


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    scheduler: Scheduler = entry.runtime_data
    async_add_entities([NextAutomationSensor(scheduler, entry)])
