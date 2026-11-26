"""Away mode and away for a meal, run by the scheduler in a real Home Assistant core.

Uses the pretend house of tests/test_time_travel.py: Morning at 07:00,
Sunset at 18:00 and Night at 23:00, each turning on one scene in the hall.
The first day is Monday 23 November 2026.

Needs Home Assistant's test tools, which do not load on Windows. On GitHub
these tests run on Linux.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from homeassistant.exceptions import ServiceValidationError  # noqa: E402

from custom_components.ryton_home_automations.const import DOMAIN  # noqa: E402
from custom_components.ryton_home_automations.view import (  # noqa: E402
    DATA_VIEW,
    async_view_data,
)

from .test_away import with_summer  # noqa: E402
from .test_day_list import make_schedule  # noqa: E402
from .test_time_travel import (  # noqa: E402, F401
    START,
    _enable_custom_integrations,
    _instant_waits,
    house,
    local,
)

HALL, DEN = "light.hall", "light.den"
TOMORROW = START + timedelta(days=1)
FRIDAY = START + timedelta(days=4)
SHABBOS = START + timedelta(days=5)


async def _start(house, schedule=None):
    """The house at 08:00 on Monday, Morning having run, with both lights on."""
    house.hass.states.async_set(HALL, "on")
    house.hass.states.async_set(DEN, "on")
    house.write_schedule(schedule or make_schedule())
    await house.reload_schedule()
    house.hass.data[DATA_VIEW]["scheduler"].house_rooms = lambda: {
        "hall": [HALL],
        "den": [DEN],
    }
    await house.move_to(local(START, "08:00"))
    house.scenes.clear()
    house.light_calls.clear()


async def _away(house, run, until, rooms=None):
    data = {"run": run, "until": until}
    if rooms is not None:
        data["rooms"] = rooms
    answer = await house.hass.services.async_call(
        DOMAIN, "start_away", data, blocking=True, return_response=True
    )
    await house.hass.async_block_till_done()
    return answer["change"]


async def _end(house):
    answer = await house.hass.services.async_call(
        DOMAIN, "end_away", {}, blocking=True, return_response=True
    )
    await house.hass.async_block_till_done()
    return answer["ended"]


async def test_everything_off_switches_the_house_off_and_runs_nothing(house):
    await _start(house)
    await _away(house, "off", TOMORROW.isoformat())
    assert sorted(house.light_calls) == [(DEN, "turn_off"), (HALL, "turn_off")]
    for day, clock in ((START, "18:00"), (START, "23:00"), (TOMORROW, "07:00"), (TOMORROW, "23:00")):
        await house.move_to(local(day, clock))
    assert house.scenes == []


async def test_away_until_a_date_ends_at_the_rollover_after_it(house):
    await _start(house)
    change = await _away(house, "off", TOMORROW.isoformat())
    after = TOMORROW + timedelta(days=1)
    assert change["ends_at"] == local(after, "04:00").isoformat(timespec="seconds")
    for day, clock in ((START, "23:00"), (TOMORROW, "23:00"), (after, "03:59")):
        await house.move_to(local(day, clock))
    assert house.scenes == []
    # The hall goes to where the schedule has it: last night's Night.
    await house.move_to(local(after, "04:00"))
    assert len(house.scenes) == 1
    await house.move_to(local(after, "07:00"))
    assert len(house.scenes) == 2


async def test_cancelling_brings_the_house_back_to_its_schedule(house):
    await _start(house)
    await _away(house, "off", TOMORROW.isoformat())
    await house.move_to(local(START, "09:00"))
    assert house.scenes == []
    assert await _end(house) == 1
    # Morning is where the schedule has the hall at 09:00.
    assert len(house.scenes) == 1
    await house.move_to(local(START, "18:00"))
    assert len(house.scenes) == 2
    assert await _end(house) == 0


async def test_removing_the_away_change_ends_it_too(house):
    await _start(house)
    change = await _away(house, "off", TOMORROW.isoformat())
    await house.move_to(local(START, "09:00"))
    await house.hass.services.async_call(
        DOMAIN, "remove_change", {"id": change["id"]}, blocking=True
    )
    await house.hass.async_block_till_done()
    assert len(house.scenes) == 1
    await house.move_to(local(START, "18:00"))
    assert len(house.scenes) == 2


async def test_a_preset_runs_in_place_of_the_schedule(house):
    await _start(house, with_summer())
    await _away(house, "summer", TOMORROW.isoformat())
    # Straight to where the preset has the hall: on, from yesterday's Morning.
    assert house.light_calls == [(HALL, "turn_on")]
    await house.move_to(local(START, "09:00"))
    assert house.light_calls == [(HALL, "turn_on"), (HALL, "turn_on")]
    await house.move_to(local(START, "18:00"))
    assert house.scenes == []


async def test_only_the_ticked_rooms_keep_running(house):
    await _start(house)
    change = await _away(house, "rooms", TOMORROW.isoformat(), rooms=["hall"])
    assert change["rooms"] == ["hall"]
    # The den is switched off; the hall stays where its schedule has it.
    assert house.light_calls == [(DEN, "turn_off")]
    before = len(house.scenes)
    await house.move_to(local(START, "18:00"))
    assert len(house.scenes) == before + 1


async def test_until_motzei_shabbos_is_an_hour_after_havdalah(house):
    await _start(house)
    change = await _away(house, "off", "motzei")
    # The stand-in calendar's havdalah is 19:12.
    assert change["ends_at"] == local(SHABBOS, "20:12").isoformat(timespec="seconds")


async def test_a_second_choice_takes_over_from_the_first(house):
    await _start(house, with_summer())
    await _away(house, "off", TOMORROW.isoformat())
    await house.move_to(local(START, "08:30"))
    await _away(house, "summer", TOMORROW.isoformat())
    data = await async_view_data(house.hass, 1)
    assert data["away"]["run"] == "summer"
    assert [c["run"] for c in data["changes"] if c["kind"] == "away"] == ["summer"]


async def test_a_preset_the_schedule_does_not_have_is_refused(house):
    await _start(house)
    with pytest.raises(ServiceValidationError):
        await _away(house, "winter", TOMORROW.isoformat())


async def test_the_view_says_what_away_mode_is_running(house):
    await _start(house, with_summer())
    data = await async_view_data(house.hass, 1)
    assert data["away"] is None
    assert data["presets"] == [{"id": "summer", "name": "Summer"}]
    assert data["motzei"]["last"] == SHABBOS.isoformat()
    assert data["motzei"]["ends_at"] == local(SHABBOS, "20:12").isoformat(timespec="minutes")

    change = await _away(house, "summer", TOMORROW.isoformat())
    data = await async_view_data(house.hass, 1)
    assert data["away"]["run"] == "summer"
    assert data["away"]["name"] == "Summer"
    assert data["away"]["by"] == "client"
    assert data["away"]["id"] == change["id"]

    await house.move_to(local(START, "09:30"))
    await _end(house)
    data = await async_view_data(house.hass, 1)
    assert data["away"] is None
    # The ended choice is kept in the house a while, but no longer shown.
    assert [c for c in data["changes"] if c["kind"] == "away"] == []


async def test_the_view_says_when_the_houses_own_dates_have_it_away(house):
    await _start(house, with_summer(("11-20", "11-30", "off")))
    data = await async_view_data(house.hass, 1)
    assert data["away"]["run"] == "off"
    assert data["away"]["by"] == "dates"


async def test_the_view_lists_the_coming_meals_and_which_are_out(house):
    await _start(house)
    data = await async_view_data(house.hass, 1)
    assert [(m["date"], m["meal"], m["name"]) for m in data["meals"]][:3] == [
        (FRIDAY.isoformat(), "night", "Shabbos night"),
        (SHABBOS.isoformat(), "day", "Shabbos day"),
        (SHABBOS.isoformat(), "shalosh_seudos", "Shalosh seudos"),
    ]
    assert all(m["out"] is None for m in data["meals"])

    answer = await house.hass.services.async_call(
        DOMAIN,
        "add_change",
        {
            "change": {
                "from": FRIDAY.isoformat(),
                "until": FRIDAY.isoformat(),
                "days": "all",
                "kind": "meal_out",
                "meal": "night",
            }
        },
        blocking=True,
        return_response=True,
    )
    data = await async_view_data(house.hass, 1)
    assert [m["out"] for m in data["meals"]][:3] == [answer["change"]["id"], None, None]


async def test_out_for_a_meal_the_rooms_set_for_it_take_that_setting(house):
    schedule = make_schedule()
    night = next(a for a in schedule["days"]["friday"]["automations"] if a["id"] == "night")
    night["when_out"] = {"night": {"hall": {"entities": {HALL: {"state": "off"}}}}}
    await _start(house, schedule)
    await house.hass.services.async_call(
        DOMAIN,
        "add_change",
        {
            "change": {
                "from": FRIDAY.isoformat(),
                "until": FRIDAY.isoformat(),
                "days": "all",
                "kind": "meal_out",
                "meal": "night",
            }
        },
        blocking=True,
    )
    await house.move_to(local(FRIDAY, "22:59"))
    house.light_calls.clear()
    scenes = len(house.scenes)
    await house.move_to(local(FRIDAY, "23:00"))
    assert house.light_calls == [(HALL, "turn_off")]
    assert len(house.scenes) == scenes
