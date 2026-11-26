"""An entity set to cycle: on so many minutes, off so many, until an end.

Runs without Home Assistant.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from engine.actions import Cycle, cycle_moments, cycle_of, latest_state, plan_steps
from engine.describe import describe_by_room
from engine.due import split_due
from engine.scenes import schedule_scenes
from engine.time_resolver import ScheduleError

from .test_day_list import TUESDAY, TZ, at, build, make_schedule

FAN = "switch.bathroom_fan"


def cycle(on=5, off=5, **end):
    return {"cycle": {"on_minutes": on, "off_minutes": off, **end}}


def start(clock="20:00"):
    return at(TUESDAY, clock)


# --- the moments of a cycle ------------------------------------------------


def test_a_cycle_switches_off_and_on_in_turn_and_ends_off():
    moments = cycle_moments(Cycle(5, 10, for_minutes=30), start())
    assert moments == [
        (at(TUESDAY, "20:05"), "off"),
        (at(TUESDAY, "20:15"), "on"),
        (at(TUESDAY, "20:20"), "off"),
        (at(TUESDAY, "20:30"), "off"),
    ]


def test_a_cycle_that_ends_while_on_is_switched_off_at_its_end():
    moments = cycle_moments(Cycle(10, 5, for_minutes=20), start())
    assert moments == [
        (at(TUESDAY, "20:10"), "off"),
        (at(TUESDAY, "20:15"), "on"),
        (at(TUESDAY, "20:20"), "off"),
    ]


def test_a_cycle_shorter_than_its_first_on_time_is_on_until_its_end():
    assert cycle_moments(Cycle(30, 5, for_minutes=10), start()) == [
        (at(TUESDAY, "20:10"), "off")
    ]


def test_a_cycle_can_end_at_a_clock_time():
    moments = cycle_moments(Cycle(20, 20, until=time(21, 0)), start())
    assert moments[-1] == (at(TUESDAY, "21:00"), "off")
    assert [state for _, state in moments] == ["off", "on", "off"]


def test_a_clock_time_not_after_the_start_is_on_the_next_day():
    moments = cycle_moments(Cycle(60, 60, until=time(1, 0)), start("23:00"))
    assert moments == [
        (at(TUESDAY, "00:00", 1), "off"),
        (at(TUESDAY, "01:00", 1), "off"),
    ]
    whole_day = cycle_moments(Cycle(600, 600, until=time(20, 0)), start())
    assert whole_day[-1] == (at(TUESDAY, "20:00", 1), "off")


def test_the_moments_never_pass_the_end_and_always_alternate():
    for on in (1, 3, 7, 45):
        for off in (1, 4, 30):
            for length in (1, 2, 9, 60, 1440):
                moments = cycle_moments(Cycle(on, off, for_minutes=length), start())
                end = start() + timedelta(minutes=length)
                assert moments[-1] == (end, "off")
                assert all(when <= end for when, _ in moments)
                assert [when for when, _ in moments] == sorted(when for when, _ in moments)
                states = [state for _, state in moments[:-1]]
                assert states == ["off", "on"] * (len(states) // 2) + ["off"] * (len(states) % 2)


# --- what the schedule may hold ------------------------------------------------


def test_a_cycle_is_read_from_an_action():
    assert cycle_of(FAN, cycle(for_minutes=60)) == Cycle(5, 5, for_minutes=60)
    assert cycle_of(FAN, cycle(until="22:30")) == Cycle(5, 5, until=time(22, 30))
    assert cycle_of(FAN, {"state": "on"}) is None


@pytest.mark.parametrize(
    "action",
    [
        {"cycle": "often"},
        {"cycle": {"on_minutes": 5, "off_minutes": 5}},
        cycle(for_minutes=60, until="22:00"),
        cycle(on=0, for_minutes=60),
        cycle(off=2.5, for_minutes=60),
        cycle(on=True, for_minutes=60),
        cycle(for_minutes=1441),
        cycle(until="late"),
        cycle(until=22),
        {**cycle(for_minutes=60), "state": "on"},
    ],
)
def test_a_cycle_that_is_not_understood_is_refused(action):
    with pytest.raises(ScheduleError):
        cycle_of(FAN, action)


@pytest.mark.parametrize("entity_id", ["cover.shade", "select.mode", "scene.evening"])
def test_only_something_switched_on_and_off_can_cycle(entity_id):
    with pytest.raises(ScheduleError):
        cycle_of(entity_id, cycle(for_minutes=60))


def test_a_scene_made_in_the_form_cannot_hold_a_cycle():
    schedule = {
        "scenes": [
            {"id": "ryton_fan", "name": "Fan", "room": "bath", "entities": {FAN: cycle(for_minutes=60)}}
        ]
    }
    with pytest.raises(ScheduleError):
        schedule_scenes(schedule)


def test_the_automation_itself_switches_the_entity_on():
    steps = plan_steps({"bath": {"entities": {FAN: cycle(for_minutes=60)}}})
    (call,) = steps[0].calls
    assert (call.entity_id, call.service) == (FAN, "turn_on")


def test_a_cycle_is_said_in_words():
    rooms = {"bath": {"entities": {FAN: cycle(5, 10, until="22:00")}}}
    assert describe_by_room(rooms, {}, lambda entity_id: "Fan") == [
        ("bath", "Fan cycles on 5 min, off 10 min, until 22:00")
    ]


# --- in the day's list ---------------------------------------------------------


def _schedule_with_cycle(action=None):
    schedule = make_schedule()
    sunset = schedule["days"]["weekday"]["automations"][1]
    sunset["rooms"] = {"bath": {"entities": {FAN: action or cycle(10, 20, for_minutes=60)}}}
    return schedule


def test_every_moment_of_a_cycle_is_fixed_in_the_days_list():
    got = build(_schedule_with_cycle(), TUESDAY)
    # Sunset is at 18:00 in this pretend house.
    assert [(a.id, a.time) for a in got.cycle_steps] == [
        (f"sunset#{FAN}#1", at(TUESDAY, "18:10")),
        (f"sunset#{FAN}#2", at(TUESDAY, "18:30")),
        (f"sunset#{FAN}#3", at(TUESDAY, "18:40")),
        (f"sunset#{FAN}#4", at(TUESDAY, "19:00")),
    ]
    assert [a.rooms["bath"]["entities"][FAN]["state"] for a in got.cycle_steps] == [
        "off", "on", "off", "off",
    ]
    assert all(a.part_of == "sunset" for a in got.cycle_steps)


def test_the_cycles_moments_are_not_among_the_named_automations():
    got = build(_schedule_with_cycle(), TUESDAY)
    assert [a.id for a in got.automations] == ["morning", "sunset", "night"]
    assert len(got.moments) == 7
    assert [a.time for a in got.moments] == sorted(a.time for a in got.moments)


def test_a_day_with_no_cycle_has_no_extra_moments():
    got = build(make_schedule(), TUESDAY)
    assert got.cycle_steps == ()
    assert got.moments == got.automations


def test_a_cycle_follows_its_automations_time_when_the_client_changes_it():
    change = {
        "id": "c1",
        "made_at": "2027-06-14T10:00:00+00:00",
        "from": TUESDAY.isoformat(),
        "until": TUESDAY.isoformat(),
        "days": "all",
        "kind": "time",
        "automation": "sunset",
        "shift_minutes": 30,
    }
    got = build(_schedule_with_cycle(), TUESDAY, changes=[change])
    assert got.cycle_steps[0].time == at(TUESDAY, "18:40")
    assert got.cycle_steps[-1].time == at(TUESDAY, "19:30")


def test_a_cycle_that_is_not_understood_stops_the_days_list():
    with pytest.raises(ScheduleError):
        build(_schedule_with_cycle(cycle(for_minutes=0)), TUESDAY)


def test_the_cycles_moments_come_due_like_automations():
    got = build(_schedule_with_cycle(), TUESDAY)
    missed, upcoming = split_due([got], at(TUESDAY, "17:00"), at(TUESDAY, "18:35"))
    assert [a.id for a in missed] == ["sunset", f"sunset#{FAN}#1", f"sunset#{FAN}#2"]
    assert f"sunset#{FAN}#3" in [a.id for a in upcoming]


def test_after_a_restart_the_entity_is_brought_to_where_the_cycle_has_it():
    got = build(_schedule_with_cycle(), TUESDAY)

    def state_at(clock):
        missed, _ = split_due([got], at(TUESDAY, "17:00"), at(TUESDAY, clock))
        rooms = latest_state([a.rooms for a in missed])
        (call,) = plan_steps(rooms, merged=True)[0].calls
        return call.service

    assert state_at("18:05") == "turn_on"
    assert state_at("18:15") == "turn_off"
    assert state_at("18:35") == "turn_on"
    assert state_at("19:30") == "turn_off"
