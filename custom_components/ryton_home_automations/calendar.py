"""The house's schedule as a Home Assistant calendar.

Each automation is an event at its time, saying what it changes. The dates
are worked out by the engine from the house's stored schedule, with the
client's temporary changes laid on top, so the calendar needs no internet.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .engine.day_list import DayList, ScheduledAutomation
from .engine.describe import describe_rooms
from .engine.scenes import schedule_scenes
from .engine.time_resolver import ScheduleError
from .scheduler import Scheduler

# An event needs an end after its start. An automation is a moment.
EVENT_LENGTH = timedelta(minutes=1)
# The longest span of dates worked out for one request.
MAX_DAYS = 100


def describe(hass: HomeAssistant, scheduler: Scheduler, day_list: DayList, automation: ScheduledAutomation) -> str:
    """What an automation changes, a line for each room."""
    areas = ar.async_get(hass)

    def room_name(room: str) -> str:
        area = areas.async_get_area(room)
        return area.name if area else room

    def entity_name(entity_id: str) -> str:
        state = hass.states.get(entity_id)
        return state.name if state else entity_id

    try:
        scenes = schedule_scenes(scheduler.schedule)
    except ScheduleError:
        scenes = {}
    return "\n".join(
        describe_rooms(automation.rooms, scenes, room_name, entity_name, day_list.rooms_off)
    )


def as_event(hass: HomeAssistant, scheduler: Scheduler, day_list: DayList, automation: ScheduledAutomation) -> CalendarEvent:
    return CalendarEvent(
        start=automation.time,
        end=automation.time + EVENT_LENGTH,
        summary=automation.name,
        description=describe(hass, scheduler, day_list, automation),
        uid=f"{day_list.date.isoformat()}|{automation.key}",
    )


class RytonCalendar(CalendarEntity):
    """The schedule, one event for each automation."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_name = "Ryton schedule"

    def __init__(self, scheduler: Scheduler, entry: ConfigEntry) -> None:
        self._scheduler = scheduler
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_schedule"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._scheduler.async_listen_lists(self._lists_changed))

    @callback
    def _lists_changed(self) -> None:
        self.async_write_ha_state()

    @property
    def event(self) -> CalendarEvent | None:
        """The next automation to run."""
        found = self._scheduler.next_automation()
        if found is None:
            return None
        return as_event(self.hass, self._scheduler, *found)

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        first: date = start_date.date() - timedelta(days=1)  # a Night may run after midnight
        last: date = min(end_date.date(), first + timedelta(days=MAX_DAYS))
        events: list[CalendarEvent] = []
        for day_list in await self._scheduler.async_day_lists(first, last):
            for automation in day_list.automations:
                if start_date <= automation.time < end_date:
                    events.append(as_event(hass, self._scheduler, day_list, automation))
        events.sort(key=lambda event: event.start)
        return events


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    scheduler: Scheduler = entry.runtime_data
    async_add_entities([RytonCalendar(scheduler, entry)])


__all__: list[Any] = ["RytonCalendar", "async_setup_entry"]
