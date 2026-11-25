"""Works out, for a span of dates, which day each is and every automation's time.

This is the list Nosson reviews on paper, and later the year preview the
house sends to the website. It switches nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from .calendar_snapshot import CalendarDataError
from .calendar_source import CalendarSource
from .day_list import build_day_list, check_schedule, resolve_schedule_day
from .day_resolver import UnresolvedDayError
from .time_resolver import PastRolloverError, ScheduleError, ZmanUnavailableError

# How far the running-alongside automations look around a date: back to the
# first evening of Chanukah, ahead to the coming Rosh Hashana.
LOOK_BACK_DAYS = 8
LOOK_AHEAD_DAYS = 10

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Shabbos", "Sunday")


def _clock(when: datetime, day: date) -> str:
    """A time as HH:MM, with seconds if it has any, marked when on a later date."""
    text = when.strftime("%H:%M:%S" if when.second else "%H:%M")
    days_later = (when.date() - day).days
    return f"{text} (+{days_later})" if days_later > 0 else text


def build_preview(
    schedule: Mapping[str, Any],
    source: CalendarSource,
    tz: tzinfo,
    first: date,
    days: int,
) -> list[dict[str, Any]]:
    """Return one row for each of ``days`` dates starting at ``first``.

    A date the engine cannot work out gets an ``error`` in its row, so one
    bad date does not hide the others. Where the day itself was worked out
    and only its times were not, as with a time left blank, the row still
    says which day the date is.
    """
    rows: list[dict[str, Any]] = []
    for n in range(days):
        day = first + timedelta(days=n)
        row: dict[str, Any] = {
            "date": day.isoformat(),
            "weekday": _WEEKDAYS[day.weekday()],
        }
        try:
            hebrew = source.hebrew_date(day)
            row["hebrew_date"] = f"{hebrew.day} {hebrew.month} {hebrew.year}"
            check_schedule(schedule)
            row["day"] = resolve_schedule_day(schedule, day, source).day_id
            day_list = build_day_list(schedule, day, source, tz)
        except (
            CalendarDataError,
            PastRolloverError,
            ScheduleError,
            UnresolvedDayError,
            ZmanUnavailableError,
        ) as err:
            row["error"] = str(err)
        else:
            if day_list.shabbos_start is not None:
                row["shabbos_start"] = _clock(day_list.shabbos_start, day)
            row["automations"] = [
                {
                    "id": a.id,
                    "time": _clock(a.time, day),
                    "alongside": a.alongside,
                }
                for a in day_list.automations
            ]
        rows.append(row)
    return rows


def format_preview(rows: list[dict[str, Any]]) -> str:
    """Lay the rows out as text, one date to a line."""
    lines = []
    for row in rows:
        head = f"{row['date']} {row['weekday']:<9} {row.get('hebrew_date', ''):<18}"
        if "error" in row:
            lines.append(f"{head} ERROR: {row['error']}")
            continue
        parts = [
            f"{a['id']}{'*' if a['alongside'] else ''} {a['time']}"
            for a in row["automations"]
        ]
        lines.append(f"{head} {row['day']:<36} " + ", ".join(parts))
    lines.append("")
    lines.append("* runs alongside the day's own schedule")
    return "\n".join(lines) + "\n"
