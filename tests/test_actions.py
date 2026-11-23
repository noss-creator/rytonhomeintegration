"""Turning an automation's rooms into paced service calls.

Runs without Home Assistant. Nothing is switched: the tests look at what the
engine would ask for.
"""

from __future__ import annotations

import pytest

from engine.actions import Expected, plan_steps
from engine.time_resolver import ScheduleError

ON, OFF = {"state": "on"}, {"state": "off"}


def calls(steps):
    return [call for step in steps for call in step.calls]


def one(entity_id, action, **kwargs):
    [call] = calls(plan_steps({"room": {"entities": {entity_id: action}}}, **kwargs))
    return call


# --- what each kind of action asks for -------------------------------------


def test_light_on_and_off():
    on = one("light.kitchen", ON)
    off = one("light.kitchen", OFF)
    assert (on.domain, on.service, on.data) == ("light", "turn_on", {})
    assert (off.domain, off.service, off.data) == ("light", "turn_off", {})
    assert on.expected.is_met("on", {}) and not on.expected.is_met("off", {})
    assert off.expected.is_met("off", {}) and not off.expected.is_met("on", {})


def test_switch_on_and_off():
    assert one("switch.hot_plate", ON).service == "turn_on"
    assert one("switch.hot_plate", OFF).service == "turn_off"
    assert one("switch.hot_plate", ON).domain == "switch"


def test_dimmed_light():
    call = one("light.kitchen", {"state": "on", "brightness_pct": 40})
    assert call.data == {"brightness_pct": 40}
    assert call.expected.is_met("on", {"brightness": 102})
    assert call.expected.is_met("on", {"brightness": 104})  # close enough
    assert not call.expected.is_met("on", {"brightness": 255})
    assert not call.expected.is_met("on", {})
    assert not call.expected.is_met("off", {"brightness": 102})


def test_shade_open_closed_and_position():
    opened = one("cover.shade", {"state": "open"})
    closed = one("cover.shade", {"state": "closed"})
    half = one("cover.shade", {"position": 50})
    assert opened.service == "open_cover" and opened.expected.is_met("open", {})
    assert closed.service == "close_cover" and closed.expected.is_met("closed", {})
    assert (half.service, half.data) == ("set_cover_position", {"position": 50})
    assert half.expected.is_met("open", {"current_position": 50})
    assert half.expected.is_met("open", {"current_position": 51})
    assert not half.expected.is_met("open", {"current_position": 80})


def test_mode_list():
    call = one("select.freezer_mode", {"option": "Sabbath"})
    assert (call.domain, call.service, call.data) == (
        "select", "select_option", {"option": "Sabbath"},
    )
    assert call.expected.is_met("Sabbath", {})
    assert not call.expected.is_met("Normal", {})


def test_scene_is_turned_on_and_cannot_be_checked():
    [call] = calls(plan_steps({"living_room": {"scene": "scene.shabbos"}}))
    assert (call.domain, call.service, call.entity_id) == (
        "scene", "turn_on", "scene.shabbos",
    )
    assert call.expected is None


# --- fades -----------------------------------------------------------------


def test_fade_applies_to_lights_only():
    rooms = {"room": {"entities": {"light.a": ON, "light.b": OFF, "switch.c": ON}}}
    a, b, c = calls(plan_steps(rooms, fade_seconds=30))
    assert a.data == {"transition": 30}
    assert b.data == {"transition": 30}
    assert c.data == {}


def test_an_entity_can_have_its_own_fade():
    rooms = {
        "room": {
            "entities": {
                "light.a": {"state": "on", "fade_seconds": 5},
                "light.b": {"state": "on", "fade_seconds": 0},
                "light.c": ON,
            }
        }
    }
    a, b, c = calls(plan_steps(rooms, fade_seconds=30))
    assert a.data == {"transition": 5}
    assert b.data == {}
    assert c.data == {"transition": 30}


# --- order and pacing ------------------------------------------------------


def _twelve_lights():
    return {f"light.l{n}": ON for n in range(12)}


def test_entities_go_in_groups_of_five_with_a_pause():
    steps = plan_steps({"room": {"entities": _twelve_lights()}})
    assert [len(step.calls) for step in steps] == [5, 5, 2]
    assert [step.pause_seconds for step in steps] == [1, 1, 1]
    assert [c.entity_id for c in calls(steps)] == [f"light.l{n}" for n in range(12)]


def test_pacing_follows_the_houses_settings():
    steps = plan_steps(
        {"room": {"entities": _twelve_lights()}}, group_size=4, pause_seconds=2.5
    )
    assert [len(step.calls) for step in steps] == [4, 4, 4]
    assert {step.pause_seconds for step in steps} == {2.5}


def test_scenes_go_first_one_at_a_time_then_entities():
    rooms = {
        "kitchen": {"entities": {"light.k1": ON, "light.k2": ON}},
        "living_room": {"scene": "scene.living"},
        "dining_room": {"entities": {"light.d1": ON}},
        "bedroom": {"scene": "scene.bedroom"},
    }
    steps = plan_steps(rooms)
    assert [[c.entity_id for c in step.calls] for step in steps] == [
        ["scene.living"],
        ["scene.bedroom"],
        ["light.k1", "light.k2", "light.d1"],
    ]


def test_a_group_can_span_rooms_and_each_call_knows_its_room():
    rooms = {
        "kitchen": {"entities": {f"light.k{n}": ON for n in range(3)}},
        "dining_room": {"entities": {f"light.d{n}": ON for n in range(3)}},
    }
    steps = plan_steps(rooms)
    assert [len(step.calls) for step in steps] == [5, 1]
    assert [c.room for c in calls(steps)] == ["kitchen"] * 3 + ["dining_room"] * 3


def test_an_automation_that_does_nothing_has_no_steps():
    assert plan_steps({}) == []


# --- rooms switched off ----------------------------------------------------


def test_a_room_whose_scheduling_is_off_is_skipped():
    rooms = {
        "kitchen": {"entities": {"light.k1": ON}},
        "guest_room": {"entities": {"light.g1": ON}},
        "study": {"scene": "scene.study"},
    }
    steps = plan_steps(rooms, rooms_off={"guest_room", "study"})
    assert [c.entity_id for c in calls(steps)] == ["light.k1"]


# --- schedules the engine must refuse --------------------------------------


@pytest.mark.parametrize(
    "entity_id,action",
    [
        ("light.a", {"state": "open"}),
        ("light.a", {"state": "dim"}),
        ("light.a", {}),
        ("light.a", "on"),
        ("light.a", {"position": 50}),
        ("light.a", {"option": "Sabbath"}),
        ("light.a", {"state": "on", "brightness_pct": 0}),
        ("light.a", {"state": "on", "brightness_pct": 140}),
        ("light.a", {"state": "on", "brightness_pct": "half"}),
        ("light.a", {"state": "off", "brightness_pct": 40}),
        ("switch.a", {"state": "on", "brightness_pct": 40}),
        ("cover.a", {"state": "on"}),
        ("cover.a", {"position": 150}),
        ("cover.a", {"state": "open", "position": 50}),
        ("select.a", {"state": "on"}),
        ("scene.a", {"state": "on"}),
    ],
)
def test_actions_that_do_not_fit_are_refused(entity_id, action):
    with pytest.raises(ScheduleError):
        plan_steps({"room": {"entities": {entity_id: action}}})


@pytest.mark.parametrize(
    "room",
    [
        {"entities": {"light.a": ON}, "scene": "scene.x"},
        {},
        {"scene": "light.a"},
        "scene.x",
    ],
)
def test_rooms_that_are_not_understood_are_refused(room):
    with pytest.raises(ScheduleError):
        plan_steps({"room": room})


def test_bad_group_size_is_refused():
    with pytest.raises(ScheduleError):
        plan_steps({"room": {"entities": {"light.a": ON}}}, group_size=0)


# --- the test house's own schedule -----------------------------------------


def test_every_automation_in_the_test_house_schedule_can_be_planned():
    import json
    from pathlib import Path

    path = Path(__file__).parents[2] / "test-house" / "ryton_schedule.json"
    if not path.exists():
        pytest.skip("the test house schedule is not on this computer")
    schedule = json.loads(path.read_text(encoding="utf-8"))
    automations = [
        a for day in schedule["days"].values() for a in day["automations"]
    ] + schedule["alongside"]
    planned = 0
    for automation in automations:
        for step in plan_steps(automation["rooms"]):
            assert 1 <= len(step.calls) <= 5
            planned += len(step.calls)
    assert planned > 0


def test_expected_with_no_conditions_is_always_met():
    assert Expected().is_met(None, {})
