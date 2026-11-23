"""A calendar source built from events of the Jewish Calendar integration.

The house reads that integration's two calendar entities for a span of
dates and hands the events here. The result answers the engine's questions
for those dates with no further contact with Home Assistant.

Nothing is computed: a Hebrew date or zman is only ever one the integration
returned. This module does not import Home Assistant, so it is tested on
events recorded from a real installation.

The events are matched by their English text, which is how the integration
names them when Home Assistant's language is English.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from . import calendar_source as cs


class CalendarDataError(Exception):
    """The Jewish Calendar did not return what the engine needs."""


# Event summary -> zman key. A summary is matched by how it starts, since
# nightfall carries a note, as in "Tset Hakochavim (18 minutes)".
#
# Every name here has been read from a real installation.
_ZMAN_SUMMARIES = (
    ("Alot HaShachar", "alos"),
    ("Netz Hachama", "netz"),
    ('Sof Zman Shema (Gr"A)', "sof_zman_shema_gra"),
    ('Sof Zman Shema (Mg"A)', "sof_zman_shema_mga"),
    ('Sof Zman Tefilla (Gr"A)', "sof_zman_tefilla_gra"),
    ('Sof Zman Tefilla (Mg"A)', "sof_zman_tefilla_mga"),
    ("Chatzot Hayom", "chatzos"),
    ("Mincha Gedola", "mincha_gedola"),
    ("Mincha Ketana", "mincha_ketana"),
    ("Plag Hamincha", "plag"),
    ("Shkia", "shkia"),
    ("Tset Hakochavim", "tzeis"),
    ("Candle Lighting", "candle_lighting"),
    ("Havdalah", "havdalah"),
)

# Month names as the integration writes them in a Hebrew date.
_MONTH_NAMES = {
    "Tishrei": cs.TISHREI,
    "Marcheshvan": cs.CHESHVAN,
    "Kislev": cs.KISLEV,
    "Tevet": cs.TEVES,
    "Sh'vat": cs.SHEVAT,
    "Adar": cs.ADAR,
    "Adar I": cs.ADAR_1,
    "Adar II": cs.ADAR_2,
    "Nisan": cs.NISAN,
    "Iyyar": cs.IYAR,
    "Sivan": cs.SIVAN,
    "Tammuz": cs.TAMMUZ,
    "Av": cs.AV,
    "Elul": cs.ELUL,
}

_HEBREW_DATE = re.compile(r"^(\d{1,2}) (.+) (\d{4})$")


def zman_key(summary: str) -> str | None:
    """Return the zman key an event summary stands for, or None."""
    for text, key in _ZMAN_SUMMARIES:
        if summary == text or summary.startswith(text + " "):
            return key
    return None


def parse_hebrew_date(summary: str) -> cs.HebrewDate | None:
    """Read a summary such as "17 Kislev 5787", or return None if it is not one."""
    match = _HEBREW_DATE.match(summary)
    if not match:
        return None
    day, month, year = match.groups()
    if month not in _MONTH_NAMES:
        return None
    return cs.HebrewDate(int(year), _MONTH_NAMES[month], int(day))


class CalendarSnapshot:
    """The Jewish Calendar for the dates ``first`` to ``last``."""

    def __init__(
        self,
        first: date,
        last: date,
        hebrew_dates: Mapping[date, cs.HebrewDate],
        zmanim: Mapping[tuple[date, str], datetime],
    ) -> None:
        self.first = first
        self.last = last
        self._hebrew_dates = dict(hebrew_dates)
        self._zmanim = dict(zmanim)

    def _check(self, day: date) -> None:
        if not self.first <= day <= self.last:
            raise CalendarDataError(
                f"{day} is outside the dates read from the Jewish Calendar "
                f"({self.first} to {self.last})"
            )

    def hebrew_date(self, day: date) -> cs.HebrewDate:
        self._check(day)
        return self._hebrew_dates[day]

    def zman(self, day: date, key: str) -> datetime | None:
        self._check(day)
        return self._zmanim.get((day, key))


def parse_events(
    daily_events: Iterable[Mapping[str, Any]],
    yearly_events: Iterable[Mapping[str, Any]],
    tz: tzinfo,
    first: date,
    last: date,
) -> CalendarSnapshot:
    """Build a snapshot for ``first`` to ``last`` from calendar events.

    Each event is a mapping with ``start`` and ``summary``, as the
    ``calendar.get_events`` service returns them: ``start`` is a date for an
    all-day event and a date and time otherwise. ``tz`` is the house's
    timezone, which decides the date a zman belongs to.

    Raises CalendarDataError if any date in the span has no Hebrew date.
    """
    hebrew_dates: dict[date, cs.HebrewDate] = {}
    zmanim: dict[tuple[date, str], datetime] = {}

    for event in list(daily_events) + list(yearly_events):
        start = event.get("start")
        summary = event.get("summary")
        if not isinstance(start, str) or not isinstance(summary, str):
            continue

        if "T" not in start:
            hebrew = parse_hebrew_date(summary)
            if hebrew is not None:
                hebrew_dates[date.fromisoformat(start)] = hebrew
            continue

        key = zman_key(summary)
        if key is None:
            continue
        moment = datetime.fromisoformat(start)
        if moment.tzinfo is None:
            raise CalendarDataError(f"{summary} at {start} has no timezone")
        moment = moment.astimezone(tz)
        zmanim[(moment.date(), key)] = moment

    missing = [
        first + timedelta(days=n)
        for n in range((last - first).days + 1)
        if first + timedelta(days=n) not in hebrew_dates
    ]
    if missing:
        raise CalendarDataError(
            f"The Jewish Calendar returned no Hebrew date for {missing[0]} "
            f"({len(missing)} dates in all). Check that the date event is "
            "selected in its options and that Home Assistant is in English."
        )

    return CalendarSnapshot(first, last, hebrew_dates, zmanim)
