"""The warning blink, run by the scheduler in a real Home Assistant core.

Uses the pretend house of tests/test_time_travel.py. Needs Home Assistant's
test tools, which do not load on Windows. On GitHub these tests run on Linux.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from .test_day_list import make_schedule  # noqa: E402
from .test_time_travel import (  # noqa: E402, F401
    START,
    _enable_custom_integrations,
    _instant_waits,
    house,
    local,
)

ON_LAMP = "light.was_on"
OFF_LAMP = "light.was_off"


def _with_blink(slow=False):
    schedule = make_schedule()
    schedule["settings"]["blink_slow"] = slow
    schedule["days"]["weekday"]["automations"][0]["rooms"] = {
        "dining": {"entities": {ON_LAMP: {"blink": True}, OFF_LAMP: {"blink": True}}}
    }
    return schedule


async def _start(house, schedule=None):
    house.hass.states.async_set(ON_LAMP, "on")
    house.hass.states.async_set(OFF_LAMP, "off")
    house.write_schedule(schedule or _with_blink())
    await house.reload_schedule()


def _calls(house, entity_id):
    return [service for entity, service in house.light_calls if entity == entity_id]


async def test_a_light_blinks_six_times_and_goes_back_to_how_it_was(house):
    await _start(house)
    await house.move_to(local(START, "07:00"))
    # Six times on and off, then the one that was on is switched back on.
    assert _calls(house, ON_LAMP) == ["turn_on", "turn_off"] * 6 + ["turn_on"]
    assert _calls(house, OFF_LAMP) == ["turn_on", "turn_off"] * 6
    assert house.hass.states.get(ON_LAMP).state == "on"
    assert house.hass.states.get(OFF_LAMP).state == "off"


async def test_a_blink_missed_over_a_restart_is_not_replayed(house):
    await _start(house)
    await house.stop_integration()
    await house.move_to(local(START, "08:00"))
    await house.start_integration()
    await house.hass.async_block_till_done()
    assert house.light_calls == []


async def test_a_room_switched_off_does_not_blink(house):
    await _start(house)
    await house.hass.services.async_call(
        "ryton_home_automations",
        "set_room_scheduling",
        {"room": "dining", "scheduling": "off"},
        blocking=True,
    )
    await house.move_to(local(START, "07:00"))
    assert house.light_calls == []
