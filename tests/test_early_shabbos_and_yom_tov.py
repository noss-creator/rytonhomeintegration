"""Early Shabbos never applies when the Shabbos that follows is Yom Tov.

Runs without Home Assistant, on the made-up schedule and zmanim of
tests/test_day_list.py: plag 16:45, candle lighting 17:42 on Fridays.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from .test_day_list import FRIDAY, at, build, make_schedule

ALL_YEAR_AT_PLAG = [
    {"when": {"kind": "date_range", "from": "01-01", "to": "12-31"},
     "start": {"kind": "zman", "zman": "plag"}}
]
EARLY, CANDLE_LIGHTING = "16:45", "17:42"


def _first_friday(schedule, occasion):
    """The first Friday from 2026 on which ``occasion`` falls."""
    day = date(2026, 1, 2)
    while day < date(2126, 1, 1):
        got = build(schedule, day)
        if got.day.occasion == occasion:
            return day, got
        day += timedelta(days=7)
    raise AssertionError(f"{occasion} never fell on a Friday")


def _always_early(yom_tov_days=2):
    schedule = make_schedule(yom_tov_days)
    schedule["settings"]["early_shabbos_rules"] = ALL_YEAR_AT_PLAG
    schedule["settings"]["early_shabbos_on_chol_hamoed"] = True
    return schedule


@pytest.mark.parametrize(
    "occasion",
    [
        "erev_rosh_hashana", "erev_yom_kippur", "erev_succos", "hoshana_rabba",
        "erev_pesach", "erev_shvii_pesach",
        # With two days of Yom Tov the Shabbos after these is the second day.
        "shvii_pesach", "shavuos_1",
    ],
)
@pytest.mark.parametrize("combination_on", [True, False])
def test_never_early_on_a_friday_before_a_yom_tov_shabbos(occasion, combination_on):
    schedule = _always_early()
    schedule["days"][f"{occasion}__friday"]["enabled"] = combination_on
    day, got = _first_friday(schedule, occasion)
    assert day.weekday() == 4
    assert got.shabbos_start == at(day, CANDLE_LIGHTING)
    # An ordinary Friday in the same schedule is early.
    assert build(schedule, FRIDAY).shabbos_start == at(FRIDAY, EARLY)


EARLY_THIS_WEEK = {"kind": "early", "start": {"kind": "zman", "zman": "plag"}}


@pytest.mark.parametrize(
    "occasion",
    [
        "erev_rosh_hashana", "erev_yom_kippur", "erev_succos", "hoshana_rabba",
        "erev_pesach", "erev_shvii_pesach",
    ],
)
def test_the_client_can_still_make_an_erev_yom_tov_friday_early(occasion):
    schedule = _always_early()
    day, _ = _first_friday(schedule, occasion)
    got = build(schedule, day, one_week=EARLY_THIS_WEEK)
    assert got.shabbos_start == at(day, EARLY)


# --- no early Shabbos at all on a Friday that is itself Yom Tov -------------


@pytest.mark.parametrize(
    "yom_tov_days,occasion",
    [
        (2, "rosh_hashana_2"), (2, "succos_2"), (2, "simchas_torah"),
        (2, "pesach_2"), (2, "shvii_pesach"), (2, "shavuos_1"),
        (1, "rosh_hashana_2"), (1, "shvii_pesach"), (1, "shavuos"),
    ],
)
@pytest.mark.parametrize("combination_on", [True, False])
def test_no_early_shabbos_on_a_friday_that_is_yom_tov(
    yom_tov_days, occasion, combination_on
):
    schedule = _always_early(yom_tov_days)
    schedule["days"][f"{occasion}__friday"]["enabled"] = combination_on
    day, got = _first_friday(schedule, occasion)
    assert day.weekday() == 4
    assert got.shabbos_start == at(day, CANDLE_LIGHTING)
    # Not even by the client's one-week switch.
    switched = build(schedule, day, one_week=EARLY_THIS_WEEK)
    assert switched.shabbos_start == at(day, CANDLE_LIGHTING)


def test_every_yom_tov_that_can_fall_on_friday_is_covered():
    """Any Friday whose occasion is Yom Tov starts Shabbos at candle lighting."""
    for yom_tov_days in (1, 2):
        schedule = _always_early(yom_tov_days)
        day, seen = date(2026, 1, 2), set()
        while day < date(2076, 1, 1):
            got = build(schedule, day)
            occasion = got.day.occasion
            yom_tov = occasion is not None and not occasion.startswith(
                ("erev_", "chol_hamoed", "hoshana", "purim", "bedikas", "day_before",
                 "tisha", "sunday")
            )
            if yom_tov:
                seen.add(occasion)
                assert got.shabbos_start == at(day, CANDLE_LIGHTING), (day, occasion)
            day += timedelta(days=7)
        assert len(seen) >= 3


@pytest.mark.parametrize("occasion", ["erev_succos", "hoshana_rabba", "erev_pesach"])
def test_one_day_house_is_never_early_before_a_yom_tov_shabbos(occasion):
    day, got = _first_friday(_always_early(yom_tov_days=1), occasion)
    assert got.shabbos_start == at(day, CANDLE_LIGHTING)
