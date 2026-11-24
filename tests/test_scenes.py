"""The schedule's own scenes. Runs without Home Assistant."""

from __future__ import annotations

import pytest

from engine.actions import latest_state, plan_steps
from engine.day_list import check_schedule
from engine.scenes import entity_id_of, expand_scenes, schedule_scenes
from engine.time_resolver import ScheduleError

from .test_day_list import make_schedule

ON, OFF = {"state": "on"}, {"state": "off"}


def scene(scene_id="ryton_kitchen_supper", **changes):
    made = {
        "id": scene_id,
        "name": "Supper",
        "room": "kitchen",
        "entities": {"light.spots": ON, "switch.hot_plate": OFF},
    }
    made.update(changes)
    return made


def with_scenes(*scenes):
    schedule = make_schedule()
    schedule["scenes"] = list(scenes)
    return schedule


def sent(rooms, merged=False):
    return [
        (call.entity_id, call.service)
        for step in plan_steps(rooms, merged=merged)
        for call in step.calls
    ]


# --- reading the scenes ------------------------------------------------------


def test_a_schedule_without_scenes_has_none():
    assert schedule_scenes(make_schedule()) == {}
    assert schedule_scenes(None) == {}
    check_schedule(make_schedule())


def test_a_scene_is_read_by_its_identifier():
    scenes = schedule_scenes(with_scenes(scene()))
    assert list(scenes) == ["ryton_kitchen_supper"]
    assert scenes["ryton_kitchen_supper"]["name"] == "Supper"
    assert scenes["ryton_kitchen_supper"]["room"] == "kitchen"
    assert entity_id_of("ryton_kitchen_supper") == "scene.ryton_kitchen_supper"


def test_a_schedule_with_a_good_scene_is_accepted():
    check_schedule(with_scenes(scene()))


@pytest.mark.parametrize(
    "bad",
    [
        scene("kitchen_supper"),
        scene("ryton_"),
        scene("ryton_Kitchen"),
        scene("ryton_kitchen supper"),
        scene("scene.ryton_kitchen"),
        scene(id=None),
        scene(name=""),
        scene(name="   "),
        scene(name=None),
        scene(room=""),
        scene(entities={}),
        scene(entities=None),
        scene(entities={"light.spots": {"state": "sideways"}}),
        scene(entities={"scene.other": ON}),
        "ryton_kitchen_supper",
    ],
)
def test_a_scene_that_is_not_understood_refuses_the_schedule(bad):
    with pytest.raises(ScheduleError):
        check_schedule(with_scenes(bad))


def test_the_same_scene_twice_refuses_the_schedule():
    with pytest.raises(ScheduleError, match="twice"):
        check_schedule(with_scenes(scene(), scene()))


def test_scenes_that_are_not_a_list_refuse_the_schedule():
    schedule = make_schedule()
    schedule["scenes"] = {"ryton_kitchen_supper": scene()}
    with pytest.raises(ScheduleError):
        check_schedule(schedule)


# --- a room that uses one ----------------------------------------------------


def test_a_room_using_a_schedule_scene_gets_its_entities():
    scenes = schedule_scenes(with_scenes(scene()))
    rooms = {
        "kitchen": {"scene": "scene.ryton_kitchen_supper"},
        "porch": {"entities": {"light.porch": ON}},
    }
    expanded = expand_scenes(rooms, scenes)
    assert expanded == {
        "kitchen": {"entities": {"light.spots": ON, "switch.hot_plate": OFF}},
        "porch": {"entities": {"light.porch": ON}},
    }
    # No scene is turned on in Home Assistant: every entity is sent itself.
    assert sorted(sent(expanded)) == [
        ("light.porch", "turn_on"),
        ("light.spots", "turn_on"),
        ("switch.hot_plate", "turn_off"),
    ]


def test_any_other_scene_is_left_for_home_assistant():
    scenes = schedule_scenes(with_scenes(scene()))
    rooms = {"kitchen": {"scene": "scene.kitchen_bright"}}
    assert expand_scenes(rooms, scenes) == rooms
    assert sent(expand_scenes(rooms, scenes)) == [("scene.kitchen_bright", "turn_on")]


def test_with_no_scenes_the_rooms_are_unchanged():
    rooms = {"kitchen": {"scene": "scene.ryton_gone"}, "porch": {"entities": {"light.porch": ON}}}
    assert expand_scenes(rooms, {}) == rooms


def test_the_rooms_given_are_not_altered():
    scenes = schedule_scenes(with_scenes(scene()))
    rooms = {"kitchen": {"scene": "scene.ryton_kitchen_supper"}}
    expand_scenes(rooms, scenes)
    assert rooms == {"kitchen": {"scene": "scene.ryton_kitchen_supper"}}
    assert scenes["ryton_kitchen_supper"]["entities"] == {
        "light.spots": ON,
        "switch.hot_plate": OFF,
    }


def test_after_a_restart_entities_set_after_the_scene_win():
    scenes = schedule_scenes(with_scenes(scene()))
    missed = [
        {"kitchen": {"entities": {"light.counter": ON}}},
        {"kitchen": {"scene": "scene.ryton_kitchen_supper"}},
        {"kitchen": {"entities": {"light.spots": OFF}}},
    ]
    expanded = expand_scenes(latest_state(missed), scenes)
    assert expanded == {"kitchen": {"entities": {"switch.hot_plate": OFF, "light.spots": OFF}}}
    assert sorted(sent(expanded, merged=True)) == [
        ("light.spots", "turn_off"),
        ("switch.hot_plate", "turn_off"),
    ]
