"""A child's room with its own, earlier Night, run in a real Home Assistant core.

Uses the pretend house of tests/test_time_travel.py: Morning at 07:00,
Sunset at 18:00 and Night at 23:00, each turning on one scene in the hall.

Needs Home Assistant's test tools, which do not load on Windows. On GitHub
these tests run on Linux.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from homeassistant.exceptions import ServiceValidationError  # noqa: E402
from voluptuous import Invalid  # noqa: E402

from custom_components.ryton_home_automations.const import DOMAIN  # noqa: E402
from custom_components.ryton_home_automations.view import async_view_data  # noqa: E402

from .test_time_travel import (  # noqa: E402, F401
    START,
    _enable_custom_integrations,
    _instant_waits,
    house,
    local,
)


async def _set(house, **data):
    return await house.hass.services.async_call(
        DOMAIN, "set_room_night", {"room": "hall", **data}, blocking=True, return_response=True
    )


async def test_a_childs_room_has_its_night_earlier_and_not_again_with_the_house(house):
    await house.reload_schedule()
    await house.move_to(local(START, "18:00"))
    answer = await _set(house, minutes=180)
    assert answer["room_night"] == {"hall": {"mode": "child", "minutes": 180}}
    before = len(house.scenes)
    await house.move_to(local(START, "19:59"))
    assert len(house.scenes) == before
    await house.move_to(local(START, "20:00"))
    assert len(house.scenes) == before + 1
    await house.move_to(local(START, "23:00"))
    assert len(house.scenes) == before + 1


async def test_a_clock_time_and_turning_it_off_again(house):
    await house.reload_schedule()
    await house.move_to(local(START, "18:00"))
    await _set(house, at="19:30")
    before = len(house.scenes)
    await house.move_to(local(START, "19:30"))
    assert len(house.scenes) == before + 1

    answer = await _set(house)
    assert answer["room_night"] == {}
    await house.move_to(local(START, "23:00"))
    data = await async_view_data(house.hass, 2)
    assert data["room_night"] == {}
    assert [a["id"] for a in data["days"][-1]["automations"]] == ["morning", "sunset", "night"]


async def test_the_view_shows_the_childs_night_and_what_it_is_counted_from(house):
    await house.reload_schedule()
    await _set(house, minutes=90)
    data = await async_view_data(house.hass, 1)
    today = data["days"][-1]
    assert data["room_night"] == {"hall": {"mode": "child", "minutes": 90}}
    assert today["night_usual"] == local(START, "23:00").isoformat(timespec="minutes")
    assert [(a["id"], a["time"][11:16]) for a in today["automations"]][-2:] == [
        ("night#own:hall", "21:30"),
        ("night", "23:00"),
    ]


async def test_a_setting_out_of_range_is_refused(house):
    await house.reload_schedule()
    with pytest.raises((ServiceValidationError, Invalid)):
        await _set(house, minutes=0)
    with pytest.raises((ServiceValidationError, Invalid)):
        await _set(house, at="7pm")


async def test_an_adults_room_is_left_at_night_and_has_its_own_night_later(house):
    await house.reload_schedule()
    await house.move_to(local(START, "18:00"))
    answer = await _set(house, mode="adult", minutes=90)
    assert answer["room_night"] == {"hall": {"mode": "adult", "minutes": 90}}
    before = len(house.scenes)
    await house.move_to(local(START, "23:00"))
    assert len(house.scenes) == before
    await house.move_to(local(START + timedelta(days=1), "00:29"))
    assert len(house.scenes) == before
    await house.move_to(local(START + timedelta(days=1), "00:30"))
    assert len(house.scenes) == before + 1
