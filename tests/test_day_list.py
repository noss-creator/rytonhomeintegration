"""Putting a date's fixed list together from a whole schedule.

Runs without Home Assistant. Hebrew dates come from tests/hdate_source.py.
The zmanim are made-up values, the same every day, so the expected times are
easy to read: netz 06:00, plag 16:45, shkia 18:00, tzeis 18:40, candle
lighting 17:42 on Fridays, havdalah 19:12 on Shabbos.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from engine.day_list import build_day_list
from engine.day_tables import table_for
from engine.time_resolver import (
    PastRolloverError,
    ScheduleError,
)

from .hdate_source import HdateSource

TZ = ZoneInfo("America/New_York")

_EVERY_DAY = {"netz": "06:00", "plag": "16:45", "shkia": "18:00", "tzeis": "18:40"}


class Source(HdateSource):
    def zman(self, day: date, key: str) -> datetime | None:
        clock = _EVERY_DAY.get(key)
        if key == "candle_lighting" and day.weekday() == 4:
            clock = "17:42"
        if key == "havdalah" and day.weekday() == 5:
            clock = "19:12"
        return at(day, clock) if clock else None


def at(day: date, clock: str, day_offset: int = 0) -> datetime:
    hour, minute = (int(p) for p in clock.split(":"))
    on = day + timedelta(days=day_offset)
    return datetime(on.year, on.month, on.day, hour, minute, tzinfo=TZ)


SOURCE = Source()


def _automation(automation_id, time, day_id):
    return {
        "id": automation_id,
        "name": automation_id.replace("_", " ").title(),
        "time": time,
        "fade_seconds": 0,
        # Marks which day the automation came from.
        "rooms": {"hall": {"scene": f"scene.{day_id}"}},
    }


def make_schedule(yom_tov_days=2, purim="regular"):
    """A schedule holding every day of the house, each with Morning, Sunset and Night."""
    table = table_for(yom_tov_days, purim)
    day_ids = ["weekday", "friday", "shabbos"]
    day_ids += [o.id for o in table.shabbos_variants]
    day_ids += [o.id for o in table.friday_variants]
    day_ids += [o.id for o in table.occasions if o.standalone]
    day_ids += [c.id for c in table.combinations]

    days = {}
    for day_id in day_ids:
        days[day_id] = {
            "enabled": True,
            "automations": [
                _automation("morning", {"kind": "clock", "at": "07:00"}, day_id),
                _automation("sunset", {"kind": "zman", "zman": "shkia"}, day_id),
                _automation("night", {"kind": "clock", "at": "23:00"}, day_id),
            ],
        }
    days["friday"]["automations"].insert(
        1,
        _automation(
            "erev_shabbos",
            {"kind": "zman", "zman": "shabbos_start", "offset_minutes": -10},
            "friday",
        ),
    )

    return {
        "format_version": 1,
        "house_id": "test-house",
        "revision": 1,
        "published_at": "2026-11-23T10:30:00+02:00",
        "settings": {
            "yom_tov_days": yom_tov_days,
            "candle_lighting_minutes": 18,
            "havdalah_minutes": 72,
            "purim": purim,
            "selichos": {"from_motzei_shabbos": True, "from_elul": False},
            "early_shabbos_rules": [],
            "simcha": {"night_time": {"kind": "clock", "at": "01:00", "day_offset": 1}},
            "pacing": {"group_size": 5, "pause_seconds": 1},
            "day_rollover": "04:00",
        },
        "days": days,
        "alongside": [
            {
                "id": "sefiras_haomer",
                "name": "Sefiras haomer",
                "time": {"kind": "zman", "zman": "tzeis", "offset_minutes": 5},
                "rooms": {"porch": {"scene": "scene.omer"}},
            },
            {
                "id": "chanukah_candle_lighting",
                "name": "Chanukah candle lighting",
                "times": {
                    "weeknight": {"kind": "zman", "zman": "tzeis"},
                    "friday": {"kind": "zman", "zman": "candle_lighting", "offset_minutes": -15},
                    "motzei_shabbos": {"kind": "zman", "zman": "havdalah", "offset_minutes": 10},
                },
                "rooms": {"porch": {"scene": "scene.chanukah"}},
            },
            {
                "id": "selichos",
                "name": "Selichos",
                "time": {"kind": "clock", "at": "05:30"},
                "rooms": {"porch": {"scene": "scene.selichos"}},
            },
        ],
    }


TUESDAY = date(2027, 6, 15)
FRIDAY = date(2027, 6, 18)
SUCCOS_ON_SHABBOS = date(2026, 9, 26)


def build(schedule, day, **kwargs):
    return build_day_list(schedule, day, SOURCE, TZ, **kwargs)


def times(day_list):
    return [(a.id, a.time) for a in day_list.automations]


# --- a plain day -----------------------------------------------------------


def test_weekday_list():
    got = build(make_schedule(), TUESDAY)
    assert got.day.day_id == "weekday"
    assert got.shabbos_start is None
    assert times(got) == [
        ("morning", at(TUESDAY, "07:00")),
        ("sunset", at(TUESDAY, "18:00")),
        ("night", at(TUESDAY, "23:00")),
    ]


def test_list_is_in_time_order_whatever_order_the_schedule_has():
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"].reverse()
    got = build(schedule, TUESDAY)
    assert [a.id for a in got.automations] == ["morning", "sunset", "night"]


def test_rooms_and_fade_are_carried_through():
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][0]["fade_seconds"] = 30
    morning = build(schedule, TUESDAY).automations[0]
    assert morning.fade_seconds == 30
    assert morning.rooms == {"hall": {"scene": "scene.weekday"}}
    assert morning.alongside is False


# --- Friday and Shabbos start ---------------------------------------------


def test_friday_times_from_shabbos_start():
    got = build(make_schedule(), FRIDAY)
    assert got.day.day_id == "friday"
    assert got.shabbos_start == at(FRIDAY, "17:42")
    assert times(got)[1] == ("erev_shabbos", at(FRIDAY, "17:32"))


def test_early_shabbos_rule_moves_the_friday_automation():
    schedule = make_schedule()
    schedule["settings"]["early_shabbos_rules"] = [
        {"when": {"kind": "clock_season", "season": "summer"},
         "start": {"kind": "zman", "zman": "plag"}}
    ]
    got = build(schedule, FRIDAY)
    assert got.shabbos_start == at(FRIDAY, "16:45")
    assert times(got)[1] == ("erev_shabbos", at(FRIDAY, "16:35"))

    late = build(schedule, FRIDAY, one_week={"kind": "late"})
    assert late.shabbos_start == at(FRIDAY, "17:42")
    assert times(late)[1] == ("erev_shabbos", at(FRIDAY, "17:32"))


def test_early_shabbos_this_week_with_no_rules():
    switch = {"kind": "early", "start": {"kind": "clock", "at": "16:00"}}
    got = build(make_schedule(), FRIDAY, one_week=switch)
    assert times(got)[1] == ("erev_shabbos", at(FRIDAY, "15:50"))


# --- combination days ------------------------------------------------------


def test_combination_day_uses_its_own_automations():
    got = build(make_schedule(), SUCCOS_ON_SHABBOS)
    assert got.day.day_id == "succos_1__shabbos"
    assert {a.rooms["hall"]["scene"] for a in got.automations} == {
        "scene.succos_1__shabbos"
    }


def test_switched_off_combination_runs_the_yom_tovs_own_day():
    schedule = make_schedule()
    schedule["days"]["succos_1__shabbos"]["enabled"] = False
    got = build(schedule, SUCCOS_ON_SHABBOS)
    assert got.day.day_id == "succos_1"
    assert {a.rooms["hall"]["scene"] for a in got.automations} == {"scene.succos_1"}


# --- simcha mode -----------------------------------------------------------


def test_simcha_mode_moves_night_later():
    got = build(make_schedule(), TUESDAY, simcha=True)
    assert times(got)[-1] == ("night", at(TUESDAY, "01:00", day_offset=1))
    assert times(got)[:2] == times(build(make_schedule(), TUESDAY))[:2]


def test_simcha_mode_keeps_a_night_that_is_already_later():
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][2]["time"] = {
        "kind": "clock", "at": "02:00", "day_offset": 1,
    }
    got = build(schedule, TUESDAY, simcha=True)
    assert times(got)[-1] == ("night", at(TUESDAY, "02:00", day_offset=1))


def test_simcha_mode_with_no_simcha_time_is_refused():
    schedule = make_schedule()
    del schedule["settings"]["simcha"]
    build(schedule, TUESDAY)
    with pytest.raises(ScheduleError):
        build(schedule, TUESDAY, simcha=True)


# --- day rollover ----------------------------------------------------------


def _with_late_night(clock="05:00"):
    schedule = make_schedule()
    night = schedule["days"]["weekday"]["automations"][2]
    night["time"] = {"kind": "clock", "at": clock, "day_offset": 1}
    return schedule, night


def test_night_past_the_rollover_is_refused():
    schedule, _ = _with_late_night()
    with pytest.raises(PastRolloverError):
        build(schedule, TUESDAY)


def test_night_past_the_rollover_runs_with_the_automations_exception():
    schedule, night = _with_late_night()
    night["allow_past_rollover"] = True
    assert times(build(schedule, TUESDAY))[-1] == ("night", at(TUESDAY, "05:00", 1))


def test_night_past_the_rollover_runs_with_the_days_exception():
    schedule, _ = _with_late_night()
    schedule["days"]["weekday"]["allow_past_rollover"] = True
    assert times(build(schedule, TUESDAY))[-1] == ("night", at(TUESDAY, "05:00", 1))


def test_rollover_is_the_houses_own_setting():
    schedule, _ = _with_late_night("04:30")
    with pytest.raises(PastRolloverError):
        build(schedule, TUESDAY)
    schedule["settings"]["day_rollover"] = "05:00"
    assert times(build(schedule, TUESDAY))[-1] == ("night", at(TUESDAY, "04:30", 1))


# --- running-alongside automations -----------------------------------------


def test_omer_runs_on_top_of_the_days_own_list():
    omer_tuesday = date(2027, 5, 4)
    got = build(make_schedule(), omer_tuesday)
    assert got.day.day_id == "weekday"
    assert times(got) == [
        ("morning", at(omer_tuesday, "07:00")),
        ("sunset", at(omer_tuesday, "18:00")),
        ("sefiras_haomer", at(omer_tuesday, "18:45")),
        ("night", at(omer_tuesday, "23:00")),
    ]
    omer = got.automations[2]
    assert omer.alongside is True
    assert omer.rooms == {"porch": {"scene": "scene.omer"}}


def test_chanukah_uses_the_time_for_its_weekday():
    friday, shabbos, sunday = date(2026, 12, 4), date(2026, 12, 5), date(2026, 12, 6)
    schedule = make_schedule()

    def chanukah(day):
        [found] = [a for a in build(schedule, day).automations if a.alongside]
        return found.time

    assert chanukah(friday) == at(friday, "17:27")
    assert chanukah(shabbos) == at(shabbos, "19:22")
    assert chanukah(sunday) == at(sunday, "18:40")


def test_selichos_follows_the_houses_period():
    monday = date(2027, 9, 27)  # the week before Rosh Hashana 5788
    schedule = make_schedule()
    assert times(build(schedule, monday))[0] == ("selichos", at(monday, "05:30"))

    schedule["settings"]["selichos"] = {"from_motzei_shabbos": False, "from_elul": False}
    assert [a.id for a in build(schedule, monday).automations if a.alongside] == []


def test_alongside_automation_not_set_up_is_left_out():
    schedule = make_schedule()
    schedule["alongside"] = []
    got = build(schedule, date(2027, 5, 4))
    assert [a.id for a in got.automations] == ["morning", "sunset", "night"]


# --- schedules the engine must refuse --------------------------------------


def test_unknown_format_version_is_refused():
    schedule = make_schedule()
    schedule["format_version"] = 2
    with pytest.raises(ScheduleError):
        build(schedule, TUESDAY)


def test_schedule_missing_the_dates_day_is_refused():
    schedule = make_schedule()
    del schedule["days"]["weekday"]
    with pytest.raises(ScheduleError):
        build(schedule, TUESDAY)


def test_schedule_missing_a_combination_day_is_refused():
    schedule = make_schedule()
    del schedule["days"]["succos_1__shabbos"]
    with pytest.raises(ScheduleError):
        build(schedule, SUCCOS_ON_SHABBOS)


def test_same_automation_identifier_twice_in_a_day_is_refused():
    schedule = make_schedule()
    automations = schedule["days"]["weekday"]["automations"]
    automations.append(copy.deepcopy(automations[0]))
    with pytest.raises(ScheduleError):
        build(schedule, TUESDAY)


def test_automation_timed_from_a_zman_the_date_lacks_is_refused():
    from engine.time_resolver import (
        ZmanUnavailableError,
    )

    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][1]["time"] = {
        "kind": "zman", "zman": "candle_lighting",
    }
    with pytest.raises(ZmanUnavailableError):
        build(schedule, TUESDAY)


# --- every date for two years ---------------------------------------------


@pytest.mark.parametrize(
    "yom_tov_days,purim", [(2, "regular"), (2, "shushan"), (1, "regular"), (1, "shushan")]
)
def test_a_list_can_be_built_for_every_date_in_two_years(yom_tov_days, purim):
    schedule = make_schedule(yom_tov_days, purim)
    day = date(2026, 11, 23)
    while day <= date(2028, 11, 22):
        got = build(schedule, day)
        ids = [a.id for a in got.automations if not a.alongside]
        assert {"morning", "sunset", "night"} <= set(ids), day
        assert [a.time for a in got.automations] == sorted(a.time for a in got.automations)
        day += timedelta(days=1)


# --- early Shabbos on a Friday of Chol Hamoed -------------------------------

CHOL_HAMOED_FRIDAY = date(2028, 4, 14)  # Chol Hamoed Pesach on Friday
AT_PLAG_IN_SUMMER = [
    {"when": {"kind": "clock_season", "season": "summer"},
     "start": {"kind": "zman", "zman": "plag"}}
]


def _schedule_with_early_rule(on_chol_hamoed=None):
    schedule = make_schedule()
    schedule["settings"]["early_shabbos_rules"] = AT_PLAG_IN_SUMMER
    if on_chol_hamoed is not None:
        schedule["settings"]["early_shabbos_on_chol_hamoed"] = on_chol_hamoed
    return schedule


def test_early_shabbos_applies_on_chol_hamoed_only_when_the_house_says_so():
    got = build(_schedule_with_early_rule(True), CHOL_HAMOED_FRIDAY)
    assert got.day.day_id == "chol_hamoed_pesach__friday"
    assert got.shabbos_start == at(CHOL_HAMOED_FRIDAY, "16:45")


def test_regular_shabbos_on_chol_hamoed_unless_the_house_chose_early():
    for schedule in (_schedule_with_early_rule(), _schedule_with_early_rule(False)):
        got = build(schedule, CHOL_HAMOED_FRIDAY)
        assert got.day.day_id == "chol_hamoed_pesach__friday"
        assert got.shabbos_start == at(CHOL_HAMOED_FRIDAY, "17:42")


def test_the_chol_hamoed_setting_holds_when_the_combination_is_switched_off():
    schedule = _schedule_with_early_rule(False)
    schedule["days"]["chol_hamoed_pesach__friday"]["enabled"] = False
    got = build(schedule, CHOL_HAMOED_FRIDAY)
    assert got.day.day_id == "chol_hamoed_pesach"
    assert got.shabbos_start == at(CHOL_HAMOED_FRIDAY, "17:42")


def test_the_chol_hamoed_setting_covers_succos_too():
    friday = date(2029, 9, 28)  # Chol Hamoed Succos on Friday
    assert build(_schedule_with_early_rule(True), friday).day.day_id == (
        "chol_hamoed_succos__friday"
    )
    assert build(_schedule_with_early_rule(True), friday).shabbos_start == at(friday, "16:45")
    assert build(_schedule_with_early_rule(False), friday).shabbos_start == at(friday, "17:42")


def test_the_chol_hamoed_setting_leaves_other_fridays_alone():
    got = build(_schedule_with_early_rule(False), FRIDAY)
    assert got.day.day_id == "friday"
    assert got.shabbos_start == at(FRIDAY, "16:45")


def test_early_shabbos_this_week_still_works_on_chol_hamoed():
    switch = {"kind": "early", "start": {"kind": "clock", "at": "16:00"}}
    got = build(_schedule_with_early_rule(False), CHOL_HAMOED_FRIDAY, one_week=switch)
    assert got.shabbos_start == at(CHOL_HAMOED_FRIDAY, "16:00")


# --- a date range that says "don't run" ----------------------------------------


def _summer_only(time):
    return {
        "kind": "by_rule",
        "rules": [{"when": {"kind": "date_range", "from": "06-01", "to": "08-31"}, "time": time}],
        "otherwise": {"kind": "dont_run"},
    }


def test_an_automation_is_left_out_on_a_date_its_range_says_dont_run():
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][0]["time"] = _summer_only(
        {"kind": "clock", "at": "07:30"}
    )
    assert times(build(schedule, TUESDAY))[0] == ("morning", at(TUESDAY, "07:30"))
    winter = date(2027, 1, 12)
    assert [a.id for a in build(schedule, winter).automations] == ["sunset", "night"]


def test_a_time_change_does_not_bring_back_an_automation_that_does_not_run():
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][0]["time"] = _summer_only(
        {"kind": "clock", "at": "07:30"}
    )
    winter = date(2027, 1, 12)
    change = {
        "id": "c1",
        "made_at": "2027-01-10T10:00:00+00:00",
        "from": winter.isoformat(),
        "until": winter.isoformat(),
        "days": "all",
        "kind": "time",
        "automation": "morning",
        "time": {"kind": "clock", "at": "09:00"},
    }
    got = build(schedule, winter, changes=[change])
    assert [a.id for a in got.automations] == ["sunset", "night"]
    assert got.skipped_changes == (("c1", "This day has no such automation"),)


def test_simcha_leaves_alone_a_night_that_does_not_run():
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][2]["time"] = _summer_only(
        {"kind": "clock", "at": "23:00"}
    )
    winter = date(2027, 1, 12)
    assert [a.id for a in build(schedule, winter, simcha=True).automations] == ["morning", "sunset"]


def test_an_alongside_automation_can_say_dont_run():
    schedule = make_schedule()
    schedule["alongside"][2]["time"] = {
        "kind": "by_rule",
        "rules": [],
        "otherwise": {"kind": "dont_run"},
    }
    for offset in range(400):
        day = date(2027, 1, 1) + timedelta(days=offset)
        assert "selichos" not in [a.id for a in build(schedule, day).automations]


# --- Erev Shabbos Hagadol --------------------------------------------------------

EREV_SHABBOS_HAGADOL = date(2027, 4, 16)


def test_erev_shabbos_hagadol_runs_its_own_day():
    got = build(make_schedule(), EREV_SHABBOS_HAGADOL)
    assert got.day.day_id == "erev_shabbos_hagadol"
    assert got.shabbos_start == at(EREV_SHABBOS_HAGADOL, "17:42")


def test_a_schedule_made_before_erev_shabbos_hagadol_runs_friday_on_that_date():
    schedule = make_schedule()
    del schedule["days"]["erev_shabbos_hagadol"]
    got = build(schedule, EREV_SHABBOS_HAGADOL)
    assert got.day.day_id == "friday"
    assert "erev_shabbos" in [a.id for a in got.automations]


def test_early_shabbos_rules_apply_on_erev_shabbos_hagadol():
    schedule = make_schedule()
    schedule["settings"]["early_shabbos_rules"] = [
        {"when": {"kind": "date_range", "from": "04-01", "to": "09-30"},
         "start": {"kind": "clock", "at": "17:00"}}
    ]
    assert build(schedule, EREV_SHABBOS_HAGADOL).shabbos_start == at(EREV_SHABBOS_HAGADOL, "17:00")
