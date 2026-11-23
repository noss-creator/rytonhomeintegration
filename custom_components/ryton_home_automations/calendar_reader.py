"""Reads Home Assistant's Jewish Calendar integration for a span of dates.

This is the only place the house asks Home Assistant for the calendar. It
makes one local service call and hands the events to the engine's parser.
No network is involved.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant

from .engine.calendar_snapshot import CalendarDataError, CalendarSnapshot, parse_events

DAILY_EVENTS = "calendar.jewish_calendar_daily_events"
YEARLY_EVENTS = "calendar.jewish_calendar_yearly_events"


async def async_read_calendar(
    hass: HomeAssistant,
    first: date,
    last: date,
    daily_entity: str = DAILY_EVENTS,
    yearly_entity: str = YEARLY_EVENTS,
) -> CalendarSnapshot:
    """Return the Jewish Calendar for ``first`` to ``last``."""
    tz = ZoneInfo(hass.config.time_zone)
    # An all-day event is left out when the span asked for ends on the
    # midnight after it, so ask for one day more than needed.
    start = datetime.combine(first, time.min, tz)
    end = datetime.combine(last + timedelta(days=2), time.min, tz)

    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": [daily_entity, yearly_entity],
            "start_date_time": start.isoformat(),
            "end_date_time": end.isoformat(),
        },
        blocking=True,
        return_response=True,
    )

    events = {}
    for entity_id in (daily_entity, yearly_entity):
        found = (response or {}).get(entity_id)
        if found is None:
            raise CalendarDataError(f"Home Assistant has no calendar {entity_id}")
        events[entity_id] = found.get("events", [])

    return parse_events(events[daily_entity], events[yearly_entity], tz, first, last)
