"""The warning blink: an entity set to blink, then put back as it was.

Runs without Home Assistant.
"""

from __future__ import annotations

import pytest

from engine.actions import blink_entities, blink_pattern, is_blink, latest_state, plan_steps
from engine.describe import describe_by_room
from engine.scenes import schedule_scenes
from engine.time_resolver import ScheduleError

from .test_day_list import TUESDAY, build, make_schedule

BLINK = {"blink": True}
LAMP = "light.dining_lamp"


def test_the_pattern_is_three_blinks_a_break_and_three_more():
    assert blink_pattern() == [
        ("on", 0.2), ("off", 0.05),
        ("on", 0.2), ("off", 0.05),
        ("on", 0.2), ("off", 0.5),
        ("on", 0.2), ("off", 0.05),
        ("on", 0.2), ("off", 0.05),
        ("on", 0.2), ("off", 0),
    ]


def test_the_slower_pattern_adds_a_fifth_of_a_second_to_each_wait():
    slow = blink_pattern(slow=True)
    assert [state for state, _ in slow] == [state for state, _ in blink_pattern()]
    assert [round(wait, 2) for _, wait in slow[:6]] == [0.4, 0.25, 0.4, 0.25, 0.4, 0.7]
    assert slow[-1] == ("off", 0)


def test_a_blink_is_read_from_an_action():
    assert is_blink(LAMP, BLINK) is True
    assert is_blink("switch.porch", BLINK) is True
    assert is_blink(LAMP, {"state": "on"}) is False


@pytest.mark.parametrize("action", [{"blink": False}, {"blink": 3}, {"blink": True, "state": "on"}])
def test_a_blink_that_is_not_understood_is_refused(action):
    with pytest.raises(ScheduleError):
        is_blink(LAMP, action)


@pytest.mark.parametrize("entity_id", ["cover.shade", "select.mode", "scene.evening"])
def test_only_something_switched_on_and_off_can_blink(entity_id):
    with pytest.raises(ScheduleError):
        is_blink(entity_id, BLINK)


def test_the_entities_to_blink_are_found_and_switched_off_rooms_left_out():
    rooms = {
        "dining": {"entities": {LAMP: BLINK, "light.other": {"state": "on"}}},
        "hall": {"entities": {"light.hall": BLINK}},
        "den": {"scene": "scene.den"},
    }
    assert blink_entities(rooms) == [LAMP, "light.hall"]
    assert blink_entities(rooms, rooms_off={"hall"}) == [LAMP]


def test_a_blink_is_not_one_of_the_automations_ordinary_steps():
    rooms = {"dining": {"entities": {LAMP: BLINK, "light.other": {"state": "on"}}}}
    steps = plan_steps(rooms)
    assert [call.entity_id for step in steps for call in step.calls] == ["light.other"]
    assert plan_steps({"dining": {"entities": {LAMP: BLINK}}}) == []


def test_a_missed_blink_leaves_the_entity_where_it_was_last_set():
    missed = [
        {"dining": {"entities": {LAMP: {"state": "on", "brightness_pct": 60}}}},
        {"dining": {"entities": {LAMP: BLINK}}},
    ]
    assert latest_state(missed) == {
        "dining": {"entities": {LAMP: {"state": "on", "brightness_pct": 60}}}
    }
    assert latest_state([{"dining": {"entities": {LAMP: BLINK}}}]) == {}


def test_a_scene_made_in_the_form_cannot_hold_a_blink():
    schedule = {
        "scenes": [{"id": "ryton_warn", "name": "Warn", "room": "dining", "entities": {LAMP: BLINK}}]
    }
    with pytest.raises(ScheduleError):
        schedule_scenes(schedule)


def test_a_blink_is_said_in_words():
    rooms = {"dining": {"entities": {LAMP: BLINK}}}
    assert describe_by_room(rooms, {}, lambda entity_id: "Lamp") == [("dining", "Lamp blinks")]


def test_a_day_with_a_blink_is_listed_like_any_other():
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][1]["rooms"] = {"dining": {"entities": {LAMP: BLINK}}}
    got = build(schedule, TUESDAY)
    assert [a.id for a in got.automations] == ["morning", "sunset", "night"]
    assert got.cycle_steps == ()
