"""What the client's view reads from the house, in a real Home Assistant core.

Uses the pretend house of tests/test_time_travel.py: Morning at 07:00,
Sunset at 18:00 and Night at 23:00, each turning on one scene in the hall.

Needs Home Assistant's test tools, which do not load on Windows. On GitHub
these tests run on Linux. The screen itself is not tested here.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from custom_components.ryton_home_automations.const import DOMAIN  # noqa: E402
from custom_components.ryton_home_automations.view import async_view_data  # noqa: E402

from .test_time_travel import (  # noqa: E402, F401
    START,
    _enable_custom_integrations,
    _instant_waits,
    house,
    local,
)


def _minutes(moment):
    return moment.isoformat(timespec="minutes")


async def test_with_no_schedule_the_view_says_so(house):
    data = await async_view_data(house.hass, 7)
    assert data["ready"] is False
    assert data["days"] == []


async def test_the_view_lists_the_coming_days_with_what_each_automation_does(house):
    await house.reload_schedule()
    data = await async_view_data(house.hass, 7)
    assert data["ready"] is True
    assert data["today"] == START.isoformat()
    # Yesterday's automations are all past, so the list starts today.
    assert [day["date"] for day in data["days"]][0] == START.isoformat()
    assert len(data["days"]) == 7

    today = data["days"][0]
    assert today["day"] == "weekday"
    assert today["day_name"] == "Weekday"
    assert [(a["name"], a["time"], a["past"]) for a in today["automations"]] == [
        ("Morning", _minutes(local(START, "07:00")), False),
        ("Sunset", _minutes(local(START, "18:00")), False),
        ("Night", _minutes(local(START, "23:00")), False),
    ]
    rooms = today["automations"][0]["rooms"]
    assert [room["room"] for room in rooms] == ["hall"]
    assert rooms[0]["text"].startswith("scene ")


async def test_an_automation_that_has_run_is_marked_past(house):
    await house.reload_schedule()
    await house.move_to(local(START, "07:00"))
    data = await async_view_data(house.hass, 1)
    assert [a["past"] for a in data["days"][0]["automations"]] == [True, False, False]


async def test_the_view_offers_each_days_automations_to_choose_from(house):
    await house.reload_schedule()
    data = await async_view_data(house.hass, 1)
    assert {"id": "morning", "name": "Morning"} in data["automations_by_day"]["weekday"]


async def test_the_view_shows_a_temporary_change_and_its_effect(house):
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
    data = await async_view_data(house.hass, 2)
    assert data["days"][0]["automations"][0]["time"] == _minutes(local(START, "06:30"))
    tomorrow = START + timedelta(days=1)
    assert data["days"][1]["automations"][0]["time"] == _minutes(local(tomorrow, "07:00"))
    assert [(c["kind"], c["automation"]) for c in data["changes"]] == [("time", "morning")]


async def test_a_room_switched_off_is_left_out_of_what_automations_do(house):
    await house.reload_schedule()
    await house.hass.services.async_call(
        DOMAIN, "set_room_scheduling", {"room": "hall", "scheduling": "off"}, blocking=True
    )
    data = await async_view_data(house.hass, 1)
    assert data["rooms_off"] == ["hall"]
    assert data["days"][0]["rooms_off"] == ["hall"]
    assert all(a["rooms"] == [] for a in data["days"][0]["automations"])


async def test_the_screen_reads_the_view_over_the_websocket(house, hass_ws_client):
    await house.reload_schedule()
    client = await hass_ws_client(house.hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/view", "days": 3})
    answer = await client.receive_json()
    assert answer["success"] is True
    assert answer["result"]["ready"] is True
    assert len(answer["result"]["days"]) == 3
