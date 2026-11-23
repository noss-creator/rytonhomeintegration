"""Which automations a run-through carries out. Runs without Home Assistant."""

from __future__ import annotations

from datetime import date, timedelta

from engine.day_list import build_day_list
from engine.run_through import automations_of_dates, every_automation

from .test_day_list import SOURCE, TZ, make_schedule


def test_every_automation_of_every_day_then_the_alongside_ones():
    schedule = make_schedule()
    items = every_automation(schedule)
    in_days = sum(len(day["automations"]) for day in schedule["days"].values())
    assert len(items) == in_days + len(schedule["alongside"])
    assert {item.label for item in items} == set(schedule["days"]) | {"alongside"}
    assert [item.automation_id for item in items[:3]] == ["morning", "sunset", "night"]
    assert [item.automation_id for item in items[-3:]] == [
        "sefiras_haomer", "chanukah_candle_lighting", "selichos",
    ]


def test_switched_off_combination_days_are_included():
    schedule = make_schedule()
    schedule["days"]["succos_1__shabbos"]["enabled"] = False
    labels = {item.label for item in every_automation(schedule)}
    assert "succos_1__shabbos" in labels


def test_each_automation_carries_its_own_rooms():
    items = every_automation(make_schedule())
    friday = [item for item in items if item.label == "friday"]
    assert [item.automation_id for item in friday] == [
        "morning", "erev_shabbos", "sunset", "night",
    ]
    assert friday[1].rooms == {"hall": {"scene": "scene.friday"}}


def _lists(first, days):
    schedule = make_schedule()
    return [
        build_day_list(schedule, first + timedelta(days=n), SOURCE, TZ)
        for n in range(days)
    ]


def test_a_span_of_dates_in_time_order():
    items = automations_of_dates(_lists(date(2027, 6, 17), 2), each_day_once=False)
    assert [(item.label, item.automation_id) for item in items] == [
        ("2027-06-17 weekday", "morning"),
        ("2027-06-17 weekday", "sunset"),
        ("2027-06-17 weekday", "night"),
        ("2027-06-18 friday", "morning"),
        ("2027-06-18 friday", "erev_shabbos"),
        ("2027-06-18 friday", "sunset"),
        ("2027-06-18 friday", "night"),
    ]


def test_each_kind_of_day_once_over_a_fortnight():
    lists = _lists(date(2027, 6, 14), 14)
    all_of_them = automations_of_dates(lists, each_day_once=False)
    once = automations_of_dates(lists, each_day_once=True)
    assert len(all_of_them) == 10 * 3 + 2 * 4 + 2 * 3  # weekdays, Fridays, Shabbosos
    assert [item.label for item in once if item.automation_id == "morning"] == [
        "2027-06-14 weekday", "2027-06-18 friday", "2027-06-19 shabbos",
    ]


def test_alongside_automations_of_a_date_are_included():
    items = automations_of_dates(_lists(date(2027, 5, 4), 1), each_day_once=True)
    assert "sefiras_haomer" in [item.automation_id for item in items]
