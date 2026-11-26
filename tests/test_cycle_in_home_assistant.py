"""An entity set to cycle, run by the scheduler in a real Home Assistant core.

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

FAN = "light.fan"
SENSOR = "sensor.ryton_next_automation"


def _with_cycle():
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][0]["rooms"] = {
        "bath": {
            "entities": {
                FAN: {"cycle": {"on_minutes": 10, "off_minutes": 20, "for_minutes": 60}}
            }
        }
    }
    return schedule


async def _start(house):
    house.hass.states.async_set(FAN, "off")
    house.write_schedule(_with_cycle())
    await house.reload_schedule()


async def test_a_cycle_switches_at_each_of_its_moments_and_ends_off(house):
    await _start(house)
    for clock in ("07:00", "07:10", "07:30", "07:40", "08:00", "09:00"):
        await house.move_to(local(START, clock))
    assert house.light_calls == [
        (FAN, "turn_on"),
        (FAN, "turn_off"),
        (FAN, "turn_on"),
        (FAN, "turn_off"),
        (FAN, "turn_off"),
    ]
    assert house.hass.states.get(FAN).state == "off"


async def test_the_next_automation_is_never_a_moment_of_a_cycle(house):
    await _start(house)
    await house.move_to(local(START, "07:05"))
    assert house.hass.states.get(SENSOR).state == "Sunset"


async def test_a_restart_in_the_middle_of_a_cycle_brings_the_entity_to_its_place(house):
    await _start(house)
    await house.move_to(local(START, "07:00"))
    await house.stop_integration()
    house.light_calls.clear()
    await house.move_to(local(START, "07:35"))
    await house.start_integration()
    await house.hass.async_block_till_done()
    # 07:10 off and 07:30 on were missed: the fan is brought straight to on.
    assert house.light_calls == [(FAN, "turn_on")]
    await house.move_to(local(START, "07:40"))
    assert house.light_calls[-1] == (FAN, "turn_off")
