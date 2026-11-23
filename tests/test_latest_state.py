"""After a restart: bringing the house to where it should be now.

Missed automations are not replayed one after another. Each room goes
straight to its latest state. Runs without Home Assistant.
"""

from __future__ import annotations

import pytest

from engine.actions import latest_state, plan_steps
from engine.time_resolver import ScheduleError

ON, OFF = {"state": "on"}, {"state": "off"}


def entities(**by_room):
    return {room: {"entities": dict(states)} for room, states in by_room.items()}


def sent(rooms):
    """The (entity, service) pairs in the order they would be sent."""
    return [
        (call.entity_id, call.service)
        for step in plan_steps(rooms, merged=True)
        for call in step.calls
    ]


# --- entities only ---------------------------------------------------------


def test_nothing_missed_is_nothing_to_do():
    assert latest_state([]) == {}
    assert sent(latest_state([])) == []


def test_one_missed_automation_is_itself():
    erev_shabbos = entities(kitchen={"switch.hot_plate": ON, "light.spots": ON})
    assert latest_state([erev_shabbos]) == erev_shabbos


def test_automations_touching_different_entities_are_all_kept():
    erev_shabbos = entities(kitchen={"switch.hot_plate": ON})
    sunset = entities(porch={"light.porch": ON})
    assert latest_state([erev_shabbos, sunset]) == {
        "kitchen": {"entities": {"switch.hot_plate": ON}},
        "porch": {"entities": {"light.porch": ON}},
    }


def test_the_later_state_of_an_entity_wins_and_is_sent_once():
    """Before day seuda turns it on, After day seuda turns it off: only off is sent."""
    before = entities(dining_room={"light.chandelier": ON}, kitchen={"switch.hot_plate": ON})
    after = entities(dining_room={"light.chandelier": OFF}, kitchen={"switch.hot_plate": OFF})
    combined = latest_state([before, after])
    assert sent(combined) == [
        ("light.chandelier", "turn_off"),
        ("switch.hot_plate", "turn_off"),
    ]


def test_order_matters_not_which_came_with_more():
    first = entities(room={"light.a": OFF, "light.b": OFF})
    second = entities(room={"light.a": ON})
    assert latest_state([first, second])["room"]["entities"] == {
        "light.b": OFF, "light.a": ON,
    }
    assert latest_state([second, first])["room"]["entities"] == {
        "light.a": OFF, "light.b": OFF,
    }


def test_three_automations_in_a_row():
    morning = entities(room={"light.a": ON, "cover.shade": {"state": "open"}})
    sunset = entities(room={"light.a": OFF, "light.b": ON})
    night = entities(room={"light.b": OFF, "cover.shade": {"state": "closed"}})
    assert sent(latest_state([morning, sunset, night])) == [
        ("light.a", "turn_off"),
        ("light.b", "turn_off"),
        ("cover.shade", "close_cover"),
    ]


def test_the_missed_automations_themselves_are_left_untouched():
    before = entities(room={"light.a": ON})
    after = entities(room={"light.a": OFF})
    latest_state([before, after])
    assert before == entities(room={"light.a": ON})
    assert after == entities(room={"light.a": OFF})


# --- scenes ----------------------------------------------------------------


def test_the_latest_scene_set_to_a_room_is_the_one_that_runs():
    morning = {"living_room": {"scene": "scene.morning"}}
    evening = {"living_room": {"scene": "scene.evening"}}
    assert latest_state([morning, evening]) == {
        "living_room": {"scene": "scene.evening"}
    }
    assert sent(latest_state([morning, evening])) == [("scene.evening", "turn_on")]


def test_a_scene_replaces_what_was_set_in_that_room_before_it():
    earlier = entities(living_room={"light.lamp": ON, "light.spots": ON})
    scene = {"living_room": {"scene": "scene.shabbos"}}
    assert latest_state([earlier, scene]) == {
        "living_room": {"scene": "scene.shabbos"}
    }


def test_entities_set_after_a_scene_are_put_right_after_it_runs():
    scene = {"living_room": {"scene": "scene.shabbos"}}
    later = entities(living_room={"light.lamp": OFF})
    combined = latest_state([scene, later])
    assert combined == {
        "living_room": {"scene": "scene.shabbos", "entities": {"light.lamp": OFF}}
    }
    assert sent(combined) == [("scene.shabbos", "turn_on"), ("light.lamp", "turn_off")]


def test_entities_before_the_scene_are_dropped_and_those_after_are_kept():
    before = entities(living_room={"light.lamp": ON, "light.spots": ON})
    scene = {"living_room": {"scene": "scene.shabbos"}}
    after_1 = entities(living_room={"light.spots": OFF, "light.strip": ON})
    after_2 = entities(living_room={"light.strip": OFF})
    combined = latest_state([before, scene, after_1, after_2])
    assert sent(combined) == [
        ("scene.shabbos", "turn_on"),
        ("light.spots", "turn_off"),
        ("light.strip", "turn_off"),
    ]


def test_a_later_scene_replaces_an_earlier_scene_and_everything_between():
    combined = latest_state(
        [
            {"living_room": {"scene": "scene.morning"}},
            entities(living_room={"light.lamp": ON}),
            {"living_room": {"scene": "scene.evening"}},
            entities(living_room={"light.spots": OFF}),
        ]
    )
    assert sent(combined) == [("scene.evening", "turn_on"), ("light.spots", "turn_off")]


def test_a_scene_in_one_room_does_not_touch_another_room():
    combined = latest_state(
        [
            entities(kitchen={"light.spots": ON}, living_room={"light.lamp": ON}),
            {"living_room": {"scene": "scene.shabbos"}},
        ]
    )
    assert combined == {
        "kitchen": {"entities": {"light.spots": ON}},
        "living_room": {"scene": "scene.shabbos"},
    }


def test_all_scenes_run_before_any_entities():
    combined = latest_state(
        [
            entities(kitchen={"light.k": ON}),
            {"living_room": {"scene": "scene.living"}},
            entities(living_room={"light.lamp": OFF}),
            {"bedroom": {"scene": "scene.bedroom"}},
        ]
    )
    assert sent(combined) == [
        ("scene.living", "turn_on"),
        ("scene.bedroom", "turn_on"),
        ("light.k", "turn_on"),
        ("light.lamp", "turn_off"),
    ]


# --- carrying it out -------------------------------------------------------


def test_the_combined_state_is_paced_like_any_automation():
    many = entities(room={f"light.l{n}": ON for n in range(12)})
    steps = plan_steps(latest_state([many]), merged=True)
    assert [len(step.calls) for step in steps] == [5, 5, 2]


def test_a_room_whose_scheduling_is_off_is_skipped():
    combined = latest_state(
        [
            entities(kitchen={"light.k": ON}),
            {"guest_room": {"scene": "scene.guest"}},
            entities(guest_room={"light.g": ON}),
        ]
    )
    steps = plan_steps(combined, merged=True, rooms_off={"guest_room"})
    assert [c.entity_id for s in steps for c in s.calls] == ["light.k"]


def test_a_schedules_own_room_still_cannot_hold_both():
    both = {"room": {"scene": "scene.x", "entities": {"light.a": ON}}}
    with pytest.raises(ScheduleError):
        plan_steps(both)
    assert len(plan_steps(both, merged=True)) == 2
