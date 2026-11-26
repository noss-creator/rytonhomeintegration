"""A room with its own Night, a child's earlier or an adult's later, and the meals with their own automation.

Runs without Home Assistant. Uses the pretend house of test_day_list: every
day has Morning at 07:00, Sunset at 18:00 and Night at 23:00, each turning
on one scene in the hall. The rollover is 04:00.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from engine.away import meals_on
from engine.changes import check_change
from engine.day_list import check_room_night, check_room_time
from engine.time_resolver import ScheduleError

from .test_day_list import FRIDAY, SOURCE, TUESDAY, at, build, make_schedule

NIGHT_BODY = {"scene": "scene.weekday"}


def rooms_at(day_list):
    return [(a.id, a.time, sorted(a.rooms)) for a in day_list.automations]


def child(how, **more):
    return build(make_schedule(), TUESDAY, room_night={"hall": how}, **more)


def test_with_no_child_rooms_the_list_is_as_it_was():
    assert build(make_schedule(), TUESDAY, room_night={}) == build(make_schedule(), TUESDAY)


def test_a_childs_room_has_its_night_so_many_minutes_earlier():
    got = child({"minutes": 180})
    assert rooms_at(got) == [
        ("morning", at(TUESDAY, "07:00"), ["hall"]),
        ("sunset", at(TUESDAY, "18:00"), ["hall"]),
        ("night#own:hall", at(TUESDAY, "20:00"), ["hall"]),
        # The house's Night no longer runs in that room.
        ("night", at(TUESDAY, "23:00"), []),
    ]
    own = next(a for a in got.automations if a.id == "night#own:hall")
    night = next(a for a in build(make_schedule(), TUESDAY).automations if a.id == "night")
    assert own.rooms == {"hall": night.rooms["hall"]}
    assert got.night_usual == at(TUESDAY, "23:00")


def test_automations_between_the_childs_night_and_the_houses_skip_the_room():
    got = child({"minutes": 360})
    assert rooms_at(got) == [
        ("morning", at(TUESDAY, "07:00"), ["hall"]),
        ("night#own:hall", at(TUESDAY, "17:00"), ["hall"]),
        ("sunset", at(TUESDAY, "18:00"), []),
        ("night", at(TUESDAY, "23:00"), []),
    ]


def test_a_childs_night_can_be_a_clock_time():
    got = child({"at": "19:30"})
    assert ("night#own:hall", at(TUESDAY, "19:30"), ["hall"]) in rooms_at(got)


@pytest.mark.parametrize("how", [{"at": "23:00"}, {"at": "23:30"}, {"at": "03:00"}])
def test_a_clock_time_that_is_not_before_night_changes_nothing(how):
    # 03:00 is after midnight, at the end of that night: later than Night.
    assert rooms_at(child(how)) == rooms_at(build(make_schedule(), TUESDAY))


def test_a_room_night_does_not_set_has_no_night_of_its_own():
    got = build(make_schedule(), TUESDAY, room_night={"attic": {"minutes": 60}})
    assert rooms_at(got) == rooms_at(build(make_schedule(), TUESDAY))


def test_a_time_change_to_night_moves_the_childs_night_with_it():
    change = {
        "id": "c1",
        "made_at": "2027-06-01T10:00:00+00:00",
        "from": TUESDAY.isoformat(),
        "until": TUESDAY.isoformat(),
        "days": "all",
        "kind": "time",
        "automation": "night",
        "time": {"kind": "clock", "at": "22:00"},
    }
    got = child({"minutes": 60}, changes=[change])
    assert ("night#own:hall", at(TUESDAY, "21:00"), ["hall"]) in rooms_at(got)


def test_a_childs_night_setting_is_checked():
    check_room_night({"minutes": 90})
    check_room_night({"at": "19:30"})
    check_room_night({"mode": "child", "minutes": 90})
    check_room_night({"mode": "adult", "at": "01:30"})
    for bad in ({}, {"mode": "adult"}, {"mode": "teen", "minutes": 5}, {"minutes": 5, "until": "x"}, {"minutes": 0}, {"minutes": 721}, {"minutes": 1.5}, {"at": "7pm"}, {"minutes": 5, "at": "19:00"}, "early"):
        with pytest.raises(ScheduleError):
            check_room_night(bad)


def test_a_setting_that_is_not_understood_changes_nothing():
    assert rooms_at(child({"minutes": "many"})) == rooms_at(build(make_schedule(), TUESDAY))


# --- an adult's room: the exact opposite ---------------------------------------


def adult(how, **more):
    return build(make_schedule(), TUESDAY, room_night={"hall": {"mode": "adult", **how}}, **more)


WEDNESDAY = TUESDAY + timedelta(days=1)
USUAL = [
    ("morning", at(TUESDAY, "07:00"), ["hall"]),
    ("sunset", at(TUESDAY, "18:00"), ["hall"]),
]


def test_an_adults_room_has_its_night_so_many_minutes_later():
    got = adult({"minutes": 90})
    assert rooms_at(got) == [
        *USUAL,
        # The house's Night leaves the room as it is.
        ("night", at(TUESDAY, "23:00"), []),
        ("night#own:hall", at(WEDNESDAY, "00:30"), ["hall"]),
    ]
    own = got.automations[-1]
    night = next(a for a in build(make_schedule(), TUESDAY).automations if a.id == "night")
    assert own.rooms == {"hall": night.rooms["hall"]}
    assert own.name == "Night, adult's room"


def test_an_adults_night_can_be_a_clock_time_after_midnight():
    assert rooms_at(adult({"at": "01:15"}))[-1] == ("night#own:hall", at(WEDNESDAY, "01:15"), ["hall"])
    assert rooms_at(adult({"at": "23:45"}))[-1] == ("night#own:hall", at(TUESDAY, "23:45"), ["hall"])


@pytest.mark.parametrize("how", [{"at": "23:00"}, {"at": "22:00"}, {"at": "04:00"}, {"at": "05:00"}, {"minutes": 300}])
def test_an_adults_night_not_between_night_and_the_days_end_changes_nothing(how):
    # The day starts over at 04:00: 23:00 and five hours is 04:00.
    assert rooms_at(adult(how)) == rooms_at(build(make_schedule(), TUESDAY))


def test_an_adults_night_just_before_the_day_starts_over():
    assert rooms_at(adult({"minutes": 299}))[-1] == ("night#own:hall", at(WEDNESDAY, "03:59"), ["hall"])


def test_a_child_and_an_adult_in_two_rooms():
    schedule = make_schedule()
    for entry in schedule["days"].values():
        for automation in entry.get("automations", ()):
            if "hall" in automation.get("rooms", {}):
                automation["rooms"]["study"] = automation["rooms"]["hall"]
    got = build(
        schedule, TUESDAY,
        room_night={"hall": {"mode": "child", "minutes": 60}, "study": {"mode": "adult", "minutes": 60}},
    )
    assert rooms_at(got) == [
        ("morning", at(TUESDAY, "07:00"), ["hall", "study"]),
        ("sunset", at(TUESDAY, "18:00"), ["hall", "study"]),
        ("night#own:hall", at(TUESDAY, "22:00"), ["hall"]),
        ("night", at(TUESDAY, "23:00"), []),
        ("night#own:study", at(WEDNESDAY, "00:00"), ["study"]),
    ]


# --- a Night time the schedule gives a room -------------------------------------


def timed(room_time, room_night=None, **more):
    """The pretend house with the hall's Night at its own time on a weekday."""
    schedule = make_schedule()
    night = next(a for a in schedule["days"]["weekday"]["automations"] if a["id"] == "night")
    night["room_times"] = {"hall": room_time}
    return build(schedule, TUESDAY, room_night={"hall": room_night} if room_night else None, **more)


def test_the_schedule_can_put_a_rooms_night_earlier():
    got = timed({"minutes": -120})
    assert rooms_at(got) == [
        ("morning", at(TUESDAY, "07:00"), ["hall"]),
        ("sunset", at(TUESDAY, "18:00"), ["hall"]),
        ("night#own:hall", at(TUESDAY, "21:00"), ["hall"]),
        ("night", at(TUESDAY, "23:00"), []),
    ]
    assert got.night_rooms == {"hall": at(TUESDAY, "21:00")}
    assert next(a for a in got.automations if a.id == "night#own:hall").name == "Night, the room's own time"


def test_an_earlier_night_from_the_schedule_makes_automations_in_between_skip_the_room():
    assert rooms_at(timed({"at": "17:30"}))[1:3] == [
        ("night#own:hall", at(TUESDAY, "17:30"), ["hall"]),
        ("sunset", at(TUESDAY, "18:00"), []),
    ]


def test_the_schedule_can_put_a_rooms_night_later():
    assert rooms_at(timed({"minutes": 45}))[-2:] == [
        ("night", at(TUESDAY, "23:00"), []),
        ("night#own:hall", at(TUESDAY, "23:45"), ["hall"]),
    ]
    assert rooms_at(timed({"at": "00:30"}))[-1] == ("night#own:hall", at(WEDNESDAY, "00:30"), ["hall"])


def test_child_and_adult_mode_are_counted_from_the_rooms_own_time():
    child_from_earlier = timed({"minutes": -120}, {"mode": "child", "minutes": 30})
    assert ("night#own:hall", at(TUESDAY, "20:30"), ["hall"]) in rooms_at(child_from_earlier)
    assert child_from_earlier.night_rooms == {"hall": at(TUESDAY, "21:00")}
    own = next(a for a in child_from_earlier.automations if a.id == "night#own:hall")
    assert own.name == "Night, child's room"

    adult_from_earlier = timed({"minutes": -120}, {"mode": "adult", "minutes": 30})
    assert ("night#own:hall", at(TUESDAY, "21:30"), ["hall"]) in rooms_at(adult_from_earlier)

    adult_from_later = timed({"minutes": 45}, {"mode": "adult", "minutes": 30})
    assert rooms_at(adult_from_later)[-1] == ("night#own:hall", at(WEDNESDAY, "00:15"), ["hall"])

    # An adult's two and a half hours from 21:00 lands after the house's Night.
    crossing = timed({"minutes": -120}, {"mode": "adult", "minutes": 150})
    assert rooms_at(crossing)[-2:] == [
        ("night", at(TUESDAY, "23:00"), []),
        ("night#own:hall", at(TUESDAY, "23:30"), ["hall"]),
    ]


def test_the_clients_clock_time_wins_over_the_schedules_time():
    got = timed({"minutes": -120}, {"mode": "child", "at": "19:00"})
    assert ("night#own:hall", at(TUESDAY, "19:00"), ["hall"]) in rooms_at(got)


def test_a_clients_time_that_does_not_fit_leaves_the_schedules_time():
    # A child's clock time after Night is not a child's: the room keeps the schedule's time.
    assert rooms_at(timed({"minutes": -120}, {"mode": "child", "at": "23:30"})) == rooms_at(
        timed({"minutes": -120})
    )
    # Landing exactly on the house's Night does not fit either.
    assert rooms_at(timed({"minutes": -120}, {"mode": "adult", "minutes": 120})) == rooms_at(
        timed({"minutes": -120})
    )


@pytest.mark.parametrize(
    "room_time",
    [{"minutes": 0}, {"minutes": 300}, {"minutes": -1000}, {"at": "23:00"}, {"at": "nine"}, {"minutes": 5, "at": "21:00"}, "early", None],
)
def test_a_schedules_room_time_that_does_not_fit_changes_nothing(room_time):
    got = timed(room_time)
    assert rooms_at(got) == rooms_at(build(make_schedule(), TUESDAY))
    assert got.night_rooms == {}


def test_a_room_time_on_one_day_is_not_on_another():
    schedule = make_schedule()
    night = next(a for a in schedule["days"]["weekday"]["automations"] if a["id"] == "night")
    night["room_times"] = {"hall": {"minutes": -60}}
    assert not any(a.id.startswith("night#own:") for a in build(schedule, FRIDAY).automations)


def test_a_room_time_is_checked():
    check_room_time({"minutes": -90})
    check_room_time({"minutes": 30})
    check_room_time({"at": "21:15"})
    for bad in ({}, {"minutes": 0}, {"minutes": 721}, {"minutes": 1.5}, {"at": "9pm"}, {"at": 9}, {"mode": "child", "minutes": 5}):
        with pytest.raises(ScheduleError):
            check_room_time(bad)


# --- meals with an automation of their own -------------------------------------

EREV_YOM_KIPPUR = date(2027, 10, 10)


def test_a_meal_with_its_own_automation_is_listed_where_the_date_has_it():
    schedule = make_schedule()
    assert meals_on(schedule, EREV_YOM_KIPPUR, SOURCE, ["morning", "first_seuda", "seuda_hamafsekes"]) == [
        ("first_seuda", "First seuda"),
        ("seuda_hamafsekes", "Seuda hamafsekes"),
    ]
    assert meals_on(schedule, EREV_YOM_KIPPUR, SOURCE, ["morning"]) == []


def test_the_seuda_before_tisha_bav_is_not_a_meal_to_be_away_for():
    erev_tisha_bav = date(2027, 8, 11)
    assert meals_on(make_schedule(), erev_tisha_bav, SOURCE, ["morning", "seuda_hamafsekes"]) == []


def test_a_seuda_is_named_after_its_day():
    purim = date(2027, 3, 23)
    assert meals_on(make_schedule(), purim, SOURCE, ["seuda"]) == [("seuda", "Purim seuda")]


def test_a_days_own_meal_comes_before_that_nights_meal():
    hoshana_rabba = date(2027, 10, 22)
    assert meals_on(make_schedule(), hoshana_rabba, SOURCE, ["seuda", "erev_yom_tov"]) == [
        ("seuda", "Hoshana rabba seuda"),
        # Shmini Atzeres is on Shabbos that year.
        ("night", "Shabbos night"),
    ]


def test_a_change_can_name_these_meals():
    for meal in ("first_seuda", "seuda_hamafsekes", "seuda"):
        check_change(
            {
                "id": "m1",
                "made_at": "2027-06-01T10:00:00+00:00",
                "from": "2027-10-10",
                "until": "2027-10-10",
                "days": "all",
                "kind": "meal_out",
                "meal": meal,
            }
        )
