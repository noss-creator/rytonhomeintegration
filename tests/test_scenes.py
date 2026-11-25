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
        scene(fade_seconds=-1),
        scene(fade_seconds="slow"),
        scene(fade_seconds=True),
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


# --- fade ----------------------------------------------------------------------


def data_sent(rooms, **options):
    return {
        call.entity_id: call.data
        for step in plan_steps(rooms, **options)
        for call in step.calls
    }


def test_a_room_fades_by_its_own_fade():
    rooms = {
        "kitchen": {"entities": {"light.spots": ON}, "fade_seconds": 20},
        "porch": {"entities": {"light.porch": OFF}},
    }
    assert data_sent(rooms) == {"light.spots": {"transition": 20}, "light.porch": {}}


def test_a_rooms_own_fade_comes_before_the_automations():
    rooms = {
        "kitchen": {"entities": {"light.spots": ON}, "fade_seconds": 20},
        "porch": {"entities": {"light.porch": OFF}},
        "hall": {"entities": {"light.hall": ON}, "fade_seconds": 0},
    }
    assert data_sent(rooms, fade_seconds=5) == {
        "light.spots": {"transition": 20},
        "light.porch": {"transition": 5},
        "light.hall": {},
    }


def test_an_entitys_own_fade_comes_before_the_rooms():
    rooms = {
        "kitchen": {
            "entities": {"light.spots": {"state": "on", "fade_seconds": 3}, "light.led": ON},
            "fade_seconds": 20,
        }
    }
    assert data_sent(rooms) == {"light.spots": {"transition": 3}, "light.led": {"transition": 20}}


def test_only_lights_fade():
    rooms = {"kitchen": {"entities": {"switch.hot_plate": ON}, "fade_seconds": 20}}
    assert data_sent(rooms) == {"switch.hot_plate": {}}


@pytest.mark.parametrize("bad", [-1, "slow", True, None])
def test_a_room_fade_that_is_not_a_number_is_refused(bad):
    with pytest.raises(ScheduleError, match="fade"):
        plan_steps({"kitchen": {"entities": {"light.spots": ON}, "fade_seconds": bad}})


def test_a_home_assistant_scene_fades_by_the_rooms_fade():
    rooms = {"kitchen": {"scene": "scene.kitchen_bright", "fade_seconds": 8}}
    assert data_sent(rooms) == {"scene.kitchen_bright": {"transition": 8}}
    # The automation's fade alone does not reach a scene.
    plain = {"kitchen": {"scene": "scene.kitchen_bright"}}
    assert data_sent(plain, fade_seconds=5) == {"scene.kitchen_bright": {}}


def test_a_scene_keeps_the_fade_it_was_saved_with():
    scenes = schedule_scenes(with_scenes(scene(fade_seconds=12)))
    assert scenes["ryton_kitchen_supper"]["fade_seconds"] == 12
    expanded = expand_scenes({"kitchen": {"scene": "scene.ryton_kitchen_supper"}}, scenes)
    assert expanded["kitchen"]["fade_seconds"] == 12
    assert data_sent(expanded) == {"light.spots": {"transition": 12}, "switch.hot_plate": {}}


def test_a_scene_saved_without_a_fade_has_none():
    scenes = schedule_scenes(with_scenes(scene()))
    assert scenes["ryton_kitchen_supper"]["fade_seconds"] == 0
    expanded = expand_scenes({"kitchen": {"scene": "scene.ryton_kitchen_supper"}}, scenes)
    assert "fade_seconds" not in expanded["kitchen"]


def test_the_rooms_fade_comes_before_the_scenes():
    scenes = schedule_scenes(with_scenes(scene(fade_seconds=12)))
    rooms = {"kitchen": {"scene": "scene.ryton_kitchen_supper", "fade_seconds": 0}}
    assert data_sent(expand_scenes(rooms, scenes)) == {"light.spots": {}, "switch.hot_plate": {}}


def test_catching_up_after_a_restart_does_not_fade():
    scenes = schedule_scenes(with_scenes(scene(fade_seconds=12)))
    missed = latest_state([{"kitchen": {"scene": "scene.ryton_kitchen_supper"}}])
    expanded = expand_scenes(missed, scenes, fade=False)
    assert data_sent(expanded, merged=True) == {"light.spots": {}, "switch.hot_plate": {}}


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
