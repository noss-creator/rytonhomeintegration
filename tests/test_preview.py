"""The preview: one row for each date, and its text layout.

Runs without a Home Assistant instance, on the made-up schedule and zmanim
of tests/test_day_list.py.
"""

from __future__ import annotations

from datetime import date

from engine.preview import (
    build_preview,
    format_preview,
)

from .test_day_list import SOURCE, TZ, make_schedule


def test_rows_for_a_week_with_a_friday():
    rows = build_preview(make_schedule(), SOURCE, TZ, date(2027, 6, 14), 7)
    assert [r["date"] for r in rows] == [f"2027-06-{d}" for d in range(14, 21)]
    assert [r["weekday"] for r in rows] == [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Shabbos", "Sunday",
    ]
    assert [r["day"] for r in rows] == [
        "weekday", "weekday", "weekday", "weekday", "friday", "shabbos", "weekday",
    ]

    tuesday, friday = rows[1], rows[4]
    assert tuesday["hebrew_date"] == "10 sivan 5787"
    assert "shabbos_start" not in tuesday
    assert tuesday["automations"] == [
        {"id": "morning", "time": "07:00", "alongside": False},
        {"id": "sunset", "time": "18:00", "alongside": False},
        {"id": "night", "time": "23:00", "alongside": False},
    ]
    assert friday["shabbos_start"] == "17:42"
    assert friday["automations"][1] == {
        "id": "erev_shabbos", "time": "17:32", "alongside": False,
    }


def test_a_time_after_midnight_is_marked_as_the_next_date():
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][2]["time"] = {
        "kind": "clock", "at": "00:30", "day_offset": 1,
    }
    [row] = build_preview(schedule, SOURCE, TZ, date(2027, 6, 15), 1)
    assert row["automations"][-1]["time"] == "00:30 (+1)"


def test_alongside_automations_are_marked():
    [row] = build_preview(make_schedule(), SOURCE, TZ, date(2027, 5, 4), 1)
    assert {"id": "sefiras_haomer", "time": "18:45", "alongside": True} in row["automations"]


def test_a_date_that_cannot_be_worked_out_gets_an_error_and_the_rest_carry_on():
    schedule = make_schedule()
    del schedule["days"]["friday"]
    rows = build_preview(schedule, SOURCE, TZ, date(2027, 6, 17), 3)
    assert "error" not in rows[0]
    assert "friday" in rows[1]["error"]
    assert "day" not in rows[1]
    assert rows[2]["day"] == "shabbos"


def test_text_layout():
    schedule = make_schedule()
    del schedule["days"]["friday"]
    text = format_preview(build_preview(schedule, SOURCE, TZ, date(2027, 5, 6), 2))
    thursday, friday = text.splitlines()[:2]
    assert thursday.startswith("2027-05-06 Thursday")
    assert "weekday" in thursday
    assert "sefiras_haomer* 18:45" in thursday
    assert "morning 07:00" in thursday
    assert "ERROR" in friday
    assert text.rstrip().endswith("* runs alongside the day's own schedule")
