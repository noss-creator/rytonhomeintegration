"""Day party mode: After day seuda runs later in the day party rooms.

Runs without Home Assistant. Uses the pretend house of test_day_list, with
three rooms set alike. Shabbos here also has After day seuda at 14:00 and
Shalosh seudos at 17:00; Sunset and Night are as in that house.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from engine.changes import ChangeError, check_change

from .test_changes import change
from .test_day_list import FRIDAY, TUESDAY, at, build, make_schedule

SHABBOS = FRIDAY + timedelta(days=1)
SCENE = {"scene": "scene.shabbos"}
ALL = ["den", "hall", "study"]


def house(rooms=("hall", "study"), shalosh_seudos=("den",)):
    """Shabbos with After day seuda in every room, and Shalosh seudos in some."""
    schedule = make_schedule()
    schedule["days"]["shabbos"]["automations"] += [
        {
            "id": "after_day_seuda",
            "time": {"kind": "clock", "at": "14:00"},
            "rooms": {room: dict(SCENE) for room in ALL},
        },
        {
            "id": "shalosh_seudos",
            "time": {"kind": "clock", "at": "17:00"},
            "rooms": {room: dict(SCENE) for room in shalosh_seudos},
        },
    ]
    schedule["settings"]["day_party"] = {"at": "16:00", "rooms": list(rooms)}
    return schedule


def party(clock="16:00", day=SHABBOS, **more):
    return change("day_party", first=day, at=clock, **more)


def of(day_list, *ids):
    return [(a.id, a.time, sorted(a.rooms)) for a in day_list.automations if a.id in ids]


BOTH = ("after_day_seuda", "after_day_seuda#party")


def test_the_party_rooms_have_after_day_seuda_at_the_time_the_client_entered():
    got = build(house(), SHABBOS, changes=[party("16:00")])
    assert of(got, *BOTH) == [
        # The house's keeps its time and leaves the party rooms as they are.
        ("after_day_seuda", at(SHABBOS, "14:00"), ["den"]),
        ("after_day_seuda#party", at(SHABBOS, "16:00"), ["hall", "study"]),
    ]
    late = next(a for a in got.automations if a.id == "after_day_seuda#party")
    assert late.rooms == {"hall": SCENE, "study": SCENE}
    assert late.name == "After day seuda, party rooms"
    assert got.skipped_changes == ()


def test_everything_else_in_the_day_is_as_it_was():
    plain = build(house(), SHABBOS)
    got = build(house(), SHABBOS, changes=[party("16:00")])
    others = lambda day_list: [a for a in day_list.automations if a.id not in BOTH]  # noqa: E731
    assert others(got) == others(plain)


def test_with_no_day_party_the_day_is_as_it_was():
    assert of(build(house(), SHABBOS), *BOTH) == [("after_day_seuda", at(SHABBOS, "14:00"), ALL)]


def test_a_house_with_no_day_party_rooms_runs_as_usual():
    for schedule in (house(rooms=()), make_schedule()):
        if "after_day_seuda" not in [a["id"] for a in schedule["days"]["shabbos"]["automations"]]:
            schedule["days"]["shabbos"]["automations"] += house()["days"]["shabbos"]["automations"][-2:]
        got = build(schedule, SHABBOS, changes=[party("16:00")])
        assert of(got, *BOTH) == [("after_day_seuda", at(SHABBOS, "14:00"), ALL)]


@pytest.mark.parametrize("clock", ["14:00", "13:00", "08:00"])
def test_a_party_time_that_is_not_later_changes_nothing(clock):
    got = build(house(), SHABBOS, changes=[party(clock)])
    assert of(got, *BOTH) == [("after_day_seuda", at(SHABBOS, "14:00"), ALL)]


def test_a_room_another_automation_sets_before_the_party_ends_is_not_set_again():
    # Shalosh seudos at 17:00 sets the hall. The party ends at 18:00.
    schedule = house(shalosh_seudos=("hall",))
    got = build(schedule, SHABBOS, changes=[party("18:00")])
    assert of(got, *BOTH, "shalosh_seudos") == [
        ("after_day_seuda", at(SHABBOS, "14:00"), ["den"]),
        ("shalosh_seudos", at(SHABBOS, "17:00"), ["hall"]),
        ("after_day_seuda#party", at(SHABBOS, "18:00"), ["study"]),
    ]


def test_where_every_party_room_was_set_in_between_there_is_no_late_entry():
    schedule = house(shalosh_seudos=("hall", "study"))
    got = build(schedule, SHABBOS, changes=[party("18:00")])
    assert of(got, *BOTH) == [("after_day_seuda", at(SHABBOS, "14:00"), ["den"])]


def test_a_date_with_no_after_day_seuda_skips_the_change():
    asked = party("16:00", day=TUESDAY)
    got = build(house(), TUESDAY, changes=[asked])
    assert got.automations == build(house(), TUESDAY).automations
    assert got.skipped_changes == ((asked["id"], "This day has no such automation"),)


def test_the_latest_of_two_day_parties_gives_the_time():
    first = party("15:00", made="2027-06-01T10:00:00+00:00")
    second = party("16:30", made="2027-06-02T10:00:00+00:00")
    got = build(house(), SHABBOS, changes=[first, second])
    assert of(got, "after_day_seuda#party")[0][1] == at(SHABBOS, "16:30")


def test_a_day_party_is_only_on_its_date():
    got = build(house(), SHABBOS + timedelta(days=7), changes=[party("16:00")])
    assert of(got, *BOTH) == [("after_day_seuda", at(SHABBOS + timedelta(days=7), "14:00"), ALL)]


def test_a_day_party_change_is_checked():
    check_change(party("16:00"))
    for bad in ("late", "25:00", 16, ""):
        with pytest.raises(ChangeError):
            check_change(party(bad))
    with pytest.raises(ChangeError):
        check_change(change("day_party", first=SHABBOS))
    with pytest.raises(ChangeError):
        check_change(change("day_party", first=SHABBOS, last=SHABBOS + timedelta(days=1), at="16:00"))
