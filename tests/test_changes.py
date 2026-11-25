"""The client's temporary changes, laid on top of a date's fixed list.

Runs without Home Assistant, with the made-up schedule and zmanim of
tests/test_day_list.py: Morning 07:00, Sunset at shkia 18:00, Night 23:00.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from engine.changes import (
    ChangeError,
    active_changes,
    check_change,
    check_store,
    rooms_off_for,
    still_wanted,
)
from engine.actions import plan_steps
from engine.scenes import expand_scenes, schedule_scenes

from .test_day_list import FRIDAY, TUESDAY, at, build, make_schedule, times

SHABBOS = FRIDAY + timedelta(days=1)
# Shavuos, first day, on a Friday: a Friday that is itself Yom Tov.
YOM_TOV_FRIDAY = date(2026, 5, 22)

_NEXT = iter(range(1, 10_000))


def change(kind, *, first=TUESDAY, last=None, days="all", made="2027-06-01T10:00:00+00:00", **more):
    """A temporary change over ``first`` to ``last``."""
    return {
        "id": f"c{next(_NEXT)}",
        "made_at": made,
        "from": first.isoformat(),
        "until": (last or first).isoformat(),
        "days": days,
        "kind": kind,
        **more,
    }


def time_of(day_list, automation_id):
    return dict(times(day_list))[automation_id]


def rooms_of(day_list, automation_id):
    return next(a.rooms for a in day_list.automations if a.id == automation_id)


LAMP_ON = {"state": "on", "brightness_pct": 40}
LAMP_OFF = {"state": "off"}


def schedule_with_entities():
    """The made-up schedule, with Morning setting two lamps in the den."""
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][0]["rooms"] = {
        "den": {"entities": {"light.den_a": {"state": "on"}, "light.den_b": {"state": "on"}}},
        "hall": {"scene": "scene.weekday"},
    }
    return schedule


# --- with no changes, nothing differs --------------------------------------


def test_a_list_with_no_changes_is_the_schedules_own():
    plain = build(make_schedule(), TUESDAY)
    got = build(make_schedule(), TUESDAY, changes=[], rooms_off=[])
    assert got == plain
    assert got.rooms_off == frozenset()
    assert got.skipped_changes == ()


# --- a different time ------------------------------------------------------


def test_a_clock_time_replaces_the_automations_time():
    moved = change("time", automation="night", time={"kind": "clock", "at": "22:15"})
    got = build(make_schedule(), TUESDAY, changes=[moved])
    assert time_of(got, "night") == at(TUESDAY, "22:15")
    assert time_of(got, "morning") == at(TUESDAY, "07:00")
    assert got.skipped_changes == ()


def test_a_shift_moves_a_time_that_follows_a_zman():
    later = change("time", automation="sunset", shift_minutes=30)
    earlier = change("time", automation="sunset", shift_minutes=-45)
    assert time_of(build(make_schedule(), TUESDAY, changes=[later]), "sunset") == at(TUESDAY, "18:30")
    assert time_of(build(make_schedule(), TUESDAY, changes=[earlier]), "sunset") == at(TUESDAY, "17:15")


def test_the_list_stays_in_time_order_after_a_time_change():
    moved = change("time", automation="night", time={"kind": "clock", "at": "06:00"})
    got = build(make_schedule(), TUESDAY, changes=[moved])
    assert [a.id for a in got.automations] == ["night", "morning", "sunset"]


def test_a_time_change_applies_only_within_its_dates():
    moved = change(
        "time", first=TUESDAY, last=TUESDAY + timedelta(days=2),
        automation="night", time={"kind": "clock", "at": "22:00"},
    )
    for offset, clock in [(-1, "23:00"), (0, "22:00"), (2, "22:00")]:
        day = TUESDAY + timedelta(days=offset)
        assert time_of(build(make_schedule(), day, changes=[moved]), "night") == at(day, clock)
    after = TUESDAY + timedelta(days=3)  # a Friday
    assert time_of(build(make_schedule(), after, changes=[moved]), "night") == at(after, "23:00")


def test_a_change_applies_only_on_the_days_it_names():
    week = dict(first=TUESDAY, last=TUESDAY + timedelta(days=6))
    moved = change(
        "time", days=["weekday"], automation="night",
        time={"kind": "clock", "at": "22:00"}, **week,
    )
    assert time_of(build(make_schedule(), TUESDAY, changes=[moved]), "night") == at(TUESDAY, "22:00")
    assert time_of(build(make_schedule(), FRIDAY, changes=[moved]), "night") == at(FRIDAY, "23:00")
    assert time_of(build(make_schedule(), SHABBOS, changes=[moved]), "night") == at(SHABBOS, "23:00")


def test_of_two_time_changes_the_one_made_later_wins():
    first = change(
        "time", made="2027-06-01T10:00:00+00:00",
        automation="night", time={"kind": "clock", "at": "22:00"},
    )
    second = change(
        "time", made="2027-06-02T10:00:00+00:00",
        automation="night", time={"kind": "clock", "at": "21:00"},
    )
    for order in ([first, second], [second, first]):
        assert time_of(build(make_schedule(), TUESDAY, changes=order), "night") == at(TUESDAY, "21:00")


def test_a_time_past_the_rollover_is_skipped_and_the_schedule_kept():
    late = change(
        "time", automation="night", time={"kind": "clock", "at": "05:00", "day_offset": 1},
    )
    got = build(make_schedule(), TUESDAY, changes=[late])
    assert time_of(got, "night") == at(TUESDAY, "23:00")
    assert [skipped for skipped, _ in got.skipped_changes] == [late["id"]]


def test_a_shift_to_before_the_day_begins_is_skipped():
    early = change("time", automation="morning", shift_minutes=-240)  # 03:00
    got = build(make_schedule(), TUESDAY, changes=[early])
    assert time_of(got, "morning") == at(TUESDAY, "07:00")
    assert [skipped for skipped, _ in got.skipped_changes] == [early["id"]]


def test_where_the_later_time_change_cannot_be_used_the_earlier_one_is():
    good = change(
        "time", made="2027-06-01T10:00:00+00:00",
        automation="night", time={"kind": "clock", "at": "22:00"},
    )
    bad = change(
        "time", made="2027-06-02T10:00:00+00:00",
        automation="night", time={"kind": "clock", "at": "05:00", "day_offset": 1},
    )
    got = build(make_schedule(), TUESDAY, changes=[good, bad])
    assert time_of(got, "night") == at(TUESDAY, "22:00")


def test_a_change_for_an_automation_the_day_lacks_is_skipped():
    moved = change(
        "time", first=TUESDAY, last=FRIDAY,
        automation="erev_shabbos", time={"kind": "clock", "at": "15:00"},
    )
    on_tuesday = build(make_schedule(), TUESDAY, changes=[moved])
    assert times(on_tuesday) == times(build(make_schedule(), TUESDAY))
    assert on_tuesday.skipped_changes == ((moved["id"], "This day has no such automation"),)
    on_friday = build(make_schedule(), FRIDAY, changes=[moved])
    assert time_of(on_friday, "erev_shabbos") == at(FRIDAY, "15:00")
    assert on_friday.skipped_changes == ()


def test_a_time_change_reaches_a_running_alongside_automation():
    omer = date(2027, 5, 4)  # during Sefiras haomer
    plain = build(make_schedule(), omer)
    assert time_of(plain, "sefiras_haomer") == at(omer, "18:45")
    moved = change("time", first=omer, automation="sefiras_haomer", shift_minutes=20)
    assert time_of(build(make_schedule(), omer, changes=[moved]), "sefiras_haomer") == at(omer, "19:05")


# --- a different state in a room -------------------------------------------


def test_a_room_change_sets_an_entity_the_automation_already_sets():
    dim = change("room", automation="morning", room="den", entities={"light.den_a": LAMP_ON})
    got = build(schedule_with_entities(), TUESDAY, changes=[dim])
    assert rooms_of(got, "morning")["den"]["entities"] == {
        "light.den_b": {"state": "on"},
        "light.den_a": LAMP_ON,
    }
    assert rooms_of(got, "morning")["hall"] == {"scene": "scene.weekday"}


def test_a_room_change_adds_an_entity_and_a_room():
    more = change("room", automation="morning", room="den", entities={"light.den_c": LAMP_ON})
    new_room = change("room", automation="morning", room="attic", entities={"light.attic": LAMP_OFF})
    got = build(schedule_with_entities(), TUESDAY, changes=[more, new_room])
    rooms = rooms_of(got, "morning")
    assert rooms["den"]["entities"]["light.den_c"] == LAMP_ON
    assert rooms["attic"] == {"entities": {"light.attic": LAMP_OFF}}


def test_a_room_change_leaves_an_entity_as_is():
    leave = change("room", automation="morning", room="den", entities={"light.den_a": None})
    got = build(schedule_with_entities(), TUESDAY, changes=[leave])
    assert rooms_of(got, "morning")["den"]["entities"] == {"light.den_b": {"state": "on"}}


def test_a_room_change_does_not_alter_the_schedule_itself():
    schedule = schedule_with_entities()
    dim = change("room", automation="morning", room="den", entities={"light.den_a": None})
    build(schedule, TUESDAY, changes=[dim])
    assert schedule == schedule_with_entities()
    assert rooms_of(build(schedule, TUESDAY), "morning")["den"]["entities"] == {
        "light.den_a": {"state": "on"}, "light.den_b": {"state": "on"},
    }


def test_of_two_room_changes_the_later_wins_entity_by_entity():
    first = change(
        "room", made="2027-06-01T10:00:00+00:00", automation="morning", room="den",
        entities={"light.den_a": LAMP_OFF, "light.den_b": LAMP_OFF},
    )
    second = change(
        "room", made="2027-06-02T10:00:00+00:00", automation="morning", room="den",
        entities={"light.den_a": LAMP_ON},
    )
    got = build(schedule_with_entities(), TUESDAY, changes=[second, first])
    assert rooms_of(got, "morning")["den"]["entities"] == {
        "light.den_b": LAMP_OFF, "light.den_a": LAMP_ON,
    }


def test_a_room_that_uses_a_scene_made_in_the_form_has_its_entities_changed():
    schedule = schedule_with_entities()
    schedule["scenes"] = [
        {
            "id": "ryton_den_bright", "name": "Bright", "room": "den", "fade_seconds": 30,
            "entities": {"light.den_a": {"state": "on"}, "light.den_b": {"state": "on"}},
        }
    ]
    schedule["days"]["weekday"]["automations"][0]["rooms"]["den"] = {
        "scene": "scene.ryton_den_bright"
    }
    alter = change(
        "room", automation="morning", room="den",
        entities={"light.den_a": None, "light.den_b": LAMP_OFF},
    )
    got = build(schedule, TUESDAY, changes=[alter])
    assert rooms_of(got, "morning")["den"] == {
        "entities": {"light.den_b": LAMP_OFF},
        "fade_seconds": 30,
    }


def test_a_room_that_uses_a_home_assistant_scene_runs_it_then_the_entities():
    add = change("room", automation="morning", room="hall", entities={"light.hall": LAMP_OFF})
    got = build(schedule_with_entities(), TUESDAY, changes=[add])
    hall = rooms_of(got, "morning")["hall"]
    assert hall == {"scene": "scene.weekday", "entities": {"light.hall": LAMP_OFF}}
    # The engine can carry it out: the scene first, then the entity.
    rooms = expand_scenes({"hall": hall}, schedule_scenes(schedule_with_entities()))
    steps = plan_steps(rooms, merged=True)
    assert [call.entity_id for step in steps for call in step.calls] == [
        "scene.weekday", "light.hall",
    ]


# --- room switches ---------------------------------------------------------


def test_a_rooms_own_switch_with_no_changes():
    got = build(make_schedule(), TUESDAY, rooms_off=["guest_room"])
    assert got.rooms_off == frozenset({"guest_room"})


def test_off_until_a_date_then_back_to_the_rooms_own_switch():
    off = change("room_switch", first=TUESDAY, last=TUESDAY + timedelta(days=1), room="den", scheduling="off")
    assert build(make_schedule(), TUESDAY, changes=[off]).rooms_off == frozenset({"den"})
    after = TUESDAY + timedelta(days=2)
    assert build(make_schedule(), after, changes=[off]).rooms_off == frozenset()


def test_on_until_a_date_for_a_room_whose_own_switch_is_off():
    on = change("room_switch", first=TUESDAY, last=TUESDAY, room="guest_room", scheduling="on")
    assert build(make_schedule(), TUESDAY, changes=[on], rooms_off=["guest_room"]).rooms_off == frozenset()
    after = TUESDAY + timedelta(days=1)
    assert build(make_schedule(), after, changes=[on], rooms_off=["guest_room"]).rooms_off == frozenset(
        {"guest_room"}
    )


def test_of_two_room_switch_changes_the_later_wins():
    off = change("room_switch", made="2027-06-01T10:00:00+00:00", room="den", scheduling="off")
    on = change("room_switch", made="2027-06-02T10:00:00+00:00", room="den", scheduling="on")
    assert rooms_off_for(active_changes([on, off], TUESDAY, "weekday")) == frozenset()
    off["made_at"] = "2027-06-03T10:00:00+00:00"
    assert rooms_off_for(active_changes([on, off], TUESDAY, "weekday")) == frozenset({"den"})


def test_a_room_switched_off_is_skipped_when_the_automation_runs():
    off = change("room_switch", room="den", scheduling="off")
    got = build(schedule_with_entities(), TUESDAY, changes=[off])
    steps = plan_steps(rooms_of(got, "morning"), rooms_off=got.rooms_off)
    assert [call.entity_id for step in steps for call in step.calls] == ["scene.weekday"]


# --- early and late Shabbos, this week -------------------------------------


def early_rule_schedule():
    schedule = make_schedule()
    schedule["settings"]["early_shabbos_rules"] = [
        {"when": {"kind": "clock_season", "season": "summer"},
         "start": {"kind": "zman", "zman": "plag"}}
    ]
    return schedule


def test_early_shabbos_this_week():
    early = change("shabbos", first=FRIDAY, week="early", start={"kind": "clock", "at": "16:00"})
    got = build(make_schedule(), FRIDAY, changes=[early])
    assert got.shabbos_start == at(FRIDAY, "16:00")
    assert time_of(got, "erev_shabbos") == at(FRIDAY, "15:50")


def test_late_shabbos_this_week_skips_the_houses_early_rules():
    schedule = early_rule_schedule()
    assert build(schedule, FRIDAY).shabbos_start == at(FRIDAY, "16:45")
    late = change("shabbos", first=FRIDAY, week="late")
    assert build(schedule, FRIDAY, changes=[late]).shabbos_start == at(FRIDAY, "17:42")


def test_a_shabbos_change_touches_only_the_fridays_in_its_dates():
    early = change("shabbos", first=FRIDAY, week="early", start={"kind": "clock", "at": "16:00"})
    next_friday = FRIDAY + timedelta(days=7)
    assert build(make_schedule(), next_friday, changes=[early]).shabbos_start == at(next_friday, "17:42")
    assert build(make_schedule(), TUESDAY, changes=[early]) == build(make_schedule(), TUESDAY)


def test_early_shabbos_never_applies_on_a_friday_that_is_yom_tov():
    early = change(
        "shabbos", first=YOM_TOV_FRIDAY, week="early", start={"kind": "clock", "at": "16:00"},
    )
    plain = build(make_schedule(), YOM_TOV_FRIDAY)
    assert plain.day.day_id == "shavuos_1__friday"
    assert build(make_schedule(), YOM_TOV_FRIDAY, changes=[early]).shabbos_start == plain.shabbos_start


def test_an_early_shabbos_change_that_cannot_be_read_is_skipped():
    bad = change("shabbos", first=FRIDAY, week="early", start={"kind": "nonsense"})
    got = build(make_schedule(), FRIDAY, changes=[bad])
    assert got.shabbos_start == at(FRIDAY, "17:42")
    assert [skipped for skipped, _ in got.skipped_changes] == [bad["id"]]


# --- simcha ----------------------------------------------------------------


def test_simcha_over_a_range_of_dates_moves_each_night():
    simcha = change("simcha", first=TUESDAY, last=TUESDAY + timedelta(days=1))
    for offset in (0, 1):
        day = TUESDAY + timedelta(days=offset)
        got = build(make_schedule(), day, changes=[simcha])
        assert time_of(got, "night") == at(day, "01:00", day_offset=1)
    after = TUESDAY + timedelta(days=2)
    assert time_of(build(make_schedule(), after, changes=[simcha]), "night") == at(after, "23:00")


def test_simcha_is_laid_on_top_of_a_changed_night():
    simcha = change("simcha")
    moved = change("time", automation="night", time={"kind": "clock", "at": "22:00"})
    got = build(make_schedule(), TUESDAY, changes=[simcha, moved])
    assert time_of(got, "night") == at(TUESDAY, "01:00", day_offset=1)


def test_simcha_with_no_simcha_time_is_skipped_and_the_day_still_runs():
    schedule = make_schedule()
    del schedule["settings"]["simcha"]
    simcha = change("simcha")
    got = build(schedule, TUESDAY, changes=[simcha])
    assert time_of(got, "night") == at(TUESDAY, "23:00")
    assert [skipped for skipped, _ in got.skipped_changes] == [simcha["id"]]


# --- a change never stops the day ------------------------------------------


def test_changes_that_are_not_understood_are_left_out():
    junk = [
        None,
        "night",
        {"kind": "time"},
        change("time", automation="night", time={"kind": "zman", "zman": "shkia"}),
        change("time", automation="night", shift_minutes=0),
        change("room", automation="morning", room="den", entities={"scene.x": {"state": "on"}}),
        change("room", automation="morning", room="den", scene="scene.x", entities={"light.a": LAMP_ON}),
        change("volume", room="den"),
    ]
    assert build(make_schedule(), TUESDAY, changes=junk) == build(make_schedule(), TUESDAY)


@pytest.mark.parametrize("yom_tov_days", [1, 2])
def test_every_date_in_two_years_builds_with_changes_on_top(yom_tov_days):
    """Whatever day a date is, the changes never stop its list being built."""
    schedule = make_schedule(yom_tov_days)
    first, last = date(2026, 9, 1), date(2028, 9, 1)
    span = dict(first=first, last=last)
    changes = [
        change("time", automation="night", shift_minutes=-30, **span),
        change("time", automation="morning", time={"kind": "clock", "at": "08:00"}, **span),
        change("time", automation="sunset", shift_minutes=660, **span),  # past the rollover
        change("room", automation="morning", room="den", entities={"light.den_a": LAMP_ON}, **span),
        change("room_switch", room="hall", scheduling="off", **span),
        change("shabbos", week="early", start={"kind": "clock", "at": "16:00"}, **span),
        change("simcha", days=["weekday"], **span),
    ]
    day = first
    while day <= last:
        plain = build(schedule, day)
        got = build(schedule, day, changes=changes)
        assert got.day == plain.day
        assert {a.id for a in got.automations} == {a.id for a in plain.automations}
        assert got.rooms_off == frozenset({"hall"})
        assert time_of(got, "morning") == at(day, "08:00")
        assert time_of(got, "sunset") == time_of(plain, "sunset")
        assert rooms_of(got, "morning")["den"] == {"entities": {"light.den_a": LAMP_ON}}
        if got.day.day_id != "weekday":
            assert time_of(got, "night") == time_of(plain, "night") - timedelta(minutes=30)
        day += timedelta(days=1)


# --- checking and keeping --------------------------------------------------


def test_a_good_change_of_each_kind_passes_the_check():
    for good in [
        change("time", automation="night", time={"kind": "clock", "at": "22:00"}),
        change("time", automation="night", shift_minutes=-15),
        change("room", automation="night", room="den", entities={"light.a": LAMP_ON, "light.b": None}),
        change("room_switch", room="den", scheduling="on"),
        change("shabbos", week="late"),
        change("shabbos", week="early", start={"kind": "clock", "at": "16:00"}),
        change("simcha", days=["weekday", "friday"]),
    ]:
        check_change(good)


@pytest.mark.parametrize(
    "bad",
    [
        {"until": "2027-06-14"},  # ends before it starts
        {"from": "next week"},
        {"days": []},
        {"days": "weekday"},
        {"made_at": "yesterday"},
        {"id": ""},
    ],
)
def test_a_change_with_a_bad_common_field_is_refused(bad):
    broken = {**change("simcha"), **bad}
    with pytest.raises(ChangeError):
        check_change(broken)


def test_the_store_is_checked_as_a_whole():
    one, two = change("simcha"), change("simcha")
    check_store({"format_version": 1, "rooms_off": ["den"], "changes": [one, two]})
    check_store({"format_version": 1})
    with pytest.raises(ChangeError):
        check_store({"format_version": 2, "changes": []})
    with pytest.raises(ChangeError):
        check_store({"format_version": 1, "changes": [one, {**two, "id": one["id"]}]})
    with pytest.raises(ChangeError):
        check_store({"format_version": 1, "rooms_off": "den"})


def test_a_change_is_dropped_the_day_after_its_last_date():
    ends_tuesday = change("simcha", first=TUESDAY - timedelta(days=3), last=TUESDAY)
    assert still_wanted([ends_tuesday], TUESDAY) == [ends_tuesday]
    assert still_wanted([ends_tuesday], TUESDAY + timedelta(days=1)) == []
    assert still_wanted([ends_tuesday, None, {"until": "?"}], TUESDAY) == [ends_tuesday]
