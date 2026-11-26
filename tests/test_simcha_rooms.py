"""Simcha mode for the rooms the schedule names, at the time the client enters.

Runs without Home Assistant. Uses the pretend house of test_day_list: every
day has Morning at 07:00, Sunset at 18:00 and Night at 23:00, each turning
on one scene in the hall. The schedule's own simcha time is 01:00. Here the
study and the den are set like the hall.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from engine.changes import ChangeError, check_change

from .test_changes import change
from .test_day_list import TUESDAY, at, build, make_schedule

WEDNESDAY = TUESDAY + timedelta(days=1)


def house(rooms=("hall", "study")):
    """The pretend house with three rooms, of which ``rooms`` are simcha rooms."""
    schedule = make_schedule()
    for entry in schedule["days"].values():
        for automation in entry.get("automations", ()):
            if "hall" in automation.get("rooms", {}):
                automation["rooms"]["study"] = automation["rooms"]["hall"]
                automation["rooms"]["den"] = automation["rooms"]["hall"]
    schedule["settings"]["simcha"]["rooms"] = list(rooms)
    return schedule


def nights(day_list):
    return [(a.id, a.time, sorted(a.rooms)) for a in day_list.automations if a.id.startswith("night")]


def test_only_the_simcha_rooms_have_their_night_at_the_time_the_client_entered():
    got = build(house(), TUESDAY, changes=[change("simcha", at="00:30")])
    assert nights(got) == [
        # The house's Night keeps its time and leaves the simcha rooms as they are.
        ("night", at(TUESDAY, "23:00"), ["den"]),
        ("night#simcha", at(WEDNESDAY, "00:30"), ["hall", "study"]),
    ]
    late = got.automations[-1]
    usual = next(a for a in build(house(), TUESDAY).automations if a.id == "night")
    assert late.rooms == {room: usual.rooms[room] for room in ("hall", "study")}
    assert late.name == "Night, simcha rooms"
    assert got.skipped_changes == ()
    assert got.night_usual == at(TUESDAY, "23:00")


def test_with_no_time_from_the_client_the_schedules_simcha_time_is_used():
    got = build(house(), TUESDAY, changes=[change("simcha")])
    assert nights(got)[-1] == ("night#simcha", at(WEDNESDAY, "01:00"), ["hall", "study"])


def test_a_house_with_no_simcha_rooms_runs_as_usual():
    got = build(house(rooms=()), TUESDAY, changes=[change("simcha", at="00:30")])
    assert nights(got) == [("night", at(TUESDAY, "23:00"), ["den", "hall", "study"])]


def test_a_simcha_room_night_sets_nothing_in_is_left_out():
    got = build(house(rooms=("hall", "attic")), TUESDAY, changes=[change("simcha", at="00:30")])
    assert nights(got)[-1] == ("night#simcha", at(WEDNESDAY, "00:30"), ["hall"])


@pytest.mark.parametrize("clock", ["22:00", "23:00", "12:00"])
def test_a_simcha_time_that_is_not_later_than_night_changes_nothing(clock):
    got = build(house(), TUESDAY, changes=[change("simcha", at=clock)])
    assert nights(got) == [("night", at(TUESDAY, "23:00"), ["den", "hall", "study"])]


def test_a_simcha_time_before_the_day_starts_over_is_kept():
    got = build(house(), TUESDAY, changes=[change("simcha", at="03:59")])
    assert nights(got)[-1] == ("night#simcha", at(WEDNESDAY, "03:59"), ["hall", "study"])


def test_simcha_over_a_range_of_dates_is_on_each_night():
    simcha = change("simcha", first=TUESDAY, last=WEDNESDAY, at="00:30")
    for day in (TUESDAY, WEDNESDAY):
        got = build(house(), day, changes=[simcha])
        assert nights(got)[-1] == (
            "night#simcha", at(day + timedelta(days=1), "00:30"), ["hall", "study"],
        )
    after = WEDNESDAY + timedelta(days=1)
    assert [n[0] for n in nights(build(house(), after, changes=[simcha]))] == ["night"]


def test_the_latest_of_two_simcha_changes_gives_the_time():
    first = change("simcha", at="00:30", made="2027-06-01T10:00:00+00:00")
    second = change("simcha", at="02:00", made="2027-06-02T10:00:00+00:00")
    got = build(house(), TUESDAY, changes=[first, second])
    assert nights(got)[-1][1] == at(WEDNESDAY, "02:00")


def test_simcha_wins_over_a_rooms_own_night():
    schedule = house()
    night = next(a for a in schedule["days"]["weekday"]["automations"] if a["id"] == "night")
    night["room_times"] = {"study": {"minutes": -60}, "den": {"minutes": -30}}
    got = build(
        schedule, TUESDAY,
        changes=[change("simcha", at="00:30")],
        room_night={"hall": {"mode": "child", "minutes": 120}},
    )
    assert nights(got) == [
        # The den is no simcha room: it keeps its own time.
        ("night#own:den", at(TUESDAY, "22:30"), ["den"]),
        ("night", at(TUESDAY, "23:00"), []),
        ("night#simcha", at(WEDNESDAY, "00:30"), ["hall", "study"]),
    ]


def test_on_a_night_with_no_simcha_the_rooms_keep_their_own_night():
    got = build(house(), TUESDAY, room_night={"hall": {"mode": "child", "minutes": 120}})
    assert nights(got)[0] == ("night#own:hall", at(TUESDAY, "21:00"), ["hall"])


def test_a_schedule_from_before_simcha_rooms_moves_the_whole_house():
    got = build(make_schedule(), TUESDAY, changes=[change("simcha", at="00:30")])
    assert nights(got) == [("night", at(WEDNESDAY, "00:30"), ["hall"])]


def test_the_clients_simcha_time_is_checked():
    check_change(change("simcha"))
    check_change(change("simcha", at="00:30"))
    for bad in ("late", "25:00", 30, ""):
        with pytest.raises(ChangeError):
            check_change(change("simcha", at=bad))
