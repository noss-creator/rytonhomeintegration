"""Reading the Jewish Calendar's events into a calendar source.

Runs without Home Assistant, on events recorded from the test installation
(tests/recorded/jewish_calendar_events.json).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from engine import calendar_source as cs
from engine.calendar_snapshot import (
    CalendarDataError,
    parse_events,
    parse_hebrew_date,
    zman_key,
)
from engine.time_resolver import resolve_time

from .hdate_source import HdateSource

TZ = ZoneInfo("Asia/Jerusalem")
RECORDED = json.loads(
    (Path(__file__).parent / "recorded" / "jewish_calendar_events.json").read_text(
        encoding="utf-8"
    )
)
FEBRUARY = RECORDED["service_daily_2027_02"]["events"]
FEB_7 = date(2027, 2, 7)
FEB_8 = date(2027, 2, 8)


def local(day: date, clock: str) -> datetime:
    return datetime.combine(day, datetime.strptime(clock, "%H:%M:%S").time(), TZ)


# --- a real service response ----------------------------------------------


def test_real_response_gives_the_hebrew_date():
    snapshot = parse_events(FEBRUARY, [], TZ, FEB_7, FEB_7)
    assert snapshot.hebrew_date(FEB_7) == cs.HebrewDate(5787, cs.SHEVAT, 30)
    assert snapshot.hebrew_date(FEB_7) == HdateSource().hebrew_date(FEB_7)


def test_real_response_gives_every_selected_zman_in_house_time():
    """The service answers in UTC; the engine gets the house's local time."""
    snapshot = parse_events(FEBRUARY, [], TZ, FEB_7, FEB_7)
    expected = {
        "alos": "05:14:00",
        "netz": "06:29:00",
        "chatzos": "11:53:00",
        "mincha_gedola": "12:20:00",
        "mincha_ketana": "15:02:00",
        "plag": "16:10:30",
        "shkia": "17:18:00",
        "tzeis": "17:34:12",
    }
    for key, clock in expected.items():
        got = snapshot.zman(FEB_7, key)
        assert got == local(FEB_7, clock), key
        assert got.utcoffset().total_seconds() == 2 * 3600


def test_zman_not_returned_that_day_is_none():
    snapshot = parse_events(FEBRUARY, [], TZ, FEB_7, FEB_7)
    assert snapshot.zman(FEB_7, "candle_lighting") is None  # a Sunday
    assert snapshot.zman(FEB_7, "sof_zman_shema_gra") is None  # not selected


def test_time_resolver_runs_on_the_snapshot():
    snapshot = parse_events(FEBRUARY, [], TZ, FEB_7, FEB_7)
    spec = {"kind": "zman", "zman": "shkia", "offset_minutes": -30}
    assert resolve_time(spec, FEB_7, snapshot, TZ) == local(FEB_7, "16:48:00")


def test_a_date_with_no_hebrew_date_is_refused():
    """8 February came back with zmanim but no Hebrew date."""
    with pytest.raises(CalendarDataError):
        parse_events(FEBRUARY, [], TZ, FEB_7, FEB_8)


def test_asking_outside_the_dates_read_is_an_error_not_a_guess():
    snapshot = parse_events(FEBRUARY, [], TZ, FEB_7, FEB_7)
    with pytest.raises(CalendarDataError):
        snapshot.hebrew_date(FEB_8)
    with pytest.raises(CalendarDataError):
        snapshot.zman(FEB_8, "shkia")


# --- both calendars together ----------------------------------------------


def test_daily_and_yearly_events_together():
    friday, thursday = date(2026, 11, 27), date(2026, 11, 26)
    snapshot = parse_events(RECORDED["daily"], RECORDED["yearly"], TZ, thursday, friday)
    assert snapshot.hebrew_date(friday) == cs.HebrewDate(5787, cs.KISLEV, 17)
    assert snapshot.zman(friday, "candle_lighting") == local(friday, "16:17:00")
    assert snapshot.zman(thursday, "candle_lighting") is None
    assert snapshot.zman(friday, "plag") == local(friday, "15:31:15")


def test_holiday_and_other_all_day_events_are_not_mistaken_for_dates():
    events = [
        {"start": "2027-10-02", "summary": "Rosh Hashana I"},
        {"start": "2027-10-02", "summary": "1 of the Omer"},
        {"start": "2027-10-02", "summary": "1 Tishrei 5788"},
    ]
    snapshot = parse_events(events, [], TZ, date(2027, 10, 2), date(2027, 10, 2))
    assert snapshot.hebrew_date(date(2027, 10, 2)) == cs.HebrewDate(5788, cs.TISHREI, 1)


def test_a_zman_after_midnight_utc_lands_on_the_local_date():
    events = [
        {"start": "2027-06-18", "summary": "13 Sivan 5787"},
        # 22:30 UTC on the 17th is 01:30 on the 18th in Jerusalem summer time.
        {"start": "2027-06-17T22:30:00+00:00", "summary": "Alot HaShachar"},
    ]
    day = date(2027, 6, 18)
    snapshot = parse_events(events, [], TZ, day, day)
    assert snapshot.zman(day, "alos") == local(day, "01:30:00")


def test_a_time_with_no_timezone_is_refused():
    events = [
        {"start": "2027-02-07", "summary": "30 Sh'vat 5787"},
        {"start": "2027-02-07T17:18:00", "summary": "Shkia"},
    ]
    with pytest.raises(CalendarDataError):
        parse_events(events, [], TZ, FEB_7, FEB_7)


# --- the four sof zman events, as Home Assistant really writes them ---------


def test_real_sof_zman_events_are_read():
    friday = date(2026, 11, 27)
    events = [{"start": "2026-11-27", "summary": "17 Kislev 5787"}]
    events += RECORDED["sof_zman_2026_11_27"]["events"]
    snapshot = parse_events(events, [], TZ, friday, friday)
    assert snapshot.zman(friday, "sof_zman_shema_mga") == local(friday, "08:13:30")
    assert snapshot.zman(friday, "sof_zman_shema_gra") == local(friday, "08:51:00")
    assert snapshot.zman(friday, "sof_zman_tefilla_mga") == local(friday, "09:17:40")
    assert snapshot.zman(friday, "sof_zman_tefilla_gra") == local(friday, "09:42:00")


# --- every month name, as Home Assistant really writes it -------------------

_REAL_DATES = (
    RECORDED["hebrew_dates"]["events"]
    + [e for e in RECORDED["daily"] if "T" not in e["start"]]
    + [e for e in FEBRUARY if "T" not in e["start"]]
)


@pytest.mark.parametrize("event", _REAL_DATES, ids=lambda e: e["summary"])
def test_real_hebrew_date_is_read_and_agrees_with_the_test_stand_in(event):
    day = date.fromisoformat(event["start"])
    read = parse_hebrew_date(event["summary"])
    assert read is not None
    assert read == HdateSource().hebrew_date(day)


def test_all_fourteen_month_names_were_seen_on_a_real_installation():
    months = {parse_hebrew_date(e["summary"]).month for e in _REAL_DATES}
    assert months == set(cs.MONTHS)


# --- the text of events ----------------------------------------------------


@pytest.mark.parametrize(
    "summary,key",
    [
        ("Alot HaShachar", "alos"),
        ("Plag Hamincha", "plag"),
        ("Tset Hakochavim (18 minutes)", "tzeis"),
        ("Candle Lighting", "candle_lighting"),
        ("Havdalah", "havdalah"),
        ("Shkia", "shkia"),
        ("Rosh Hashana I", None),
        ("Ha'Azinu", None),
        ("Shkiaa", None),
    ],
)
def test_zman_key(summary, key):
    assert zman_key(summary) == key


@pytest.mark.parametrize(
    "summary,expected",
    [
        ("17 Kislev 5787", cs.HebrewDate(5787, cs.KISLEV, 17)),
        ("30 Sh'vat 5787", cs.HebrewDate(5787, cs.SHEVAT, 30)),
        ("1 Adar I 5787", cs.HebrewDate(5787, cs.ADAR_1, 1)),
        ("14 Adar II 5787", cs.HebrewDate(5787, cs.ADAR_2, 14)),
        ("1 Marcheshvan 5788", cs.HebrewDate(5788, cs.CHESHVAN, 1)),
        ("1 of the Omer", None),
        ("Erev Pesach", None),
        ("17 Brumaire 5787", None),
    ],
)
def test_parse_hebrew_date(summary, expected):
    assert parse_hebrew_date(summary) == expected
