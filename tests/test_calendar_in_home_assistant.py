"""The schedule as a calendar, and the next-automation sensor, in a real Home Assistant core.

Uses the pretend house of tests/test_time_travel.py: Morning at 07:00,
Sunset at 18:00 and Night at 23:00, each turning on one scene in the hall.

Needs Home Assistant's test tools, which do not load on Windows. On GitHub
these tests run on Linux.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from custom_components.ryton_home_automations.const import DOMAIN  # noqa: E402

from .test_time_travel import (  # noqa: E402, F401
    START,
    _enable_custom_integrations,
    _instant_waits,
    house,
    local,
)

CALENDAR = "calendar.ryton_schedule"
SENSOR = "sensor.ryton_next_automation"
TOMORROW = START + timedelta(days=1)


async def _events(house, first, last):
    entity = house.hass.data["calendar"].get_entity(CALENDAR)
    return await entity.async_get_events(house.hass, first, last)


async def test_the_sensor_names_the_next_automation_and_its_time(house):
    await house.reload_schedule()
    state = house.hass.states.get(SENSOR)
    assert state.state == "Morning"
    assert state.attributes["time"] == local(START, "07:00").isoformat(timespec="seconds")
    assert state.attributes["day"] == "weekday"
    assert state.attributes["changes"] == "hall: scene scene.weekday"

    await house.move_to(local(START, "07:00"))
    assert house.hass.states.get(SENSOR).state == "Sunset"


async def test_after_the_last_automation_the_sensor_shows_tomorrows_first(house):
    await house.reload_schedule()
    for clock in ("07:00", "18:00", "23:00"):
        await house.move_to(local(START, clock))
    state = house.hass.states.get(SENSOR)
    assert state.state == "Morning"
    assert state.attributes["date"] == TOMORROW.isoformat()
    assert state.attributes["time"] == local(TOMORROW, "07:00").isoformat(timespec="seconds")


async def test_the_sensor_is_unknown_with_no_schedule(house):
    assert house.hass.states.get(SENSOR).state == "unknown"


async def test_the_calendar_lists_a_dates_automations(house):
    await house.reload_schedule()
    events = await _events(house, local(START, "00:00"), local(TOMORROW, "00:00"))
    assert [(event.summary, event.start) for event in events] == [
        ("Morning", local(START, "07:00")),
        ("Sunset", local(START, "18:00")),
        ("Night", local(START, "23:00")),
    ]
    assert events[0].description == "hall: scene scene.weekday"
    assert events[0].end == local(START, "07:01")


async def test_the_calendar_covers_a_month_and_names_each_days_own_automations(house):
    await house.reload_schedule()
    events = await _events(
        house, local(START, "00:00"), local(START + timedelta(days=28), "00:00")
    )
    by_date = {}
    for event in events:
        by_date.setdefault(event.start.astimezone(local(START, "00:00").tzinfo).date(), []).append(
            event.summary
        )
    assert len(by_date) == 28
    friday = START + timedelta(days=4)
    assert "Erev Shabbos" in by_date[friday]


async def test_the_calendar_and_sensor_follow_a_temporary_change(house):
    await house.reload_schedule()
    await house.hass.services.async_call(
        DOMAIN,
        "add_change",
        {
            "change": {
                "from": START.isoformat(),
                "until": START.isoformat(),
                "days": "all",
                "kind": "time",
                "automation": "morning",
                "time": {"kind": "clock", "at": "06:30"},
            }
        },
        blocking=True,
    )
    assert house.hass.states.get(SENSOR).attributes["time"] == local(
        START, "06:30"
    ).isoformat(timespec="seconds")
    events = await _events(house, local(START, "00:00"), local(TOMORROW, "00:00"))
    assert events[0].start == local(START, "06:30")
    tomorrow = await _events(house, local(TOMORROW, "00:00"), local(TOMORROW, "12:00"))
    assert [event.start for event in tomorrow] == [local(TOMORROW, "07:00")]


async def test_the_calendars_own_state_is_the_next_automation(house):
    await house.reload_schedule()
    state = house.hass.states.get(CALENDAR)
    assert state.attributes["message"] == "Morning"
