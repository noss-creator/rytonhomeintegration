"""Day resolution for a house keeping two days of Yom Tov.

Runs without Home Assistant. Hebrew dates come from tests/hdate_source.py.
The expected identifiers below are typed out from SCHEDULE_FORMAT.md and
PLAN.md, not taken from the engine's table, so a mistake in the table shows.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pytest

from engine.day_resolver import (
    UnresolvedDayError,
    resolve_day,
)
from engine.day_tables import table_for

from .hdate_source import HdateSource

FIRST = date(1900, 1, 1)
LAST = date(2299, 12, 31)  # 400 years

STANDALONE = {
    "weekday", "friday", "shabbos", "shabbos_shuva", "shabbos_hagadol",
    "erev_rosh_hashana", "rosh_hashana_1", "rosh_hashana_2", "erev_yom_kippur",
    "yom_kippur", "erev_succos", "succos_1", "succos_2", "chol_hamoed_succos",
    "hoshana_rabba", "shmini_atzeres", "simchas_torah",
    "erev_purim", "purim",
    "bedikas_chametz", "erev_pesach", "pesach_1", "pesach_2",
    "chol_hamoed_pesach", "erev_shvii_pesach", "shvii_pesach", "acharon_pesach",
    "erev_shavuos", "shavuos_1", "shavuos_2",
    "erev_tisha_bav", "tisha_bav",
}

ON_FRIDAY = {
    "erev_rosh_hashana__friday", "rosh_hashana_2__friday",
    "erev_yom_kippur__friday", "erev_succos__friday", "succos_2__friday",
    "chol_hamoed_succos__friday", "hoshana_rabba__friday",
    "simchas_torah__friday", "purim__friday", "erev_pesach__friday",
    "pesach_2__friday", "chol_hamoed_pesach__friday",
    "erev_shvii_pesach__friday", "shvii_pesach__friday", "shavuos_1__friday",
    "friday_before_erev_pesach_shabbos",
}

ON_SHABBOS = {
    "rosh_hashana_1__shabbos", "succos_1__shabbos",
    "chol_hamoed_succos__shabbos", "shmini_atzeres__shabbos",
    "erev_purim__shabbos", "erev_pesach__shabbos", "pesach_1__shabbos",
    "chol_hamoed_pesach__shabbos", "shvii_pesach__shabbos",
    "acharon_pesach__shabbos", "erev_shavuos__shabbos", "shavuos_2__shabbos",
    "erev_tisha_bav__shabbos", "tisha_bav_deferred__shabbos",
}

COMBINATIONS_REGULAR = ON_FRIDAY | ON_SHABBOS
COMBINATIONS_SHUSHAN = (COMBINATIONS_REGULAR - {"erev_purim__shabbos"}) | {
    "purim__shabbos", "erev_purim__friday", "sunday_after_purim_shabbos",
}

ALL_ON = lambda _id: True  # noqa: E731
ALL_OFF = lambda _id: False  # noqa: E731

SOURCE = HdateSource()


def _days():
    day = FIRST
    while day <= LAST:
        yield day
        day += timedelta(days=1)


def _resolve_all(purim, is_enabled):
    table = table_for(2, purim)
    return [resolve_day(d, SOURCE, table, is_enabled) for d in _days()]


@pytest.fixture(scope="module")
def regular_on():
    return _resolve_all("regular", ALL_ON)


@pytest.fixture(scope="module")
def regular_off():
    return _resolve_all("regular", ALL_OFF)


@pytest.fixture(scope="module")
def shushan_on():
    return _resolve_all("shushan", ALL_ON)


@pytest.fixture(scope="module")
def shushan_off():
    return _resolve_all("shushan", ALL_OFF)


def test_expected_lists_have_the_plans_counts():
    assert len(STANDALONE) == 32
    assert len(ON_FRIDAY) == 16
    assert len(ON_SHABBOS) == 14
    assert len(COMBINATIONS_SHUSHAN) == 32  # 31, plus the Sunday after Purim


def test_table_lists_exactly_the_plans_combinations():
    assert {c.id for c in table_for(2, "regular").combinations} == COMBINATIONS_REGULAR
    assert {c.id for c in table_for(2, "shushan").combinations} == COMBINATIONS_SHUSHAN


def test_every_date_in_400_years_resolves(regular_on, shushan_on):
    # _resolve_all raises UnresolvedDayError on any date the table cannot decide.
    assert len(regular_on) == len(shushan_on) == (LAST - FIRST).days + 1


def test_every_listed_combination_occurs_and_no_other(regular_on, shushan_on):
    assert {r.combination for r in regular_on} - {None} == COMBINATIONS_REGULAR
    assert {r.combination for r in shushan_on} - {None} == COMBINATIONS_SHUSHAN


def test_days_used_with_everything_switched_on(regular_on, shushan_on):
    assert {r.day_id for r in regular_on} == STANDALONE | COMBINATIONS_REGULAR
    assert {r.day_id for r in shushan_on} == STANDALONE | COMBINATIONS_SHUSHAN


def test_days_used_with_everything_switched_off(regular_off, shushan_off):
    assert {r.day_id for r in regular_off} == STANDALONE
    assert {r.day_id for r in shushan_off} == STANDALONE


def test_switched_off_combination_runs_the_occasions_own_day(regular_off):
    own_day_exceptions = {
        "friday_before_erev_pesach_shabbos": "friday",
        "tisha_bav_deferred__shabbos": "shabbos",
    }
    for r in regular_off:
        if r.combination is None:
            continue
        assert r.combination_enabled is False
        assert r.day_id == own_day_exceptions.get(r.combination, r.occasion)


def test_combination_falls_on_its_weekday(shushan_on, regular_on):
    for r in regular_on + shushan_on:
        if r.combination is None:
            continue
        if r.combination == "sunday_after_purim_shabbos":
            assert r.date.weekday() == 6
        elif r.combination in ON_SHABBOS or r.combination == "purim__shabbos":
            assert r.date.weekday() == 5
        else:
            assert r.date.weekday() == 4


def test_plain_days_fall_on_their_weekdays(regular_on):
    for r in regular_on:
        if r.day_id == "weekday":
            assert r.date.weekday() in (6, 0, 1, 2, 3)
        elif r.day_id == "friday":
            assert r.date.weekday() == 4
        elif r.day_id in ("shabbos", "shabbos_shuva", "shabbos_hagadol"):
            assert r.date.weekday() == 5
        elif r.day_id in STANDALONE and r.day_id != "yom_kippur":
            # A standalone occasion's own day only runs Sunday to Thursday
            # while every combination is switched on.
            assert r.date.weekday() in (6, 0, 1, 2, 3), r


def test_each_occasion_occurs_the_right_number_of_times_a_year(regular_on):
    per_year: dict[int, Counter] = {}
    for r in regular_on:
        year = SOURCE.hebrew_date(r.date).year
        counts = per_year.setdefault(year, Counter())
        if r.occasion:
            counts[r.occasion] += 1
        if r.day_id in ("shabbos_shuva", "shabbos_hagadol"):
            counts[r.day_id] += 1

    full_years = sorted(per_year)[1:-1]
    assert len(full_years) >= 398
    once = STANDALONE - {
        "weekday", "friday", "shabbos", "shabbos_shuva", "shabbos_hagadol",
        "chol_hamoed_succos", "chol_hamoed_pesach", "erev_tisha_bav",
    }
    for year in full_years:
        c = per_year[year]
        for occasion in once:
            assert c[occasion] == 1, (year, occasion)
        assert c["chol_hamoed_succos"] == 4, year
        assert c["chol_hamoed_pesach"] == 3, year
        assert c["shabbos_shuva"] == 1, year
        # 9 Av on Shabbos: no Erev Tisha B'Av day, and the fast is on Sunday.
        assert c["erev_tisha_bav"] + c["tisha_bav_deferred"] == 1, year
        # Erev Pesach on Shabbos is itself Shabbos Hagadol.
        assert c["shabbos_hagadol"] + c["day_before_erev_pesach_shabbos"] == 1, year


def test_first_adar_of_a_leap_year_has_no_purim(regular_on):
    seen = 0
    for r in regular_on:
        if SOURCE.hebrew_date(r.date).month == "adar_1":
            seen += 1
            assert r.day_id in ("weekday", "friday", "shabbos")
    assert seen > 0


# Dates checked by hand against a printed calendar.
KNOWN_REGULAR = {
    # Tishrei 5787: Rosh Hashana on Shabbos and Sunday.
    date(2026, 9, 11): "erev_rosh_hashana__friday",
    date(2026, 9, 12): "rosh_hashana_1__shabbos",
    date(2026, 9, 13): "rosh_hashana_2",
    date(2026, 9, 19): "shabbos_shuva",
    date(2026, 9, 20): "erev_yom_kippur",
    date(2026, 9, 21): "yom_kippur",
    date(2026, 9, 25): "erev_succos__friday",
    date(2026, 9, 26): "succos_1__shabbos",
    date(2026, 9, 27): "succos_2",
    date(2026, 9, 28): "chol_hamoed_succos",
    date(2026, 10, 2): "hoshana_rabba__friday",
    date(2026, 10, 3): "shmini_atzeres__shabbos",
    date(2026, 10, 4): "simchas_torah",
    date(2026, 10, 5): "weekday",
    # Yom Kippur on Shabbos.
    date(2024, 10, 11): "erev_yom_kippur__friday",
    date(2024, 10, 12): "yom_kippur",
    # Purim and Pesach 5787, a leap year.
    date(2027, 3, 22): "erev_purim",
    date(2027, 3, 23): "purim",
    date(2027, 4, 17): "shabbos_hagadol",
    date(2027, 4, 20): "bedikas_chametz",
    date(2027, 4, 21): "erev_pesach",
    date(2027, 4, 22): "pesach_1",
    date(2027, 4, 23): "pesach_2__friday",
    date(2027, 4, 24): "chol_hamoed_pesach__shabbos",
    date(2027, 4, 27): "erev_shvii_pesach",
    date(2027, 4, 28): "shvii_pesach",
    date(2027, 4, 29): "acharon_pesach",
    date(2027, 4, 30): "friday",
    # Erev Pesach on Shabbos, 5785.
    date(2025, 4, 10): "bedikas_chametz",
    date(2025, 4, 11): "friday_before_erev_pesach_shabbos",
    date(2025, 4, 12): "erev_pesach__shabbos",
    date(2025, 4, 13): "pesach_1",
    # Purim on Friday, and Purim on Sunday.
    date(2021, 2, 25): "erev_purim",
    date(2021, 2, 26): "purim__friday",
    date(2024, 3, 23): "erev_purim__shabbos",
    date(2024, 3, 24): "purim",
    # Shavuos on Friday and Shabbos, and on Sunday and Monday.
    date(2026, 5, 21): "erev_shavuos",
    date(2026, 5, 22): "shavuos_1__friday",
    date(2026, 5, 23): "shavuos_2__shabbos",
    date(2019, 6, 8): "erev_shavuos__shabbos",
    date(2019, 6, 9): "shavuos_1",
    date(2019, 6, 10): "shavuos_2",
    # 9 Av on Shabbos, fast on Sunday.
    date(2022, 8, 5): "friday",
    date(2022, 8, 6): "tisha_bav_deferred__shabbos",
    date(2022, 8, 7): "tisha_bav",
    # 9 Av on Sunday.
    date(2025, 8, 2): "erev_tisha_bav__shabbos",
    date(2025, 8, 3): "tisha_bav",
}

KNOWN_SHUSHAN = {
    date(2021, 2, 26): "erev_purim__friday",
    date(2021, 2, 27): "purim__shabbos",
    date(2021, 2, 28): "sunday_after_purim_shabbos",
    date(2027, 3, 23): "erev_purim",
    date(2027, 3, 24): "purim",
    date(2027, 3, 25): "weekday",
}

KNOWN_REGULAR_OFF = {
    date(2026, 9, 11): "erev_rosh_hashana",
    date(2026, 9, 26): "succos_1",
    date(2025, 4, 11): "friday",
    date(2025, 4, 12): "erev_pesach",
    date(2022, 8, 6): "shabbos",
}


@pytest.mark.parametrize("day,expected", sorted(KNOWN_REGULAR.items()))
def test_known_dates(day, expected):
    assert resolve_day(day, SOURCE, table_for(2, "regular"), ALL_ON).day_id == expected


@pytest.mark.parametrize("day,expected", sorted(KNOWN_SHUSHAN.items()))
def test_known_dates_shushan_purim(day, expected):
    assert resolve_day(day, SOURCE, table_for(2, "shushan"), ALL_ON).day_id == expected


@pytest.mark.parametrize("day,expected", sorted(KNOWN_REGULAR_OFF.items()))
def test_known_dates_switched_off(day, expected):
    assert resolve_day(day, SOURCE, table_for(2, "regular"), ALL_OFF).day_id == expected


def test_sunday_after_purim_runs_as_weekday_when_off():
    table = table_for(2, "shushan")
    assert resolve_day(date(2021, 2, 28), SOURCE, table, ALL_OFF).day_id == "weekday"


def test_unlisted_overlap_is_flagged():
    """A Friday occasion with no combination must raise, not pick silently."""
    full = table_for(2, "regular")
    trimmed = type(full)(
        full.occasions,
        full.shabbos_variants,
        tuple(c for c in full.combinations if c.id != "purim__friday"),
        full.uncombined,
    )
    with pytest.raises(UnresolvedDayError):
        resolve_day(date(2021, 2, 26), SOURCE, trimmed, ALL_ON)
