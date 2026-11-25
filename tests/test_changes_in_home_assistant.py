"""The client's temporary changes inside a real Home Assistant core.

The clock is moved by hand, as in tests/test_time_travel.py, whose pretend
house this uses: every automation of the made-up schedule turns on one scene
in the hall, named after its day. Morning is at 07:00, Sunset at 18:00 and
Night at 23:00.

Needs Home Assistant's test tools, which do not load on Windows. On GitHub
these tests run on Linux.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from homeassistant.exceptions import ServiceValidationError  # noqa: E402

from custom_components.ryton_home_automations.const import DOMAIN  # noqa: E402

from .test_time_travel import (  # noqa: E402, F401
    START,
    _enable_custom_integrations,
    _instant_waits,
    house,
    local,
)


async def _call(house, name, **data):
    return await house.hass.services.async_call(
        DOMAIN, name, data, blocking=True, return_response=True
    )


def _change(kind, first=START, last=None, days="all", **more):
    return {
        "from": first.isoformat(),
        "until": (last or first).isoformat(),
        "days": days,
        "kind": kind,
        **more,
    }


async def _add(house, change):
    return (await _call(house, "add_change", change=change))["change"]


async def test_a_time_change_moves_tonights_night(house):
    await house.reload_schedule()
    made = await _add(
        house, _change("time", automation="night", time={"kind": "clock", "at": "22:00"})
    )
    assert made["id"] and made["made_at"]
    for clock in ("07:00", "18:00", "22:00", "23:00", "23:30"):
        await house.move_to(local(START, clock))
    assert house.scene_times() == [
        (local(START, "07:00"), "scene.weekday"),
        (local(START, "18:00"), "scene.weekday"),
        (local(START, "22:00"), "scene.weekday"),
    ]


async def test_an_automation_that_already_ran_does_not_run_again(house):
    await house.reload_schedule()
    await house.move_to(local(START, "07:00"))
    await house.move_to(local(START, "18:00"))
    await _add(house, _change("time", automation="sunset", shift_minutes=60))
    await house.move_to(local(START, "19:00"))
    await house.move_to(local(START, "19:30"))
    assert house.scene_times() == [
        (local(START, "07:00"), "scene.weekday"),
        (local(START, "18:00"), "scene.weekday"),
    ]
    # Nor at the next rollover, when the lists are fixed again.
    await house.move_to(local(START, "23:00"))
    await house.move_to(local(START + timedelta(days=1), "04:00"))
    assert len(house.scenes) == 3


async def test_an_automation_moved_to_a_time_already_past_runs_at_once(house):
    await house.reload_schedule()
    await house.move_to(local(START, "07:00"))
    await house.move_to(local(START, "18:00"))
    await house.move_to(local(START, "19:00"))
    await _add(
        house, _change("time", automation="night", time={"kind": "clock", "at": "18:30"})
    )
    await house.hass.async_block_till_done()
    assert house.scene_times()[-1] == (local(START, "19:00"), "scene.weekday")
    assert len(house.scenes) == 3
    await house.move_to(local(START, "23:00"))
    assert len(house.scenes) == 3


async def test_removing_a_change_puts_the_time_back(house):
    await house.reload_schedule()
    made = await _add(
        house, _change("time", automation="night", time={"kind": "clock", "at": "22:00"})
    )
    assert (await _call(house, "remove_change", id=made["id"])) == {"removed": True}
    assert (await _call(house, "remove_change", id=made["id"])) == {"removed": False}
    for clock in ("07:00", "18:00", "22:00"):
        await house.move_to(local(START, clock))
    assert len(house.scenes) == 2
    await house.move_to(local(START, "23:00"))
    assert house.scene_times()[-1] == (local(START, "23:00"), "scene.weekday")


async def test_a_room_switched_off_is_skipped_until_it_is_switched_on(house):
    await house.reload_schedule()
    assert (await _call(house, "set_room_scheduling", room="hall", scheduling="off")) == {
        "rooms_off": ["hall"]
    }
    await house.move_to(local(START, "07:00"))
    assert house.scenes == []
    await _call(house, "set_room_scheduling", room="hall", scheduling="on")
    await house.move_to(local(START, "18:00"))
    assert house.scene_times() == [(local(START, "18:00"), "scene.weekday")]


async def test_a_room_off_until_a_date_comes_back_by_itself(house):
    await house.reload_schedule()
    await _add(house, _change("room_switch", room="hall", scheduling="off"))
    for clock in ("07:00", "18:00", "23:00"):
        await house.move_to(local(START, clock))
    assert house.scenes == []
    tomorrow = START + timedelta(days=1)
    await house.move_to(local(tomorrow, "04:00"))
    await house.move_to(local(tomorrow, "07:00"))
    assert house.scene_times() == [(local(tomorrow, "07:00"), "scene.weekday")]


async def test_a_room_change_adds_an_entity_after_the_rooms_scene(house):
    house.hass.states.async_set("light.hall", "off")
    await house.reload_schedule()
    await _add(
        house,
        _change("room", automation="morning", room="hall", entities={"light.hall": {"state": "on"}}),
    )
    await house.move_to(local(START, "07:00"))
    assert house.scene_times() == [(local(START, "07:00"), "scene.weekday")]
    assert house.light_calls == [("light.hall", "turn_on")]
    # Only Morning was changed.
    await house.move_to(local(START, "18:00"))
    assert len(house.light_calls) == 1


async def test_changes_survive_a_restart(house):
    await house.reload_schedule()
    made = await _add(house, _change("simcha", last=START + timedelta(days=3)))
    await _call(house, "set_room_scheduling", room="guest_room", scheduling="off")
    await house.stop_integration()
    await house.start_integration()
    assert await _call(house, "list_changes") == {
        "rooms_off": ["guest_room"],
        "changes": [made],
    }


async def test_a_change_is_dropped_after_its_last_date(house):
    await house.reload_schedule()
    await _add(house, _change("simcha"))
    await house.move_to(local(START + timedelta(days=1), "04:00"))
    assert len((await _call(house, "list_changes"))["changes"]) == 1  # yesterday's list still uses it
    await house.move_to(local(START + timedelta(days=2), "04:00"))
    assert (await _call(house, "list_changes"))["changes"] == []


async def test_a_change_that_sets_a_scene_is_refused(house):
    await house.reload_schedule()
    with pytest.raises(ServiceValidationError):
        await _add(
            house,
            _change("room", automation="morning", room="hall", entities={"scene.x": {"state": "on"}}),
        )
    assert (await _call(house, "list_changes"))["changes"] == []


async def test_the_days_in_a_span_of_dates_are_listed_by_the_engine(house):
    await house.reload_schedule()
    answer = await _call(
        house,
        "days_in_dates",
        **{"from": START.isoformat(), "until": (START + timedelta(days=6)).isoformat()},
    )
    found = {entry["day"]: entry["dates"] for entry in answer["days"]}
    assert set(found) == {"weekday", "friday", "shabbos"}
    assert found["friday"] == [(START + timedelta(days=4)).isoformat()]
    assert len(found["weekday"]) == 5
