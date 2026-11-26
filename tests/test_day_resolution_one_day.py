"""Day resolution for a house keeping one day of Yom Tov.

Runs without Home Assistant. Hebrew dates come from tests/hdate_source.py.
The expected identifiers below are typed out from SCHEDULE_FORMAT.md and
PLAN.md, not taken from the engine's table, so a mistake in the table shows.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pytest

from engine.day_resolver import resolve_day
from engine.day_tables import table_for

from .hdate_source import HdateSource

FIRST = date(1900, 1, 1)
LAST = date(2299, 12, 31)  # 400 years

STANDALONE = {
    "weekday", "friday", "shabbos", "shabbos_shuva", "shabbos_hagadol",
    "erev_shabbos_hagadol",
    "erev_rosh_hashana", "rosh_hashana_1", "rosh_hashana_2", "erev_yom_kippur",
    "yom_kippur", "erev_succos", "succos", "chol_hamoed_succos",
    "hoshana_rabba", "simchas_torah",
    "erev_purim", "purim",
    "bedikas_chametz", "erev_pesach", "pesach", "chol_hamoed_pesach",
    "erev_shvii_pesach", "shvii_pesach",
    "erev_shavuos", "shavuos",
    "erev_tisha_bav", "tisha_bav",
}

ON_FRIDAY = {
    "erev_rosh_hashana__friday", "rosh_hashana_2__friday",
    "erev_yom_kippur__friday", "erev_succos__friday",
    "chol_hamoed_succos__friday", "hoshana_rabba__friday", "purim__friday",
    "friday_before_erev_pesach_shabbos", "erev_pesach__friday",
    "chol_hamoed_pesach__friday", "erev_shvii_pesach__friday",
    "shvii_pesach__friday", "shavuos__friday",
}

ON_SHABBOS = {
    "rosh_hashana_1__shabbos", "succos__shabbos", "chol_hamoed_succos__shabbos",
    "simchas_torah__shabbos", "erev_purim__shabbos", "erev_pesach__shabbos",
    "pesach__shabbos", "chol_hamoed_pesach__shabbos", "shvii_pesach__shabbos",
    "erev_shavuos__shabbos", "erev_tisha_bav__shabbos",
    "tisha_bav_deferred__shabbos",
}

COMBINATIONS_REGULAR = ON_FRIDAY | ON_SHABBOS
COMBINATIONS_SHUSHAN = (COMBINATIONS_REGULAR - {"erev_purim__shabbos"}) | {
    "purim__shabbos", "erev_purim__friday", "sunday_after_purim_shabbos",
}

ALL_ON = lambda _id: True  # noqa: E731
ALL_OFF = lambda _id: False  # noqa: E731

SOURCE = HdateSource()


def _resolve_all(purim, is_enabled):
    table = table_for(1, purim)
    days = (FIRST + timedelta(days=n) for n in range((LAST - FIRST).days + 1))
    return [resolve_day(d, SOURCE, table, is_enabled) for d in days]


@pytest.fixture(scope="module")
def regular_on():
    return _resolve_all("regular", ALL_ON)


@pytest.fixture(scope="module")
def regular_off():
    return _resolve_all("regular", ALL_OFF)


@pytest.fixture(scope="module")
def shushan_on():
    return _resolve_all("shushan", ALL_ON)


def test_expected_lists_have_the_plans_counts():
    assert len(STANDALONE) == 28
    assert len(ON_FRIDAY) == 13
    assert len(ON_SHABBOS) == 12


def test_table_lists_exactly_the_plans_combinations():
    assert {c.id for c in table_for(1, "regular").combinations} == COMBINATIONS_REGULAR
    assert {c.id for c in table_for(1, "shushan").combinations} == COMBINATIONS_SHUSHAN


def test_every_date_in_400_years_resolves(regular_on, shushan_on):
    # _resolve_all raises UnresolvedDayError on any date the table cannot decide.
    assert len(regular_on) == len(shushan_on) == (LAST - FIRST).days + 1


def test_every_listed_combination_occurs_and_no_other(regular_on, shushan_on):
    assert {r.combination for r in regular_on} - {None} == COMBINATIONS_REGULAR
    assert {r.combination for r in shushan_on} - {None} == COMBINATIONS_SHUSHAN


def test_days_used_with_everything_switched_on(regular_on, shushan_on):
    assert {r.day_id for r in regular_on} == STANDALONE | COMBINATIONS_REGULAR
    assert {r.day_id for r in shushan_on} == STANDALONE | COMBINATIONS_SHUSHAN


def test_days_used_with_everything_switched_off(regular_off):
    assert {r.day_id for r in regular_off} == STANDALONE


def test_switched_off_combination_runs_the_occasions_own_day(regular_off):
    own_day_exceptions = {
        "friday_before_erev_pesach_shabbos": "friday",
        "tisha_bav_deferred__shabbos": "shabbos",
    }
    for r in regular_off:
        if r.combination is None:
            continue
        assert r.day_id == own_day_exceptions.get(r.combination, r.occasion)


def test_combination_falls_on_its_weekday(regular_on):
    for r in regular_on:
        if r.combination in ON_FRIDAY:
            assert r.date.weekday() == 4
        elif r.combination in ON_SHABBOS:
            assert r.date.weekday() == 5


def test_each_occasion_occurs_the_right_number_of_times_a_year(regular_on):
    per_year: dict[int, Counter] = {}
    for r in regular_on:
        counts = per_year.setdefault(SOURCE.hebrew_date(r.date).year, Counter())
        if r.occasion:
            counts[r.occasion] += 1
        if r.day_id in ("shabbos_shuva", "shabbos_hagadol", "erev_shabbos_hagadol"):
            counts[r.day_id] += 1

    full_years = sorted(per_year)[1:-1]
    assert len(full_years) >= 398
    once = STANDALONE - {
        "weekday", "friday", "shabbos", "shabbos_shuva", "shabbos_hagadol",
        "erev_shabbos_hagadol",
        "chol_hamoed_succos", "chol_hamoed_pesach", "erev_tisha_bav",
    }
    for year in full_years:
        c = per_year[year]
        for occasion in once:
            assert c[occasion] == 1, (year, occasion)
        assert c["chol_hamoed_succos"] == 5, year
        assert c["chol_hamoed_pesach"] == 4, year
        assert c["shabbos_shuva"] == 1, year
        assert c["erev_tisha_bav"] + c["tisha_bav_deferred"] == 1, year
        assert c["shabbos_hagadol"] + c["day_before_erev_pesach_shabbos"] == 1, year
        # The Friday before each Shabbos Hagadol that is not Erev Pesach.
        assert c["erev_shabbos_hagadol"] == c["shabbos_hagadol"], year


# Dates checked by hand against a printed calendar.
KNOWN = {
    # Tishrei 5787.
    date(2026, 9, 12): "rosh_hashana_1__shabbos",
    date(2026, 9, 13): "rosh_hashana_2",
    date(2026, 9, 25): "erev_succos__friday",
    date(2026, 9, 26): "succos__shabbos",
    date(2026, 9, 27): "chol_hamoed_succos",
    date(2026, 10, 2): "hoshana_rabba__friday",
    date(2026, 10, 3): "simchas_torah__shabbos",
    date(2026, 10, 4): "weekday",
    # Pesach 5787.
    date(2027, 4, 21): "erev_pesach",
    date(2027, 4, 22): "pesach",
    date(2027, 4, 23): "chol_hamoed_pesach__friday",
    date(2027, 4, 24): "chol_hamoed_pesach__shabbos",
    date(2027, 4, 27): "erev_shvii_pesach",
    date(2027, 4, 28): "shvii_pesach",
    date(2027, 4, 29): "weekday",
    # Pesach 5785: Erev Pesach on Shabbos, Shvii shel Pesach on Shabbos.
    date(2025, 4, 10): "bedikas_chametz",
    date(2025, 4, 11): "friday_before_erev_pesach_shabbos",
    date(2025, 4, 12): "erev_pesach__shabbos",
    date(2025, 4, 13): "pesach",
    date(2025, 4, 18): "erev_shvii_pesach__friday",
    date(2025, 4, 19): "shvii_pesach__shabbos",
    date(2025, 4, 20): "weekday",
    # Pesach 5782: Pesach on Shabbos, Shvii shel Pesach on Friday.
    date(2022, 4, 15): "erev_pesach__friday",
    date(2022, 4, 16): "pesach__shabbos",
    date(2022, 4, 22): "shvii_pesach__friday",
    date(2022, 4, 23): "shabbos",
    # Shavuos on Friday, and on Sunday.
    date(2026, 5, 22): "shavuos__friday",
    date(2026, 5, 23): "shabbos",
    date(2019, 6, 8): "erev_shavuos__shabbos",
    date(2019, 6, 9): "shavuos",
    date(2019, 6, 10): "weekday",
}


@pytest.mark.parametrize("day,expected", sorted(KNOWN.items()))
def test_known_dates(day, expected):
    assert resolve_day(day, SOURCE, table_for(1, "regular"), ALL_ON).day_id == expected
