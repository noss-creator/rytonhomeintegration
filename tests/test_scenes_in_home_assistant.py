"""The schedule's own scenes, inside a real Home Assistant core.

Needs Home Assistant's test tools, which do not load on Windows. On GitHub
these tests run on Linux.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

from homeassistant.helpers import area_registry as ar  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

from .test_day_list import make_schedule  # noqa: E402
from .test_time_travel import (  # noqa: E402, F401
    START,
    _enable_custom_integrations,
    _instant_waits,
    house,
    local,
)

SUPPER = "scene.ryton_kitchen_supper"


def with_scene(name="Supper", used=True, entities=None):
    schedule = make_schedule()
    schedule["scenes"] = [
        {
            "id": "ryton_kitchen_supper",
            "name": name,
            "room": "kitchen",
            "entities": entities
            or {"light.a": {"state": "on"}, "light.b": {"state": "off"}},
        }
    ]
    if used:
        schedule["days"]["weekday"]["automations"][0]["rooms"] = {"kitchen": {"scene": SUPPER}}
    return schedule


async def publish(house, schedule):
    house.write_schedule(schedule)
    await house.reload_schedule()
    await house.hass.async_block_till_done()


def lights(house):
    house.hass.states.async_set("light.a", "off")
    house.hass.states.async_set("light.b", "on")


async def test_a_scene_in_the_schedule_appears_in_home_assistant(house):
    ar.async_get(house.hass).async_create("Kitchen")
    assert house.hass.states.get(SUPPER) is None

    await publish(house, with_scene())

    state = house.hass.states.get(SUPPER)
    assert state is not None
    # The identifier carries the prefix. The name people see does not.
    assert state.attributes["friendly_name"] == "Supper"
    assert er.async_get(house.hass).async_get(SUPPER).area_id == "kitchen"


async def test_an_automation_using_the_scene_sets_its_entities_itself(house):
    lights(house)
    await publish(house, with_scene())
    await house.move_to(local(START, "07:00"))

    assert sorted(house.light_calls) == [("light.a", "turn_on"), ("light.b", "turn_off")]
    assert house.hass.states.get("light.a").state == "on"
    assert house.hass.states.get("light.b").state == "off"
    # Home Assistant was not asked to turn the scene on.
    assert SUPPER not in [scene for _, scene in house.scenes]


async def test_an_entity_of_the_scene_that_misses_is_sent_again(house, caplog):
    lights(house)
    house.ignore = {"light.a": 1}
    await publish(house, with_scene())
    await house.move_to(local(START, "07:00"))

    assert house.light_calls.count(("light.a", "turn_on")) == 2
    assert house.hass.states.get("light.a").state == "on"
    assert "still failing" not in caplog.text


async def test_turning_the_scene_on_by_hand_sets_its_entities(house):
    lights(house)
    await publish(house, with_scene(used=False))

    scene = house.hass.data["scene"].get_entity(SUPPER)
    await scene.async_activate()
    await house.hass.async_block_till_done()

    assert sorted(house.light_calls) == [("light.a", "turn_on"), ("light.b", "turn_off")]


async def test_a_renamed_scene_takes_its_new_name(house):
    await publish(house, with_scene())
    await publish(house, with_scene(name="Friday supper"))

    assert house.hass.states.get(SUPPER).attributes["friendly_name"] == "Friday supper"


async def test_a_scene_taken_out_of_the_schedule_leaves_home_assistant(house):
    await publish(house, with_scene())
    assert house.hass.states.get(SUPPER) is not None

    await publish(house, make_schedule())

    assert house.hass.states.get(SUPPER) is None
    assert er.async_get(house.hass).async_get(SUPPER) is None


async def test_a_scene_put_back_appears_again(house):
    await publish(house, with_scene())
    await publish(house, make_schedule())
    await publish(house, with_scene())

    assert house.hass.states.get(SUPPER) is not None


async def test_the_scenes_come_back_after_a_restart_with_no_website(house):
    lights(house)
    await publish(house, with_scene(used=False))
    await house.stop_integration()
    await house.start_integration()

    assert house.hass.states.get(SUPPER).attributes["friendly_name"] == "Supper"
    scene = house.hass.data["scene"].get_entity(SUPPER)
    await scene.async_activate()
    await house.hass.async_block_till_done()
    assert ("light.a", "turn_on") in house.light_calls


async def test_the_scene_shows_what_it_does(house):
    lights(house)
    house.hass.states.async_set("light.a", "off", {"friendly_name": "Spots"})
    entities = {"light.a": {"state": "on", "brightness_pct": 75}, "light.b": {"state": "off"}}
    await publish(house, with_scene(used=False, entities=entities))

    shown = house.hass.states.get(SUPPER).attributes
    assert shown["entity_id"] == ["light.a", "light.b"]
    assert shown["Spots"] == "On, 75%"
    assert "fade_seconds" not in shown

    # A change to the scene in the schedule shows here too.
    entities["light.a"] = {"state": "off"}
    await publish(house, with_scene(used=False, entities=entities))
    assert house.hass.states.get(SUPPER).attributes["Spots"] == "Off"
