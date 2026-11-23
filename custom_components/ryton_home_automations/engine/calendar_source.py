"""The one interface through which the engine reads the Jewish calendar.

In a house this is backed by Home Assistant's Jewish Calendar integration.
In tests it is backed by recorded or generated data. The engine never
computes a Hebrew date or a zman itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

TISHREI = "tishrei"
CHESHVAN = "cheshvan"
KISLEV = "kislev"
TEVES = "teves"
SHEVAT = "shevat"
ADAR = "adar"  # the only Adar of a regular year
ADAR_1 = "adar_1"
ADAR_2 = "adar_2"
NISAN = "nisan"
IYAR = "iyar"
SIVAN = "sivan"
TAMMUZ = "tammuz"
AV = "av"
ELUL = "elul"

MONTHS = (
    TISHREI, CHESHVAN, KISLEV, TEVES, SHEVAT, ADAR, ADAR_1, ADAR_2,
    NISAN, IYAR, SIVAN, TAMMUZ, AV, ELUL,
)


@dataclass(frozen=True)
class HebrewDate:
    """A Hebrew date. ``month`` is one of ``MONTHS``."""

    year: int
    month: str
    day: int

    def __post_init__(self) -> None:
        if self.month not in MONTHS:
            raise ValueError(f"Unknown Hebrew month: {self.month!r}")


# The zman keys of SCHEDULE_FORMAT.md that are read from the Jewish Calendar.
ZMAN_KEYS = (
    "alos", "netz", "sof_zman_shema_gra", "sof_zman_shema_mga",
    "sof_zman_tefilla_gra", "sof_zman_tefilla_mga", "chatzos", "mincha_gedola",
    "mincha_ketana", "plag", "shkia", "tzeis", "candle_lighting", "havdalah",
)


class CalendarSource(Protocol):
    """What the engine asks the Jewish calendar."""

    def hebrew_date(self, day: date) -> HebrewDate:
        """Return the Hebrew date of a civil date (the daytime of that date)."""
        ...

    def zman(self, day: date, key: str) -> datetime | None:
        """Return a zman of a civil date as a timezone-aware datetime.

        ``key`` is one of ``ZMAN_KEYS``. Returns None when the calendar has no
        such zman on that date, such as candle lighting on a Tuesday.
        """
        ...
