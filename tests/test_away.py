"""Away mode and away for a meal.

Runs without Home Assistant. Uses the pretend house of test_day_list: every
day has Morning at 07:00, Sunset at 18:00 and Night at 23:00, each turning
on one scene in the hall. The rollover is 04:00.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from engine.away import (
    Mode,
    away_changes,
    meals_on,
    mode_at,
    motzei_end,
    schedule_date,
    schedule_presets,
    switch_moments,
)
from engine.changes import ChangeError, check_change
from engine.day_list import check_schedule
from engine.preview import build_preview
from engine.time_resolver import ScheduleError

from .test_day_list import FRIDAY, SOURCE, TUESDAY, TZ, at, build, make_schedule

MONDAY = TUESDAY - timedelta(days=1)
HOUSE = {"hall": ["light.hall"], "den": ["switch.den", "light.den"], "porch": []}
HALL_OFF = {"entities": {"light.hall": {"state": "off"}}}
DEN_OFF = {"entities": {"switch.den": {"state": "off"}, "light.den": {"state": "off"}}}


def with_summer(*away_dates):
    """The pretend house with a preset that has only a weekday: Morning at 09:00."""
    schedule = make_schedule()
    schedule["presets"] = [
        {
            "id": "summer",
            "name": "Summer",
            "days": {
                "weekday": {
                    "enabled": True,
                    "automations": [
                        {
                            "id": "morning",
                            "name": "Morning",
                            "time": {"kind": "clock", "at": "09:00"},
                            "rooms": {"hall": {"entities": {"light.hall": {"state": "on"}}}},
                        }
                    ],
                }
            },
        }
    ]
    schedule["away_dates"] = [
        {"from": first, "to": last, "run": run} for first, last, run in away_dates
    ]
    return schedule


def away(run, starts, ends, change_id="a1", made="2027-06-01T10:00:00+00:00", **more):
    return {
        "id": change_id,
        "made_at": made,
        "from": starts.date().isoformat(),
        "until": ends.date().isoformat(),
        "days": "all",
        "kind": "away",
        "run": run,
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
        **more,
    }


def ids(day_list):
    return [a.id for a in day_list.automations]


def switches(day_list):
    return [(a.name, a.time, a.rooms) for a in day_list.switches]


# --- which schedule runs at a moment -------------------------------------------


def test_the_schedules_date_runs_until_the_rollover():
    schedule = make_schedule()
    assert schedule_date(at(TUESDAY, "03:59"), schedule, TZ) == MONDAY
    assert schedule_date(at(TUESDAY, "04:00"), schedule, TZ) == TUESDAY
    assert schedule_date(at(TUESDAY, "23:30"), schedule, TZ) == TUESDAY


def test_with_no_away_dates_the_regular_schedule_runs():
    assert mode_at(make_schedule(), [], at(TUESDAY, "12:00"), TZ) is None


def test_yearly_dates_run_from_rollover_to_rollover():
    schedule = with_summer(("06-15", "06-15", "summer"))
    assert mode_at(schedule, [], at(TUESDAY, "03:59"), TZ) is None
    assert mode_at(schedule, [], at(TUESDAY, "04:00"), TZ) == Mode("summer")
    assert mode_at(schedule, [], at(TUESDAY, "03:59", 1), TZ) == Mode("summer")
    assert mode_at(schedule, [], at(TUESDAY, "04:00", 1), TZ) is None


def test_the_first_yearly_range_listed_wins():
    schedule = with_summer(("06-01", "06-30", "off"), ("06-15", "06-15", "summer"))
    assert mode_at(schedule, [], at(TUESDAY, "12:00"), TZ) == Mode("off")


def test_the_clients_choice_wins_over_the_yearly_dates():
    schedule = with_summer(("06-01", "06-30", "off"))
    client = away_changes(
        schedule, [away("summer", at(TUESDAY, "08:00"), at(TUESDAY, "10:00"))]
    )
    assert mode_at(schedule, client, at(TUESDAY, "07:59"), TZ) == Mode("off")
    assert mode_at(schedule, client, at(TUESDAY, "08:00"), TZ) == Mode("summer")
    assert mode_at(schedule, client, at(TUESDAY, "10:00"), TZ) == Mode("off")


def test_the_later_of_two_client_choices_wins():
    first = away("off", at(TUESDAY, "08:00"), at(TUESDAY, "20:00"))
    second = away(
        "rooms", at(TUESDAY, "09:00"), at(TUESDAY, "10:00"),
        change_id="a2", made="2027-06-02T10:00:00+00:00", rooms=["hall"],
    )
    schedule = make_schedule()
    client = away_changes(schedule, [second, first])
    assert mode_at(schedule, client, at(TUESDAY, "09:30"), TZ) == Mode("rooms", frozenset({"hall"}))
    assert mode_at(schedule, client, at(TUESDAY, "11:00"), TZ) == Mode("off")


def test_a_client_choice_of_a_preset_the_schedule_lacks_is_skipped():
    change = away("winter", at(TUESDAY, "08:00"), at(TUESDAY, "20:00"))
    assert away_changes(with_summer(), [change]) == []
    assert ids(build(with_summer(), TUESDAY, changes=[change])) == ["morning", "sunset", "night"]


def test_the_moments_away_mode_changes_are_found():
    schedule = with_summer(("06-15", "06-16", "off"))
    client = away_changes(
        schedule, [away("summer", at(TUESDAY, "08:00"), at(TUESDAY, "10:00"))]
    )
    assert switch_moments(schedule, client, TUESDAY, TZ) == [
        (at(TUESDAY, "04:00"), Mode("off")),
        (at(TUESDAY, "08:00"), Mode("summer")),
        (at(TUESDAY, "10:00"), Mode("off")),
    ]
    # The next day stays off, so nothing changes at its start.
    assert switch_moments(schedule, client, TUESDAY + timedelta(days=1), TZ) == []
    assert switch_moments(schedule, client, TUESDAY + timedelta(days=2), TZ) == [
        (at(TUESDAY, "04:00", 2), None)
    ]


# --- what the schedule may hold ------------------------------------------------


@pytest.mark.parametrize(
    "presets",
    [
        "summer",
        ["summer"],
        [{"id": "Summer"}],
        [{"id": "off"}],
        [{"id": "rooms"}],
        [{"id": "a"}, {"id": "a"}],
        [{"id": "a", "days": []}],
        [{"id": "a", "alongside": {}}],
    ],
)
def test_presets_that_are_not_understood_are_refused(presets):
    with pytest.raises(ScheduleError):
        schedule_presets({"presets": presets})


@pytest.mark.parametrize(
    "away_dates",
    [
        "june",
        ["june"],
        [{"from": "06-01", "to": "06-30", "run": "winter"}],
        [{"from": "June", "to": "06-30", "run": "off"}],
        [{"from": "06-01", "run": "off"}],
    ],
)
def test_away_dates_that_are_not_understood_are_refused(away_dates):
    schedule = with_summer()
    schedule["away_dates"] = away_dates
    with pytest.raises(ScheduleError):
        check_schedule(schedule)


def test_an_away_change_is_checked():
    good = away("off", at(TUESDAY, "08:00"), at(TUESDAY, "20:00"))
    check_change(good)
    check_change({**good, "run": "rooms", "rooms": []})
    for bad in (
        {**good, "starts_at": "tomorrow"},
        {**good, "ends_at": "2027-06-15T20:00:00"},
        {**good, "ends_at": at(TUESDAY, "07:00").isoformat()},
        {**good, "run": "rooms"},
        {**good, "run": "rooms", "rooms": "hall"},
        {key: value for key, value in good.items() if key != "run"},
    ):
        with pytest.raises(ChangeError):
            check_change(bad)


# --- the day's list while away -------------------------------------------------


def test_all_off_runs_nothing():
    schedule = with_summer(("06-10", "06-20", "off"))
    got = build(schedule, TUESDAY, house_rooms=HOUSE)
    assert ids(got) == []
    assert got.switches == ()


def test_all_off_switches_everything_off_when_it_starts():
    schedule = with_summer(("06-15", "06-20", "off"))
    got = build(schedule, TUESDAY, house_rooms=HOUSE)
    assert switches(got) == [
        ("Away mode starts", at(TUESDAY, "04:00"), {"hall": HALL_OFF, "den": DEN_OFF})
    ]
    assert got.switches[0].merged is True
    assert got.moments[0] is got.switches[0]


def test_when_away_ends_each_room_goes_to_where_the_regular_schedule_has_it():
    schedule = with_summer(("06-10", "06-14", "off"))
    got = build(schedule, TUESDAY, house_rooms=HOUSE)
    assert ids(got) == ["morning", "sunset", "night"]
    # Monday's Night was the last thing the regular schedule would have run.
    assert switches(got) == [
        ("Away mode ends", at(TUESDAY, "04:00"), {"hall": {"scene": "scene.weekday"}})
    ]


def test_a_preset_runs_in_place_of_the_regular_schedule():
    schedule = with_summer(("06-10", "06-20", "summer"))
    got = build(schedule, TUESDAY)
    assert [(a.id, a.time) for a in got.automations] == [("morning", at(TUESDAY, "09:00"))]
    assert got.automations[0].rooms == {"hall": {"entities": {"light.hall": {"state": "on"}}}}
    # The date is still named by the regular schedule's day.
    assert got.day.day_id == "weekday"


def test_a_day_the_preset_does_not_have_runs_nothing():
    schedule = with_summer(("06-10", "06-20", "summer"))
    got = build(schedule, FRIDAY)
    assert ids(got) == []
    assert got.day.day_id == "friday"


def test_when_a_preset_starts_each_room_goes_to_where_the_preset_has_it():
    schedule = with_summer(("06-15", "06-20", "summer"))
    got = build(schedule, TUESDAY, house_rooms=HOUSE)
    # Monday's 09:00 in the preset was the last thing it would have run.
    assert switches(got) == [
        (
            "Away mode starts",
            at(TUESDAY, "04:00"),
            {"hall": {"entities": {"light.hall": {"state": "on"}}}},
        )
    ]


def test_the_client_can_be_away_for_part_of_a_day():
    change = away("off", at(TUESDAY, "12:00"), at(TUESDAY, "20:00"))
    got = build(make_schedule(), TUESDAY, changes=[change], house_rooms=HOUSE)
    assert ids(got) == ["morning", "night"]
    assert switches(got) == [
        ("Away mode starts", at(TUESDAY, "12:00"), {"hall": HALL_OFF, "den": DEN_OFF}),
        ("Away mode ends", at(TUESDAY, "20:00"), {"hall": {"scene": "scene.weekday"}}),
    ]


def test_cancelling_moves_the_end_and_the_house_goes_back_then():
    change = away("off", at(TUESDAY, "12:00"), at(TUESDAY, "13:00"))
    got = build(make_schedule(), TUESDAY, changes=[change], house_rooms=HOUSE)
    assert ids(got) == ["morning", "sunset", "night"]
    assert [a.time for a in got.switches] == [at(TUESDAY, "12:00"), at(TUESDAY, "13:00")]


def test_away_by_rooms_keeps_only_the_ticked_rooms_running():
    schedule = make_schedule()
    for automation in schedule["days"]["weekday"]["automations"]:
        automation["rooms"]["den"] = {"entities": {"light.den": {"state": "on"}}}
    change = away("rooms", at(TUESDAY, "12:00"), at(TUESDAY, "20:00"), rooms=["den"])
    got = build(schedule, TUESDAY, changes=[change], house_rooms=HOUSE)
    assert ids(got) == ["morning", "sunset", "night"]
    by_id = {a.id: a for a in got.automations}
    assert set(by_id["morning"].rooms) == {"hall", "den"}
    assert set(by_id["sunset"].rooms) == {"den"}
    assert set(by_id["night"].rooms) == {"hall", "den"}
    start = got.switches[0]
    assert start.time == at(TUESDAY, "12:00")
    # The unticked hall is switched off; the den stays where the schedule has it.
    assert start.rooms == {
        "hall": HALL_OFF,
        "den": {"entities": {"light.den": {"state": "on"}}},
    }


def test_the_client_can_run_a_preset_inside_yearly_all_off():
    schedule = with_summer(("06-01", "06-30", "off"))
    change = away("summer", at(TUESDAY, "08:00"), at(TUESDAY, "10:00"))
    got = build(schedule, TUESDAY, changes=[change], house_rooms=HOUSE)
    assert [(a.id, a.time) for a in got.automations] == [("morning", at(TUESDAY, "09:00"))]
    assert [(a.name, a.time) for a in got.switches] == [
        ("Away mode starts", at(TUESDAY, "08:00")),
        ("Away mode starts", at(TUESDAY, "10:00")),
    ]
    assert got.switches[1].rooms == {"hall": HALL_OFF, "den": DEN_OFF}


def test_a_cycle_stops_when_away_mode_starts():
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][0]["rooms"] = {
        "den": {
            "entities": {
                "switch.den": {"cycle": {"on_minutes": 60, "off_minutes": 60, "for_minutes": 600}}
            }
        }
    }
    change = away("off", at(TUESDAY, "10:30"), at(TUESDAY, "20:00"))
    got = build(schedule, TUESDAY, changes=[change], house_rooms=HOUSE)
    assert [a.time for a in got.cycle_steps] == [
        at(TUESDAY, "08:00"), at(TUESDAY, "09:00"), at(TUESDAY, "10:00"),
    ]


def test_the_regular_schedule_can_be_asked_for_whatever_the_away_dates_say():
    schedule = with_summer(("06-01", "06-30", "off"))
    assert ids(build(schedule, TUESDAY, away=False)) == ["morning", "sunset", "night"]


def test_the_year_preview_shows_the_regular_schedule():
    schedule = with_summer(("06-01", "06-30", "off"))
    (row,) = build_preview(schedule, SOURCE, TZ, TUESDAY, 1)
    assert [a["id"] for a in row["automations"]] == ["morning", "sunset", "night"]


def test_a_time_change_applies_to_the_preset_while_it_runs():
    schedule = with_summer(("06-10", "06-20", "summer"))
    change = {
        "id": "c1",
        "made_at": "2027-06-14T10:00:00+00:00",
        "from": TUESDAY.isoformat(),
        "until": TUESDAY.isoformat(),
        "days": "all",
        "kind": "time",
        "automation": "morning",
        "shift_minutes": 30,
    }
    got = build(schedule, TUESDAY, changes=[change])
    assert [(a.id, a.time) for a in got.automations] == [("morning", at(TUESDAY, "09:30"))]


def test_every_date_of_two_years_can_be_listed_while_away():
    schedule = with_summer(("12-20", "01-10", "summer"), ("07-01", "08-31", "off"))
    day = date(2026, 1, 1)
    while day < date(2028, 1, 1):
        build(schedule, day, house_rooms=HOUSE)
        day += timedelta(days=1)


# --- meals -----------------------------------------------------------------------


def meal_names(day):
    return meals_on(make_schedule(), day, SOURCE)


def test_the_meals_of_a_regular_week():
    assert meal_names(TUESDAY) == []
    assert meal_names(FRIDAY) == [("night", "Shabbos night")]
    assert meal_names(FRIDAY + timedelta(days=1)) == [
        ("day", "Shabbos day"),
        ("shalosh_seudos", "Shalosh seudos"),
    ]


def test_the_meals_of_pesach_that_runs_into_shabbos():
    # 5787: Pesach is Thursday 22 and Friday 23 April 2027.
    assert meal_names(date(2027, 4, 21)) == [("night", "Yom Tov night")]
    assert meal_names(date(2027, 4, 22)) == [("night", "Yom Tov night"), ("day", "Yom Tov day")]
    assert meal_names(date(2027, 4, 23)) == [("night", "Shabbos night"), ("day", "Yom Tov day")]
    assert meal_names(date(2027, 4, 24)) == [
        ("day", "Shabbos day"),
        ("shalosh_seudos", "Shalosh seudos"),
    ]


def test_yom_kippur_has_no_meals():
    # 5788: Yom Kippur is Monday 11 October 2027.
    assert meal_names(date(2027, 10, 10)) == []
    assert meal_names(date(2027, 10, 11)) == []


def test_until_motzei_shabbos_is_an_hour_after_havdalah():
    last, ends = motzei_end(make_schedule(), TUESDAY, SOURCE)
    saturday = FRIDAY + timedelta(days=1)
    assert (last, ends) == (saturday, at(saturday, "20:12"))
    # Asked on Shabbos itself, it is that Shabbos.
    assert motzei_end(make_schedule(), saturday, SOURCE) == (saturday, at(saturday, "20:12"))


def test_until_motzei_covers_yom_tov_that_runs_into_shabbos():
    last, ends = motzei_end(make_schedule(), date(2027, 4, 21), SOURCE)
    assert (last, ends) == (date(2027, 4, 24), at(date(2027, 4, 24), "20:12"))


def meal_out(day, meal):
    return {
        "id": f"m-{meal}",
        "made_at": "2027-06-14T10:00:00+00:00",
        "from": day.isoformat(),
        "until": day.isoformat(),
        "days": "all",
        "kind": "meal_out",
        "meal": meal,
    }


def _with_when_out():
    schedule = make_schedule()
    erev_shabbos = schedule["days"]["friday"]["automations"][1]
    erev_shabbos["rooms"]["dining"] = {"entities": {"light.dining": {"state": "on"}}}
    erev_shabbos["when_out"] = {
        "night": {"dining": {"entities": {"light.dining": {"state": "off"}}}}
    }
    return schedule


def test_out_for_a_meal_the_rooms_set_for_it_take_that_setting():
    got = build(_with_when_out(), FRIDAY, changes=[meal_out(FRIDAY, "night")])
    rooms = {a.id: a.rooms for a in got.automations}["erev_shabbos"]
    assert rooms["dining"] == {"entities": {"light.dining": {"state": "off"}}}
    # A room with no setting for the meal runs as usual.
    assert rooms["hall"] == {"scene": "scene.friday"}


def test_another_meal_or_another_date_changes_nothing():
    usual = {"entities": {"light.dining": {"state": "on"}}}
    for changes in ([], [meal_out(FRIDAY, "day")], [meal_out(TUESDAY, "night")]):
        got = build(_with_when_out(), FRIDAY, changes=changes)
        assert {a.id: a.rooms for a in got.automations}["erev_shabbos"]["dining"] == usual


def test_a_meal_change_is_checked():
    check_change(meal_out(FRIDAY, "night"))
    with pytest.raises(ChangeError):
        check_change(meal_out(FRIDAY, "kiddush"))
    with pytest.raises(ChangeError):
        check_change({**meal_out(FRIDAY, "night"), "until": "2027-06-19"})
