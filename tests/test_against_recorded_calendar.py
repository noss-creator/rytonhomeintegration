"""The engine against events recorded from a real Jewish Calendar integration.

Runs without Home Assistant. The recording is small: three days of zmanim in
November 2026, Pesach week 2027 and Tishrei 5788. See tests/recorded.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from engine.day_resolver import resolve_day
from engine.day_tables import table_for
from engine.time_resolver import (
    ZmanUnavailableError,
    resolve_shabbos_start,
    resolve_time,
)

from .hdate_source import HdateSource
from .recorded_source import RecordedSource

TZ = ZoneInfo("Asia/Jerusalem")
RECORDED = RecordedSource()
HDATE = HdateSource()

THURSDAY = date(2026, 11, 26)
FRIDAY = date(2026, 11, 27)
SHABBOS = date(2026, 11, 28)


def at(day: date, clock: str) -> datetime:
    return datetime.combine(day, datetime.strptime(clock, "%H:%M:%S").time(), TZ)


# --- Hebrew dates ----------------------------------------------------------


@pytest.mark.parametrize("day", [THURSDAY, FRIDAY])
def test_hebrew_date_from_home_assistant_matches_the_test_stand_in(day):
    """The tests' hdate stand-in agrees with what Home Assistant reports."""
    assert RECORDED.hebrew_date(day) == HDATE.hebrew_date(day)


# --- zmanim and times ------------------------------------------------------


def test_zman_offsets_on_real_zmanim():
    before_shkia = {"kind": "zman", "zman": "shkia", "offset_minutes": -45}
    after_tzeis = {"kind": "zman", "zman": "tzeis", "offset_minutes": 5}
    assert resolve_time(before_shkia, FRIDAY, RECORDED, TZ) == at(FRIDAY, "15:50:00")
    assert resolve_time(after_tzeis, FRIDAY, RECORDED, TZ) == at(FRIDAY, "16:55:18")


def test_each_day_gets_its_own_zmanim():
    netz = {"kind": "zman", "zman": "netz"}
    assert resolve_time(netz, THURSDAY, RECORDED, TZ) == at(THURSDAY, "06:17:00")
    assert resolve_time(netz, FRIDAY, RECORDED, TZ) == at(FRIDAY, "06:18:00")
    assert resolve_time(netz, SHABBOS, RECORDED, TZ) == at(SHABBOS, "06:19:00")


def test_later_of_a_clock_time_and_a_real_zman():
    spec = {
        "kind": "later_of",
        "of": [{"kind": "clock", "at": "16:00"}, {"kind": "zman", "zman": "shkia"}],
    }
    assert resolve_time(spec, FRIDAY, RECORDED, TZ) == at(FRIDAY, "16:35:00")


def test_candle_lighting_exists_on_friday_and_havdalah_on_shabbos_only():
    candles = {"kind": "zman", "zman": "candle_lighting"}
    havdalah = {"kind": "zman", "zman": "havdalah"}
    assert resolve_time(candles, FRIDAY, RECORDED, TZ) == at(FRIDAY, "16:17:00")
    assert resolve_time(havdalah, SHABBOS, RECORDED, TZ) == at(SHABBOS, "17:47:00")
    with pytest.raises(ZmanUnavailableError):
        resolve_time(candles, THURSDAY, RECORDED, TZ)
    with pytest.raises(ZmanUnavailableError):
        resolve_time(havdalah, FRIDAY, RECORDED, TZ)


def test_shabbos_start_is_candle_lighting_with_no_matching_rule():
    plan_example = [
        {"when": {"kind": "zman_range", "zman": "shkia", "from": "18:30", "to": "19:15"},
         "start": {"kind": "zman", "zman": "plag"}},
        {"when": {"kind": "zman_range", "zman": "shkia", "from": "19:15"},
         "start": {"kind": "clock", "at": "19:00"}},
    ]
    got = resolve_shabbos_start(FRIDAY, RECORDED, TZ, plan_example)
    assert got == at(FRIDAY, "16:17:00")


def test_early_shabbos_at_the_real_plag():
    winter_at_plag = [
        {"when": {"kind": "clock_season", "season": "winter"},
         "start": {"kind": "zman", "zman": "plag"}}
    ]
    got = resolve_shabbos_start(FRIDAY, RECORDED, TZ, winter_at_plag)
    assert got == at(FRIDAY, "15:31:15")


def test_zman_range_rule_on_the_real_shkia():
    rule = [
        {"when": {"kind": "zman_range", "zman": "shkia", "from": "16:30", "to": "16:40"},
         "start": {"kind": "zman", "zman": "plag", "offset_minutes": 10}}
    ]
    got = resolve_shabbos_start(FRIDAY, RECORDED, TZ, rule)
    assert got == at(FRIDAY, "15:41:15")


# --- holidays --------------------------------------------------------------

# Home Assistant's holiday name -> the engine's occasion. None means the
# plan gives that holiday no day of its own.
HOLIDAY_NAMES = {
    "Erev Rosh Hashana": "erev_rosh_hashana",
    "Rosh Hashana I": "rosh_hashana_1",
    "Rosh Hashana II": "rosh_hashana_2",
    "Tzom Gedaliah": None,
    "Erev Yom Kippur": "erev_yom_kippur",
    "Yom Kippur": "yom_kippur",
    "Erev Sukkot": "erev_succos",
    "Sukkot": "succos_1",
    "Sukkot II": "succos_2",
    "Hol hamoed Sukkot": "chol_hamoed_succos",
    "Hoshana Raba": "hoshana_rabba",
    "Shmini Atzeret": "shmini_atzeres",
    "Simchat Torah": "simchas_torah",
    "Erev Pesach": "erev_pesach",
    "Pesach": "pesach_1",
    "Pesach II": "pesach_2",
}

# The spans of dates the yearly calendar was read for.
RECORDED_SPANS = [
    (date(2027, 4, 21), date(2027, 4, 23)),
    (date(2027, 10, 1), date(2027, 10, 25)),
]


def _recorded_days():
    for first, last in RECORDED_SPANS:
        day = first
        while day <= last:
            yield day
            day += timedelta(days=1)


@pytest.mark.parametrize("day", list(_recorded_days()))
def test_engine_agrees_with_home_assistant_on_every_recorded_date(day):
    """Where Home Assistant shows a holiday the engine has that occasion, and
    where it shows none the engine has none."""
    table = table_for(2, "regular")
    resolved = resolve_day(day, HDATE, table, lambda _id: True)
    holiday = RECORDED.holidays.get(day)
    expected = HOLIDAY_NAMES[holiday] if holiday else None
    assert resolved.occasion == expected


def test_recording_covers_a_whole_tishrei():
    seen = {RECORDED.holidays[d] for d in _recorded_days() if d in RECORDED.holidays}
    assert seen == set(HOLIDAY_NAMES)
