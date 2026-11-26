"""Turns the time specifications of SCHEDULE_FORMAT.md into clock times.

Every zman is read from the calendar source for the date in question. None is
worked out from another.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from .calendar_source import ZMAN_KEYS, CalendarSource
from .day_tables import FRI

SHABBOS_START = "shabbos_start"
BY_RULE = "by_rule"
# A case of a time that goes by rules on which the automation does not run.
DONT_RUN = "dont_run"

Spec = Mapping[str, Any]


class ScheduleError(ValueError):
    """The schedule holds something the format does not allow."""


class ZmanUnavailableError(Exception):
    """A time needs a zman the calendar does not have on that date."""


class PastRolloverError(Exception):
    """A time resolved later than the day rollover with no exception set."""


def _clock(value: Any) -> time:
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        raise ScheduleError(f"Not a clock time: {value!r}") from None


def _resolve_simple(
    spec: Spec,
    day: date,
    source: CalendarSource,
    tz: tzinfo,
    shabbos_start: datetime | None,
) -> datetime:
    kind = spec.get("kind")

    if kind == "clock":
        day_offset = spec.get("day_offset", 0)
        if day_offset not in (0, 1):
            raise ScheduleError(f"day_offset must be 0 or 1, not {day_offset!r}")
        on = day + timedelta(days=day_offset)
        return datetime.combine(on, _clock(spec.get("at")), tz)

    if kind == "zman":
        key = spec.get("zman")
        if key == SHABBOS_START:
            base = shabbos_start
        elif key in ZMAN_KEYS:
            base = source.zman(day, key)
        else:
            raise ScheduleError(f"Unknown zman: {key!r}")
        if base is None:
            raise ZmanUnavailableError(f"{day}: no {key} on this date")
        offset = spec.get("offset_minutes", 0)
        if isinstance(offset, bool) or not isinstance(offset, (int, float)):
            raise ScheduleError(f"offset_minutes must be a number, not {offset!r}")
        return base + timedelta(minutes=offset)

    raise ScheduleError(f"Unknown kind of time: {kind!r}")


def resolve_time(
    spec: Spec,
    day: date,
    source: CalendarSource,
    tz: tzinfo,
    shabbos_start: datetime | None = None,
) -> datetime:
    """Return the moment a time specification means on ``day``.

    ``tz`` is the house's timezone. ``shabbos_start`` is the engine's own
    value for the date, from ``resolve_shabbos_start``.
    """
    kind = spec.get("kind")
    if kind == BY_RULE:
        chosen = _time_by_rule(spec, day, source, tz)
        if chosen.get("kind") == DONT_RUN:
            raise ScheduleError("The automation does not run on this date")
        return resolve_time(chosen, day, source, tz, shabbos_start)
    if kind in ("later_of", "earlier_of"):
        parts = spec.get("of")
        if not isinstance(parts, Sequence) or len(parts) < 2:
            raise ScheduleError(f"{kind} needs two or more times")
        times = [_resolve_simple(p, day, source, tz, shabbos_start) for p in parts]
        return max(times) if kind == "later_of" else min(times)
    return _resolve_simple(spec, day, source, tz, shabbos_start)


def runs_on(spec: Spec, day: date, source: CalendarSource, tz: tzinfo) -> bool:
    """Whether an automation with this time runs on ``day`` at all.

    Only a time that goes by rules can say no: one of its cases, or its
    ``otherwise``, can be "don't run" in place of a time.
    """
    if spec.get("kind") != BY_RULE:
        return True
    return _time_by_rule(spec, day, source, tz).get("kind") != DONT_RUN


def _time_by_rule(spec: Spec, day: date, source: CalendarSource, tz: tzinfo) -> Spec:
    """Return the time a "by rule" time means on ``day``.

    Its rules are tried in order and the first that matches gives the time.
    When none matches, the time is ``otherwise``. Any of them can be
    ``{"kind": "dont_run"}`` in place of a time. Every part is checked on
    every date, so a mistake in a rule that seldom matches is still caught.
    """
    rules = spec.get("rules")
    if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)):
        raise ScheduleError("A time that goes by rules has no list of rules")
    times = [spec.get("otherwise")]
    for rule in rules:
        if not isinstance(rule, Mapping) or not isinstance(rule.get("when"), Mapping):
            raise ScheduleError("A rule of a time is not understood")
        times.append(rule.get("time"))
    for time_spec in times:
        if not isinstance(time_spec, Mapping):
            raise ScheduleError("A time that goes by rules needs a time for every case")
        if time_spec.get("kind") == BY_RULE:
            raise ScheduleError("A time that goes by rules cannot hold another one")

    for rule in rules:
        if _rule_matches(rule["when"], day, source, tz):
            return rule["time"]
    return spec["otherwise"]


def check_rollover(
    when: datetime,
    day: date,
    tz: tzinfo,
    day_rollover: str,
    allow_past_rollover: bool = False,
) -> None:
    """Refuse a time of ``day`` that falls after the next morning's rollover."""
    limit = datetime.combine(day + timedelta(days=1), _clock(day_rollover), tz)
    if when > limit and not allow_past_rollover:
        raise PastRolloverError(
            f"{day}: {when:%Y-%m-%d %H:%M} is later than the day rollover"
        )


def _in_date_range(day: date, start: str, end: str) -> bool:
    try:
        first = tuple(int(p) for p in start.split("-"))
        last = tuple(int(p) for p in end.split("-"))
    except (AttributeError, ValueError):
        raise ScheduleError(f"Not a month-day range: {start!r} to {end!r}") from None
    if len(first) != 2 or len(last) != 2:
        raise ScheduleError(f"Not a month-day range: {start!r} to {end!r}")
    today = (day.month, day.day)
    if first <= last:
        return first <= today <= last
    return today >= first or today <= last  # the range runs over the new year


def _rule_matches(when: Spec, day: date, source: CalendarSource, tz: tzinfo) -> bool:
    kind = when.get("kind")

    if kind == "date_range":
        return _in_date_range(day, when.get("from"), when.get("to"))

    if kind == "zman_range":
        key = when.get("zman")
        if key not in ZMAN_KEYS:
            raise ScheduleError(f"Unknown zman: {key!r}")
        moment = source.zman(day, key)
        if moment is None:
            raise ZmanUnavailableError(f"{day}: no {key} on this date")
        at = moment.astimezone(tz).time()
        if "from" in when and at < _clock(when["from"]):
            return False
        if "to" in when and at > _clock(when["to"]):
            return False
        return True

    if kind == "clock_season":
        season = when.get("season")
        if season not in ("summer", "winter"):
            raise ScheduleError(f"Unknown season: {season!r}")
        noon = datetime.combine(day, time(12), tz)
        summer_time = bool(noon.dst())
        return summer_time if season == "summer" else not summer_time

    raise ScheduleError(f"Unknown kind of rule: {kind!r}")


def _early_start(start: Spec, day: date, source: CalendarSource, tz: tzinfo) -> datetime:
    kind = start.get("kind")
    if kind == "clock" and start.get("day_offset", 0) == 0:
        return _resolve_simple(start, day, source, tz, None)
    if kind == "zman" and start.get("zman") == "plag":
        return _resolve_simple(start, day, source, tz, None)
    raise ScheduleError("An early Shabbos time is a clock time or is timed from plag")


def resolve_shabbos_start(
    day: date,
    source: CalendarSource,
    tz: tzinfo,
    rules: Sequence[Spec],
    *,
    one_week: Spec | None = None,
) -> datetime | None:
    """Return the engine's Shabbos start for ``day``, or None if it has none.

    It is candle lighting, unless ``day`` is a Friday and an early Shabbos
    rule or the one-week early switch applies. The first rule that matches
    wins. It is never later than candle lighting: an early time that works
    out later is replaced by candle lighting.

    The rules apply on every Friday. ``one_week`` is the client's one-week
    switch: ``{"kind": "late"}`` skips the rules, and
    ``{"kind": "early", "start": <time>}`` uses that time.
    """
    candle_lighting = source.zman(day, "candle_lighting")
    if day.weekday() != FRI:
        return candle_lighting

    early: datetime | None = None
    if one_week is not None:
        kind = one_week.get("kind")
        if kind == "early":
            early = _early_start(one_week.get("start", {}), day, source, tz)
        elif kind != "late":
            raise ScheduleError(f"Unknown one-week switch: {kind!r}")
    else:
        for rule in rules:
            if _rule_matches(rule.get("when", {}), day, source, tz):
                early = _early_start(rule.get("start", {}), day, source, tz)
                break

    # Shabbos never starts later than candle lighting.
    if early is None:
        return candle_lighting
    if candle_lighting is None:
        return early
    return min(early, candle_lighting)
