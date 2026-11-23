"""The dates of the running-alongside automations.

Runs without Home Assistant. Hebrew dates come from tests/hdate_source.py.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from engine.alongside import alongside_for

from .hdate_source import HdateSource

FIRST = date(1900, 1, 1)
LAST = date(2299, 12, 31)  # 400 years

SOURCE = HdateSource()

OFF = {"from_motzei_shabbos": False, "from_elul": False}
MOTZEI_SHABBOS = {"from_motzei_shabbos": True, "from_elul": False}
ELUL = {"from_motzei_shabbos": False, "from_elul": True}
BOTH = {"from_motzei_shabbos": True, "from_elul": True}


def _all_days():
    return [FIRST + timedelta(days=n) for n in range((LAST - FIRST).days + 1)]


def _runs(automation_id, selichos=OFF, gap=1):
    """Group the dates an automation applies on into runs.

    Dates no more than ``gap`` days apart belong to one run.
    """
    runs: list[list[date]] = []
    for day in _all_days():
        if any(a.id == automation_id for a in alongside_for(day, SOURCE, selichos)):
            if runs and (day - runs[-1][-1]).days <= gap:
                runs[-1].append(day)
            else:
                runs.append([day])
    return runs[1:-1]  # the first and last may be cut off by the range


def _hebrew(day):
    h = SOURCE.hebrew_date(day)
    return (h.month, h.day)


def _ids(day, selichos=OFF):
    return [(a.id, a.time_key) for a in alongside_for(day, SOURCE, selichos)]


# --- Sefiras haomer --------------------------------------------------------


@pytest.fixture(scope="module")
def omer_runs():
    return _runs("sefiras_haomer")


def test_omer_is_49_evenings_in_a_row_every_year(omer_runs):
    assert len(omer_runs) >= 398
    for run in omer_runs:
        assert len(run) == 49
        assert (run[-1] - run[0]).days == 48


def test_omer_starts_the_second_night_of_pesach_and_ends_before_erev_shavuos(omer_runs):
    for run in omer_runs:
        assert _hebrew(run[0]) == ("nisan", 15)
        assert _hebrew(run[-1]) == ("sivan", 4)
        assert _hebrew(run[-1] + timedelta(days=1)) == ("sivan", 5)


def test_omer_known_dates():
    assert _ids(date(2027, 4, 21)) == []  # Erev Pesach, the first Seder night
    assert _ids(date(2027, 4, 22)) == [("sefiras_haomer", None)]
    assert _ids(date(2027, 6, 9)) == [("sefiras_haomer", None)]
    assert _ids(date(2027, 6, 10)) == []  # Erev Shavuos


# --- Chanukah --------------------------------------------------------------


@pytest.fixture(scope="module")
def chanukah_runs():
    return _runs("chanukah_candle_lighting")


def test_chanukah_is_eight_evenings_in_a_row_every_year(chanukah_runs):
    assert len(chanukah_runs) >= 398
    for run in chanukah_runs:
        assert len(run) == 8
        assert (run[-1] - run[0]).days == 7
        assert _hebrew(run[0]) == ("kislev", 24)


def test_chanukah_ends_on_1_or_2_teves(chanukah_runs):
    last_days = {_hebrew(run[-1]) for run in chanukah_runs}
    assert last_days == {("teves", 1), ("teves", 2)}


def test_chanukah_time_follows_the_weekday(chanukah_runs):
    for run in chanukah_runs:
        keys = []
        for day in run:
            [(_, key)] = _ids(day)
            expected = {4: "friday", 5: "motzei_shabbos"}.get(day.weekday(), "weeknight")
            assert key == expected
            keys.append(key)
        # Eight evenings in a row always hold a Friday and a motzei Shabbos.
        assert "friday" in keys and "motzei_shabbos" in keys


def test_chanukah_known_dates():
    assert _ids(date(2026, 12, 3)) == []
    assert _ids(date(2026, 12, 4)) == [("chanukah_candle_lighting", "friday")]
    assert _ids(date(2026, 12, 5)) == [("chanukah_candle_lighting", "motzei_shabbos")]
    assert _ids(date(2026, 12, 6)) == [("chanukah_candle_lighting", "weeknight")]
    assert _ids(date(2026, 12, 11)) == [("chanukah_candle_lighting", "friday")]
    assert _ids(date(2026, 12, 12)) == []


# --- Selichos --------------------------------------------------------------
# A year's Selichos dates are one run once Shabbos and Rosh Hashana, which
# are skipped, are bridged: the longest gap is Erev Rosh Hashana on Wednesday,
# Rosh Hashana on Thursday and Friday, then Shabbos, then Sunday (four days
# apart).


@pytest.fixture(scope="module")
def from_motzei_shabbos_runs():
    return _runs("selichos", MOTZEI_SHABBOS, gap=4)


@pytest.fixture(scope="module")
def from_elul_runs():
    return _runs("selichos", ELUL, gap=4)


def test_selichos_never_runs_with_both_toggles_off():
    assert _runs("selichos", OFF, gap=4) == []


def test_selichos_never_on_shabbos_or_rosh_hashana(from_motzei_shabbos_runs, from_elul_runs):
    for run in from_motzei_shabbos_runs + from_elul_runs:
        for day in run:
            assert day.weekday() != 5
            assert _hebrew(day) not in (("tishrei", 1), ("tishrei", 2))


def test_selichos_runs_through_erev_yom_kippur(from_motzei_shabbos_runs, from_elul_runs):
    assert len(from_motzei_shabbos_runs) >= 398
    assert len(from_elul_runs) >= 398
    for run in from_motzei_shabbos_runs + from_elul_runs:
        assert _hebrew(run[-1]) == ("tishrei", 9)


def test_selichos_runs_on_every_day_in_the_period_but_shabbos_and_rosh_hashana(
    from_elul_runs,
):
    for run in from_elul_runs:
        said = set(run)
        day = run[0]
        while day <= run[-1]:
            skipped = day.weekday() == 5 or _hebrew(day) in (
                ("tishrei", 1), ("tishrei", 2),
            )
            assert (day in said) is not skipped, day
            day += timedelta(days=1)


def test_selichos_from_elul_starts_on_1_elul(from_elul_runs):
    for run in from_elul_runs:
        first = run[0]
        if _hebrew(first) == ("elul", 2):
            # 1 Elul was Shabbos.
            assert first.weekday() == 6
        else:
            assert _hebrew(first) == ("elul", 1)


def test_selichos_from_motzei_shabbos_starts_on_the_right_sunday(
    from_motzei_shabbos_runs,
):
    days_before = set()
    for run in from_motzei_shabbos_runs:
        first = run[0]
        assert first.weekday() == 6
        rosh_hashana = next(d for d in _span(first, 10) if _hebrew(d) == ("tishrei", 1))
        days_before.add((rosh_hashana.weekday(), (rosh_hashana - first).days))
    # Rosh Hashana on Monday, Tuesday, Thursday, Shabbos: days from the first Sunday.
    assert days_before == {(0, 8), (1, 9), (3, 4), (5, 6)}


def _span(first, days):
    return [first + timedelta(days=n) for n in range(days + 1)]


def test_selichos_with_both_toggles_is_the_same_as_from_elul(from_elul_runs):
    assert _runs("selichos", BOTH, gap=4) == from_elul_runs


def test_selichos_known_dates():
    said = [("selichos", None)]
    # Rosh Hashana on Shabbos 2 October 2027: Selichos from Sunday 26 September.
    assert _ids(date(2027, 9, 25), MOTZEI_SHABBOS) == []
    assert _ids(date(2027, 9, 26), MOTZEI_SHABBOS) == said
    assert _ids(date(2027, 10, 1), MOTZEI_SHABBOS) == said  # Erev Rosh Hashana, Friday
    assert _ids(date(2027, 10, 2), MOTZEI_SHABBOS) == []  # Rosh Hashana
    assert _ids(date(2027, 10, 3), MOTZEI_SHABBOS) == []  # Rosh Hashana
    assert _ids(date(2027, 10, 4), MOTZEI_SHABBOS) == said  # Tzom Gedaliah
    assert _ids(date(2027, 10, 8), MOTZEI_SHABBOS) == said  # Friday
    assert _ids(date(2027, 10, 9), MOTZEI_SHABBOS) == []  # Shabbos Shuva
    assert _ids(date(2027, 10, 10), MOTZEI_SHABBOS) == said  # Erev Yom Kippur
    assert _ids(date(2027, 10, 11), MOTZEI_SHABBOS) == []  # Yom Kippur
    # Rosh Hashana on Tuesday 23 September 2025: a week earlier, Sunday 14 September.
    assert _ids(date(2025, 9, 13), MOTZEI_SHABBOS) == []
    assert _ids(date(2025, 9, 14), MOTZEI_SHABBOS) == said
    # Rosh Hashana on Thursday 3 October 2024: Sunday 29 September.
    assert _ids(date(2024, 9, 28), MOTZEI_SHABBOS) == []
    assert _ids(date(2024, 9, 29), MOTZEI_SHABBOS) == said
    # From Elul: a weekday early in Elul 5787 (1 Elul is 3 September 2027).
    assert _ids(date(2027, 9, 2), ELUL) == []
    assert _ids(date(2027, 9, 3), ELUL) == said
    assert _ids(date(2027, 9, 3), MOTZEI_SHABBOS) == []


def test_nothing_applies_on_an_ordinary_date():
    assert _ids(date(2027, 1, 12), BOTH) == []
