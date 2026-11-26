"""Time specifications, Shabbos start and the day rollover.

Runs without Home Assistant. The zmanim here are made-up values handed to the
engine through its calendar interface. Nothing computes a zman.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from engine.time_resolver import (
    PastRolloverError,
    ScheduleError,
    ZmanUnavailableError,
    check_rollover,
    resolve_shabbos_start,
    resolve_time,
    runs_on,
)

TZ = ZoneInfo("America/New_York")

SUMMER_FRIDAY = date(2027, 6, 18)
WINTER_FRIDAY = date(2027, 1, 15)
TUESDAY = date(2027, 6, 15)


def at(day: date, clock: str, day_offset: int = 0) -> datetime:
    hour, minute = (int(p) for p in clock.split(":"))
    return datetime(day.year, day.month, day.day + day_offset, hour, minute, tzinfo=TZ)


class FakeSource:
    def __init__(self, zmanim: dict[tuple[date, str], datetime]):
        self._zmanim = zmanim

    def zman(self, day: date, key: str) -> datetime | None:
        return self._zmanim.get((day, key))


SOURCE = FakeSource(
    {
        (SUMMER_FRIDAY, "plag"): at(SUMMER_FRIDAY, "18:57"),
        (SUMMER_FRIDAY, "shkia"): at(SUMMER_FRIDAY, "20:30"),
        (SUMMER_FRIDAY, "tzeis"): at(SUMMER_FRIDAY, "21:10"),
        (SUMMER_FRIDAY, "candle_lighting"): at(SUMMER_FRIDAY, "20:12"),
        (WINTER_FRIDAY, "plag"): at(WINTER_FRIDAY, "15:54"),
        (WINTER_FRIDAY, "shkia"): at(WINTER_FRIDAY, "16:53"),
        (WINTER_FRIDAY, "candle_lighting"): at(WINTER_FRIDAY, "16:35"),
        (TUESDAY, "plag"): at(TUESDAY, "18:56"),
        (TUESDAY, "shkia"): at(TUESDAY, "20:29"),
    }
)


def resolve(spec, day=SUMMER_FRIDAY, shabbos_start=None):
    return resolve_time(spec, day, SOURCE, TZ, shabbos_start)


# --- the three kinds of time ---------------------------------------------


def test_clock_time():
    assert resolve({"kind": "clock", "at": "23:00"}) == at(SUMMER_FRIDAY, "23:00")


def test_clock_time_after_midnight_belongs_to_the_day_before():
    spec = {"kind": "clock", "at": "00:30", "day_offset": 1}
    assert resolve(spec) == at(SUMMER_FRIDAY, "00:30", day_offset=1)


def test_clock_time_uses_the_houses_timezone_in_summer_and_winter():
    spec = {"kind": "clock", "at": "07:00"}
    assert resolve(spec, SUMMER_FRIDAY).utcoffset().total_seconds() == -4 * 3600
    assert resolve(spec, WINTER_FRIDAY).utcoffset().total_seconds() == -5 * 3600


def test_zman_with_no_offset():
    assert resolve({"kind": "zman", "zman": "shkia"}) == at(SUMMER_FRIDAY, "20:30")


def test_zman_with_offset_before_and_after():
    before = {"kind": "zman", "zman": "shkia", "offset_minutes": -45}
    after = {"kind": "zman", "zman": "tzeis", "offset_minutes": 5}
    assert resolve(before) == at(SUMMER_FRIDAY, "19:45")
    assert resolve(after) == at(SUMMER_FRIDAY, "21:15")


def test_zman_is_read_for_the_date_asked():
    spec = {"kind": "zman", "zman": "shkia"}
    assert resolve(spec, TUESDAY) == at(TUESDAY, "20:29")
    assert resolve(spec, WINTER_FRIDAY) == at(WINTER_FRIDAY, "16:53")


def test_shabbos_start_is_the_engines_own_value():
    spec = {"kind": "zman", "zman": "shabbos_start", "offset_minutes": -10}
    start = at(SUMMER_FRIDAY, "18:57")
    assert resolve(spec, shabbos_start=start) == at(SUMMER_FRIDAY, "18:47")


def test_later_of_and_earlier_of():
    parts = [
        {"kind": "clock", "at": "23:00"},
        {"kind": "zman", "zman": "shabbos_start", "offset_minutes": 300},
    ]
    start = at(SUMMER_FRIDAY, "20:12")  # plus 300 minutes is 01:12 next morning
    later = resolve({"kind": "later_of", "of": parts}, shabbos_start=start)
    earlier = resolve({"kind": "earlier_of", "of": parts}, shabbos_start=start)
    assert later == at(SUMMER_FRIDAY, "01:12", day_offset=1)
    assert earlier == at(SUMMER_FRIDAY, "23:00")


def test_later_of_takes_more_than_two():
    spec = {
        "kind": "later_of",
        "of": [
            {"kind": "clock", "at": "19:00"},
            {"kind": "zman", "zman": "plag"},
            {"kind": "zman", "zman": "shkia"},
        ],
    }
    assert resolve(spec) == at(SUMMER_FRIDAY, "20:30")


# --- times the engine must refuse ----------------------------------------


def test_zman_missing_on_that_date_is_an_error():
    with pytest.raises(ZmanUnavailableError):
        resolve({"kind": "zman", "zman": "candle_lighting"}, TUESDAY)


def test_shabbos_start_missing_is_an_error():
    with pytest.raises(ZmanUnavailableError):
        resolve({"kind": "zman", "zman": "shabbos_start"}, TUESDAY)


@pytest.mark.parametrize(
    "spec",
    [
        {"kind": "sometime"},
        {"kind": "clock", "at": "25:00"},
        {"kind": "clock"},
        {"kind": "clock", "at": "23:00", "day_offset": 2},
        {"kind": "zman", "zman": "midnight"},
        {"kind": "zman", "zman": "shkia", "offset_minutes": "ten"},
        {"kind": "later_of", "of": [{"kind": "clock", "at": "23:00"}]},
        {"kind": "later_of"},
        # No nesting: the parts are clock or zman only.
        {
            "kind": "later_of",
            "of": [
                {"kind": "clock", "at": "23:00"},
                {"kind": "earlier_of", "of": [{"kind": "clock", "at": "22:00"}] * 2},
            ],
        },
    ],
)
def test_bad_time_specifications_are_refused(spec):
    with pytest.raises(ScheduleError):
        resolve(spec)


# --- day rollover ---------------------------------------------------------


def test_time_before_the_rollover_is_accepted():
    check_rollover(at(SUMMER_FRIDAY, "00:30", 1), SUMMER_FRIDAY, TZ, "04:00")
    check_rollover(at(SUMMER_FRIDAY, "04:00", 1), SUMMER_FRIDAY, TZ, "04:00")


def test_time_after_the_rollover_is_refused():
    with pytest.raises(PastRolloverError):
        check_rollover(at(SUMMER_FRIDAY, "04:01", 1), SUMMER_FRIDAY, TZ, "04:00")


def test_time_after_the_rollover_is_accepted_with_the_exception():
    check_rollover(
        at(SUMMER_FRIDAY, "05:00", 1), SUMMER_FRIDAY, TZ, "04:00",
        allow_past_rollover=True,
    )


def test_rollover_follows_the_houses_setting():
    late_night = at(SUMMER_FRIDAY, "04:30", 1)
    check_rollover(late_night, SUMMER_FRIDAY, TZ, "05:00")
    with pytest.raises(PastRolloverError):
        check_rollover(late_night, SUMMER_FRIDAY, TZ, "03:00")


# --- Shabbos start --------------------------------------------------------

AT_PLAG = {"kind": "zman", "zman": "plag"}
PLAN_EXAMPLE = [
    {"when": {"kind": "zman_range", "zman": "shkia", "from": "18:30", "to": "19:15"},
     "start": AT_PLAG},
    {"when": {"kind": "zman_range", "zman": "shkia", "from": "19:15"},
     "start": {"kind": "clock", "at": "19:00"}},
]


def shabbos_start(day, rules, **kwargs):
    return resolve_shabbos_start(day, SOURCE, TZ, rules, **kwargs)


def test_no_rules_means_candle_lighting():
    assert shabbos_start(SUMMER_FRIDAY, []) == at(SUMMER_FRIDAY, "20:12")


def test_no_matching_rule_means_candle_lighting():
    assert shabbos_start(WINTER_FRIDAY, PLAN_EXAMPLE) == at(WINTER_FRIDAY, "16:35")


def test_plans_example_late_shkia_starts_at_19_00():
    assert shabbos_start(SUMMER_FRIDAY, PLAN_EXAMPLE) == at(SUMMER_FRIDAY, "19:00")


def test_zman_range_at_plag():
    source = FakeSource(
        {
            (SUMMER_FRIDAY, "shkia"): at(SUMMER_FRIDAY, "19:00"),
            (SUMMER_FRIDAY, "plag"): at(SUMMER_FRIDAY, "17:40"),
            (SUMMER_FRIDAY, "candle_lighting"): at(SUMMER_FRIDAY, "18:42"),
        }
    )
    got = resolve_shabbos_start(SUMMER_FRIDAY, source, TZ, PLAN_EXAMPLE)
    assert got == at(SUMMER_FRIDAY, "17:40")


@pytest.mark.parametrize(
    "shkia,candle_lighting,expected",
    [
        ("18:29", "18:11", "18:11"),  # no rule matches: candle lighting
        ("18:30", "18:12", "17:15"),  # first rule, at plag
        ("19:15", "18:57", "17:15"),  # both match, the higher rule wins
        ("19:16", "18:58", "18:58"),  # second rule says 19:00, which is too late
        ("19:40", "19:22", "19:00"),  # second rule, 19:00
    ],
)
def test_zman_range_bounds_and_the_higher_rule_winning(shkia, candle_lighting, expected):
    """18:30 and 19:15 are inside the first rule; at 19:15 both match and the first wins."""
    source = FakeSource(
        {
            (SUMMER_FRIDAY, "shkia"): at(SUMMER_FRIDAY, shkia),
            (SUMMER_FRIDAY, "plag"): at(SUMMER_FRIDAY, "17:15"),
            (SUMMER_FRIDAY, "candle_lighting"): at(SUMMER_FRIDAY, candle_lighting),
        }
    )
    got = resolve_shabbos_start(SUMMER_FRIDAY, source, TZ, PLAN_EXAMPLE)
    assert got == at(SUMMER_FRIDAY, expected)


def test_shabbos_never_starts_later_than_candle_lighting():
    late_clock = [
        {"when": {"kind": "clock_season", "season": "winter"},
         "start": {"kind": "clock", "at": "19:00"}}
    ]
    late_offset = [
        {"when": {"kind": "clock_season", "season": "winter"},
         "start": {"kind": "zman", "zman": "plag", "offset_minutes": 120}}
    ]
    candle_lighting = at(WINTER_FRIDAY, "16:35")
    assert shabbos_start(WINTER_FRIDAY, late_clock) == candle_lighting
    assert shabbos_start(WINTER_FRIDAY, late_offset) == candle_lighting


def test_early_shabbos_this_week_is_never_later_than_candle_lighting():
    switch = {"kind": "early", "start": {"kind": "clock", "at": "18:30"}}
    got = shabbos_start(WINTER_FRIDAY, [], one_week=switch)
    assert got == at(WINTER_FRIDAY, "16:35")


def test_reordering_the_rules_changes_the_winner():
    both_match = [
        {"when": {"kind": "clock_season", "season": "summer"}, "start": AT_PLAG},
        {"when": {"kind": "clock_season", "season": "summer"},
         "start": {"kind": "clock", "at": "19:00"}},
    ]
    assert shabbos_start(SUMMER_FRIDAY, both_match) == at(SUMMER_FRIDAY, "18:57")
    assert shabbos_start(SUMMER_FRIDAY, both_match[::-1]) == at(SUMMER_FRIDAY, "19:00")


def test_offset_from_plag():
    rules = [
        {"when": {"kind": "clock_season", "season": "summer"},
         "start": {"kind": "zman", "zman": "plag", "offset_minutes": 10}}
    ]
    assert shabbos_start(SUMMER_FRIDAY, rules) == at(SUMMER_FRIDAY, "19:07")


def test_clock_season():
    summer = [{"when": {"kind": "clock_season", "season": "summer"}, "start": AT_PLAG}]
    winter = [{"when": {"kind": "clock_season", "season": "winter"}, "start": AT_PLAG}]
    assert shabbos_start(SUMMER_FRIDAY, summer) == at(SUMMER_FRIDAY, "18:57")
    assert shabbos_start(WINTER_FRIDAY, summer) == at(WINTER_FRIDAY, "16:35")
    assert shabbos_start(WINTER_FRIDAY, winter) == at(WINTER_FRIDAY, "15:54")
    assert shabbos_start(SUMMER_FRIDAY, winter) == at(SUMMER_FRIDAY, "20:12")


@pytest.mark.parametrize(
    "start,end,summer_matches,winter_matches",
    [
        ("05-01", "08-31", True, False),
        ("06-18", "06-18", True, False),
        ("06-19", "08-31", False, False),
        ("11-01", "02-28", False, True),  # runs over the new year
        ("01-15", "01-15", False, True),
    ],
)
def test_date_range(start, end, summer_matches, winter_matches):
    rules = [{"when": {"kind": "date_range", "from": start, "to": end}, "start": AT_PLAG}]
    summer = shabbos_start(SUMMER_FRIDAY, rules)
    winter = shabbos_start(WINTER_FRIDAY, rules)
    assert (summer == at(SUMMER_FRIDAY, "18:57")) is summer_matches
    assert (winter == at(WINTER_FRIDAY, "15:54")) is winter_matches


def test_rules_never_apply_on_a_day_that_is_not_friday():
    rules = [{"when": {"kind": "clock_season", "season": "summer"}, "start": AT_PLAG}]
    assert shabbos_start(TUESDAY, rules) is None


def test_late_shabbos_this_week_skips_the_rules():
    got = shabbos_start(SUMMER_FRIDAY, PLAN_EXAMPLE, one_week={"kind": "late"})
    assert got == at(SUMMER_FRIDAY, "20:12")


@pytest.mark.parametrize(
    "start,expected",
    [
        (AT_PLAG, "18:57"),
        ({"kind": "zman", "zman": "plag", "offset_minutes": 15}, "19:12"),
        ({"kind": "clock", "at": "18:30"}, "18:30"),
    ],
)
def test_early_shabbos_this_week(start, expected):
    switch = {"kind": "early", "start": start}
    got = shabbos_start(SUMMER_FRIDAY, [], one_week=switch)
    assert got == at(SUMMER_FRIDAY, expected)


def test_early_shabbos_this_week_wins_over_the_rules():
    switch = {"kind": "early", "start": AT_PLAG}
    got = shabbos_start(SUMMER_FRIDAY, PLAN_EXAMPLE, one_week=switch)
    assert got == at(SUMMER_FRIDAY, "18:57")


@pytest.mark.parametrize(
    "rule",
    [
        {"when": {"kind": "full_moon"}, "start": AT_PLAG},
        {"when": {"kind": "clock_season", "season": "spring"}, "start": AT_PLAG},
        {"when": {"kind": "zman_range", "zman": "moonrise"}, "start": AT_PLAG},
        {"when": {"kind": "date_range", "from": "May", "to": "08-31"}, "start": AT_PLAG},
        # The early time is a clock time or is timed from plag, nothing else.
        {"when": {"kind": "clock_season", "season": "summer"},
         "start": {"kind": "zman", "zman": "shkia"}},
        {"when": {"kind": "clock_season", "season": "summer"},
         "start": {"kind": "later_of", "of": [AT_PLAG, AT_PLAG]}},
    ],
)
def test_bad_early_shabbos_rules_are_refused(rule):
    with pytest.raises(ScheduleError):
        shabbos_start(SUMMER_FRIDAY, [rule])


# --- a time that goes by rules ---------------------------------------------------

CLOCK_7 = {"kind": "clock", "at": "07:00"}
CLOCK_8 = {"kind": "clock", "at": "08:00"}
CLOCK_9 = {"kind": "clock", "at": "09:00"}
SUMMER = {"kind": "clock_season", "season": "summer"}
LATE_SHKIA = {"kind": "zman_range", "zman": "shkia", "from": "19:00"}


def by_rule(*rules, otherwise=CLOCK_7):
    return {
        "kind": "by_rule",
        "rules": [{"when": when, "time": time} for when, time in rules],
        "otherwise": otherwise,
    }


def test_with_no_rules_the_time_is_the_usual_one():
    assert resolve(by_rule()) == at(SUMMER_FRIDAY, "07:00")


def test_a_rule_that_matches_gives_its_time():
    spec = by_rule((SUMMER, CLOCK_8))
    assert resolve(spec, SUMMER_FRIDAY) == at(SUMMER_FRIDAY, "08:00")
    assert resolve(spec, WINTER_FRIDAY) == at(WINTER_FRIDAY, "07:00")


def test_the_first_rule_that_matches_wins():
    spec = by_rule((LATE_SHKIA, CLOCK_9), (SUMMER, CLOCK_8))
    assert resolve(spec, SUMMER_FRIDAY) == at(SUMMER_FRIDAY, "09:00")
    swapped = by_rule((SUMMER, CLOCK_8), (LATE_SHKIA, CLOCK_9))
    assert resolve(swapped, SUMMER_FRIDAY) == at(SUMMER_FRIDAY, "08:00")


def test_a_rule_by_dates():
    june = {"kind": "date_range", "from": "06-01", "to": "06-30"}
    spec = by_rule((june, CLOCK_8))
    assert resolve(spec, TUESDAY) == at(TUESDAY, "08:00")
    assert resolve(spec, WINTER_FRIDAY) == at(WINTER_FRIDAY, "07:00")


def test_a_rule_by_shkia_between_two_times():
    early = {"kind": "zman_range", "zman": "shkia", "from": "16:00", "to": "17:30"}
    late = {"kind": "zman_range", "zman": "shkia", "from": "20:00", "to": "21:00"}
    spec = by_rule((early, CLOCK_8), (late, CLOCK_9))
    assert resolve(spec, WINTER_FRIDAY) == at(WINTER_FRIDAY, "08:00")
    assert resolve(spec, SUMMER_FRIDAY) == at(SUMMER_FRIDAY, "09:00")


def test_each_case_can_be_any_kind_of_time():
    spec = by_rule(
        (SUMMER, {"kind": "zman", "zman": "plag", "offset_minutes": -10}),
        otherwise={"kind": "later_of", "of": [CLOCK_7, {"kind": "zman", "zman": "shkia"}]},
    )
    assert resolve(spec, SUMMER_FRIDAY) == at(SUMMER_FRIDAY, "18:47")
    assert resolve(spec, WINTER_FRIDAY) == at(WINTER_FRIDAY, "16:53")


def test_a_rule_can_be_timed_from_shabbos_start():
    spec = by_rule((SUMMER, {"kind": "zman", "zman": "shabbos_start", "offset_minutes": -5}))
    start = at(SUMMER_FRIDAY, "19:00")
    assert resolve(spec, SUMMER_FRIDAY, shabbos_start=start) == at(SUMMER_FRIDAY, "18:55")


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "by_rule", "otherwise": CLOCK_7},
        {"kind": "by_rule", "rules": "summer", "otherwise": CLOCK_7},
        {"kind": "by_rule", "rules": []},
        {"kind": "by_rule", "rules": [], "otherwise": None},
        {"kind": "by_rule", "rules": [{"when": SUMMER}], "otherwise": CLOCK_7},
        {"kind": "by_rule", "rules": [{"time": CLOCK_8}], "otherwise": CLOCK_7},
        {"kind": "by_rule", "rules": ["summer"], "otherwise": CLOCK_7},
        {"kind": "by_rule", "rules": [{"when": {"kind": "sometimes"}, "time": CLOCK_8}], "otherwise": CLOCK_7},
        {"kind": "by_rule", "rules": [{"when": SUMMER, "time": {"kind": "soon"}}], "otherwise": CLOCK_7},
    ],
)
def test_a_time_by_rules_that_is_not_understood_is_refused(bad):
    with pytest.raises(ScheduleError):
        resolve(bad, SUMMER_FRIDAY)


def test_a_mistake_in_a_rule_is_caught_even_on_a_date_it_does_not_match():
    # In winter the summer rule does not apply, but its missing time is still refused.
    spec = {"kind": "by_rule", "rules": [{"when": SUMMER}], "otherwise": CLOCK_7}
    with pytest.raises(ScheduleError):
        resolve(spec, WINTER_FRIDAY)


DONT_RUN = {"kind": "dont_run"}


def test_a_rule_can_say_dont_run():
    spec = by_rule((SUMMER, DONT_RUN))
    assert runs_on(spec, SUMMER_FRIDAY, SOURCE, TZ) is False
    assert runs_on(spec, WINTER_FRIDAY, SOURCE, TZ) is True
    assert resolve(spec, WINTER_FRIDAY) == at(WINTER_FRIDAY, "07:00")
    with pytest.raises(ScheduleError):
        resolve(spec, SUMMER_FRIDAY)


def test_otherwise_can_say_dont_run():
    spec = by_rule((SUMMER, CLOCK_8), otherwise=DONT_RUN)
    assert runs_on(spec, SUMMER_FRIDAY, SOURCE, TZ) is True
    assert runs_on(spec, WINTER_FRIDAY, SOURCE, TZ) is False


def test_the_first_matching_rule_decides_whether_it_runs():
    spec = by_rule((LATE_SHKIA, DONT_RUN), (SUMMER, CLOCK_8))
    assert runs_on(spec, SUMMER_FRIDAY, SOURCE, TZ) is False


def test_a_plain_time_always_runs_and_cannot_say_dont_run():
    assert runs_on(CLOCK_7, SUMMER_FRIDAY, SOURCE, TZ) is True
    with pytest.raises(ScheduleError):
        resolve(DONT_RUN, SUMMER_FRIDAY)


def test_a_time_by_rules_cannot_hold_another():
    inner = by_rule((SUMMER, CLOCK_8))
    with pytest.raises(ScheduleError, match="another"):
        resolve(by_rule((SUMMER, inner)), SUMMER_FRIDAY)
    with pytest.raises(ScheduleError, match="another"):
        resolve(by_rule(otherwise=inner), SUMMER_FRIDAY)


def test_a_rule_by_a_zman_the_date_does_not_have_cannot_be_decided():
    no_tzeis = {"kind": "zman_range", "zman": "tzeis", "from": "19:00"}
    with pytest.raises(ZmanUnavailableError):
        resolve(by_rule((no_tzeis, CLOCK_8)), WINTER_FRIDAY)
