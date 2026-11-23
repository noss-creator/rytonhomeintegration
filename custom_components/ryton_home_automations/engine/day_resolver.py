"""Picks the one day a civil date resolves to.

This is the only place that decision is made. All knowledge of which days
exist and when they fall is in the table passed in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from .calendar_source import CalendarSource, HebrewDate
from .day_tables import FRI, FRIDAY, SAT, SHABBOS, WEEKDAY, DayTable, Occasion


class UnresolvedDayError(Exception):
    """A date the table cannot decide.

    Raised when two occasions fall on one date, or an occasion meets a Friday
    or Shabbos with no combination day listed for it. The plan says neither
    can happen once every combination is in the table.
    """


@dataclass(frozen=True)
class ResolvedDay:
    """The day a date resolved to, and how it was reached."""

    date: date
    day_id: str
    regular_day: str
    occasion: str | None = None
    combination: str | None = None
    combination_enabled: bool | None = None


def _matches(occasion: Occasion, hebrew: HebrewDate, weekday: int) -> bool:
    return any(
        hebrew.month in rule.months
        and hebrew.day in rule.days
        and weekday in rule.weekdays
        for rule in occasion.rules
    )


def resolve_day(
    day: date,
    source: CalendarSource,
    table: DayTable,
    is_enabled: Callable[[str], bool],
) -> ResolvedDay:
    """Resolve ``day`` to one day identifier.

    ``is_enabled`` says whether a combination day is switched on in the
    house's schedule.
    """
    hebrew = source.hebrew_date(day)
    weekday = day.weekday()
    regular = FRIDAY if weekday == FRI else SHABBOS if weekday == SAT else WEEKDAY

    found = [o for o in table.occasions if _matches(o, hebrew, weekday)]
    if len(found) > 1:
        names = ", ".join(o.id for o in found)
        raise UnresolvedDayError(f"{day}: more than one occasion on this date ({names})")

    if not found:
        if regular == SHABBOS:
            for variant in table.shabbos_variants:
                if _matches(variant, hebrew, weekday):
                    return ResolvedDay(day, variant.id, regular)
        return ResolvedDay(day, regular, regular)

    occasion = found[0]

    for combination in table.combinations:
        if combination.occasion == occasion.id and combination.on == regular:
            enabled = is_enabled(combination.id)
            return ResolvedDay(
                day,
                combination.id if enabled else combination.when_off,
                regular,
                occasion.id,
                combination.id,
                enabled,
            )

    if not occasion.standalone:
        raise UnresolvedDayError(
            f"{day}: {occasion.id} on a {regular} has no combination day"
        )
    if regular == WEEKDAY or (occasion.id, regular) in table.uncombined:
        return ResolvedDay(day, occasion.id, regular, occasion.id)

    raise UnresolvedDayError(
        f"{day}: {occasion.id} on {regular} has no combination day"
    )
