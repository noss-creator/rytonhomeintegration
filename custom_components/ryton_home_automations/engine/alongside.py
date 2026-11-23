"""Which running-alongside automations apply on a civil date.

Sefiras haomer, Chanukah candle lighting and Selichos are never days. They
run on top of whatever day the date resolves to. Their date ranges are fixed
here by identifier, as SCHEDULE_FORMAT.md says.

Every Hebrew date is read from the calendar source. Where a range depends on
another date (the first evening of Chanukah, the coming Rosh Hashana), that
date is found by asking the source about the neighbouring days.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .calendar_source import ELUL, IYAR, KISLEV, NISAN, SIVAN, TEVES, TISHREI, CalendarSource
from .day_tables import FRI, SAT, SUN

SEFIRAS_HAOMER = "sefiras_haomer"
CHANUKAH = "chanukah_candle_lighting"
SELICHOS = "selichos"

# The three times Chanukah candle lighting has.
WEEKNIGHT = "weeknight"
FRIDAY = "friday"
MOTZEI_SHABBOS = "motzei_shabbos"


@dataclass(frozen=True)
class Alongside:
    """A running-alongside automation that applies on a date.

    ``time_key`` names which of the automation's times to use, for one that
    has several (Chanukah). It is None for one with a single time.
    """

    id: str
    time_key: str | None = None


def _is(source: CalendarSource, day: date, month: str, day_of_month: int) -> bool:
    hebrew = source.hebrew_date(day)
    return hebrew.month == month and hebrew.day == day_of_month


def _is_omer_evening(source: CalendarSource, day: date) -> bool:
    """The evening of ``day`` is one of the 49 nights of the Omer.

    The first is the second night of Pesach, the evening of 15 Nisan. The
    49th is the evening of 4 Sivan.
    """
    hebrew = source.hebrew_date(day)
    return (
        (hebrew.month == NISAN and hebrew.day >= 15)
        or hebrew.month == IYAR
        or (hebrew.month == SIVAN and hebrew.day <= 4)
    )


def _is_chanukah_evening(source: CalendarSource, day: date) -> bool:
    """The evening of ``day`` is one of the eight, the first being 24 Kislev."""
    if source.hebrew_date(day).month not in (KISLEV, TEVES):
        return False
    return any(_is(source, day - timedelta(days=n), KISLEV, 24) for n in range(8))


def _selichos_from_motzei_shabbos(source: CalendarSource, day: date) -> bool:
    """``day`` is on or after the Sunday Selichos begins before Rosh Hashana.

    That Sunday is the last one that leaves at least four days of Selichos
    before Rosh Hashana, so it is a week earlier when Rosh Hashana is on
    Monday or Tuesday.
    """
    for ahead in range(1, 10):
        rosh_hashana = day + timedelta(days=ahead)
        if _is(source, rosh_hashana, TISHREI, 1):
            latest = rosh_hashana - timedelta(days=4)
            first = latest - timedelta(days=(latest.weekday() - SUN) % 7)
            return day >= first
    return False


def _is_selichos_day(
    source: CalendarSource, day: date, settings: Mapping[str, Any]
) -> bool:
    """Selichos is said on ``day``: inside the house's period, through Erev
    Yom Kippur, and not on Shabbos or Rosh Hashana."""
    from_elul = bool(settings.get("from_elul"))
    from_motzei_shabbos = bool(settings.get("from_motzei_shabbos"))
    if not (from_elul or from_motzei_shabbos):
        return False
    if day.weekday() == SAT:
        return False

    hebrew = source.hebrew_date(day)
    if hebrew.month == TISHREI:
        return 3 <= hebrew.day <= 9
    if hebrew.month == ELUL:
        return from_elul or _selichos_from_motzei_shabbos(source, day)
    return False


def alongside_for(
    day: date, source: CalendarSource, selichos_settings: Mapping[str, Any]
) -> list[Alongside]:
    """Return the running-alongside automations that apply on ``day``.

    ``selichos_settings`` is ``settings.selichos`` from the house's schedule.
    """
    found: list[Alongside] = []

    if _is_omer_evening(source, day):
        found.append(Alongside(SEFIRAS_HAOMER))

    if _is_chanukah_evening(source, day):
        weekday = day.weekday()
        time_key = (
            FRIDAY if weekday == FRI else MOTZEI_SHABBOS if weekday == SAT else WEEKNIGHT
        )
        found.append(Alongside(CHANUKAH, time_key))

    if _is_selichos_day(source, day, selichos_settings):
        found.append(Alongside(SELICHOS))

    return found
