"""The days, their calendar dates and the combination rules, as data.

The two kinds of house (one or two days of Yom Tov) share all the logic in
``day_resolver`` and differ only in the table built here. Identifiers are the
ones in SCHEDULE_FORMAT.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from .calendar_source import ADAR, ADAR_2, AV, ELUL, NISAN, SIVAN, TISHREI

# Weekday numbers as datetime.date.weekday() gives them.
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
ANY_WEEKDAY = (MON, TUE, WED, THU, FRI, SAT, SUN)

# The three regular-week days a date falls back to.
WEEKDAY = "weekday"
FRIDAY = "friday"
SHABBOS = "shabbos"

# The occasions that are Chol Hamoed. A house chooses whether its early
# Shabbos rules apply on a Friday of Chol Hamoed. Unless it says so, they do not.
CHOL_HAMOED = ("chol_hamoed_succos", "chol_hamoed_pesach")

# Purim is in Adar, or in Adar II of a leap year.
PURIM_MONTHS = (ADAR, ADAR_2)


@dataclass(frozen=True)
class DateRule:
    """Matches a Hebrew month and day, optionally only on some weekdays."""

    months: tuple[str, ...]
    days: tuple[int, ...]
    weekdays: tuple[int, ...] = ANY_WEEKDAY


@dataclass(frozen=True)
class Occasion:
    """Something the Hebrew calendar puts on a date.

    A standalone occasion is a day with its own automations. One that is not
    standalone exists only through its combination day.
    """

    id: str
    rules: tuple[DateRule, ...]
    standalone: bool = True


@dataclass(frozen=True)
class Combination:
    """The entry that decides a date where an occasion meets a regular-week day.

    ``when_off`` is the day the date runs while the combination is switched off.
    """

    id: str
    occasion: str
    on: str
    when_off: str


@dataclass(frozen=True)
class DayTable:
    occasions: tuple[Occasion, ...]
    # Shabbosos that are their own day when no occasion falls on them.
    shabbos_variants: tuple[Occasion, ...]
    combinations: tuple[Combination, ...]
    # (occasion, regular-week day) pairs that deliberately have no combination:
    # the date runs the occasion's own day.
    uncombined: frozenset[tuple[str, str]]
    # Occasions that, on a Friday, are followed by a Shabbos that is Yom Tov
    # (or Yom Kippur). Early Shabbos never applies to Yom Tov, so the early
    # Shabbos rules are skipped on such a Friday.
    friday_before_yom_tov: frozenset[str] = frozenset()


def _on(month: str, *days: int, weekdays: tuple[int, ...] = ANY_WEEKDAY) -> DateRule:
    return DateRule((month,), days, weekdays)


def _combo(occasion: str, on: str) -> Combination:
    """A combination named the usual way; switched off, the occasion's own day runs."""
    return Combination(f"{occasion}__{on}", occasion, on, when_off=occasion)


_NOT_FRIDAY = (MON, TUE, WED, THU, SAT, SUN)
_NOT_SHABBOS = (MON, TUE, WED, THU, FRI, SUN)

SHABBOS_VARIANTS = (
    Occasion("shabbos_shuva", (_on(TISHREI, 3, 4, 5, 6, 7, 8, 9, weekdays=(SAT,)),)),
    Occasion("shabbos_hagadol", (_on(NISAN, 8, 9, 10, 11, 12, 13, 14, weekdays=(SAT,)),)),
)

# Occasions that are the same in every house.
_COMMON_OCCASIONS = (
    Occasion("erev_rosh_hashana", (_on(ELUL, 29),)),
    Occasion("rosh_hashana_1", (_on(TISHREI, 1),)),
    Occasion("rosh_hashana_2", (_on(TISHREI, 2),)),
    Occasion("erev_yom_kippur", (_on(TISHREI, 9),)),
    Occasion("yom_kippur", (_on(TISHREI, 10),)),
    Occasion("erev_succos", (_on(TISHREI, 14),)),
    Occasion("hoshana_rabba", (_on(TISHREI, 21),)),
    # 13 Nisan, or Thursday 12 Nisan when Erev Pesach is on Shabbos.
    Occasion(
        "bedikas_chametz",
        (_on(NISAN, 13, weekdays=_NOT_FRIDAY), _on(NISAN, 12, weekdays=(THU,))),
    ),
    # Friday 13 Nisan, the day before Erev Pesach on Shabbos.
    Occasion(
        "day_before_erev_pesach_shabbos",
        (_on(NISAN, 13, weekdays=(FRI,)),),
        standalone=False,
    ),
    Occasion("erev_pesach", (_on(NISAN, 14),)),
    Occasion("erev_shvii_pesach", (_on(NISAN, 20),)),
    Occasion("erev_shavuos", (_on(SIVAN, 5),)),
    # 8 Av, unless it is the Friday before a 9 Av on Shabbos.
    Occasion("erev_tisha_bav", (_on(AV, 8, weekdays=_NOT_FRIDAY),)),
    # 9 Av, or Sunday 10 Av when 9 Av is on Shabbos.
    Occasion(
        "tisha_bav",
        (_on(AV, 9, weekdays=_NOT_SHABBOS), _on(AV, 10, weekdays=(SUN,))),
    ),
    Occasion("tisha_bav_deferred", (_on(AV, 9, weekdays=(SAT,)),), standalone=False),
)

_TWO_DAY_OCCASIONS = (
    Occasion("succos_1", (_on(TISHREI, 15),)),
    Occasion("succos_2", (_on(TISHREI, 16),)),
    Occasion("chol_hamoed_succos", (_on(TISHREI, 17, 18, 19, 20),)),
    Occasion("shmini_atzeres", (_on(TISHREI, 22),)),
    Occasion("simchas_torah", (_on(TISHREI, 23),)),
    Occasion("pesach_1", (_on(NISAN, 15),)),
    Occasion("pesach_2", (_on(NISAN, 16),)),
    Occasion("chol_hamoed_pesach", (_on(NISAN, 17, 18, 19),)),
    Occasion("shvii_pesach", (_on(NISAN, 21),)),
    Occasion("acharon_pesach", (_on(NISAN, 22),)),
    Occasion("shavuos_1", (_on(SIVAN, 6),)),
    Occasion("shavuos_2", (_on(SIVAN, 7),)),
)

# One day of Yom Tov. `simchas_torah` and `shvii_pesach` name a different day
# here than in a two-day house, as SCHEDULE_FORMAT.md says.
_ONE_DAY_OCCASIONS = (
    Occasion("succos", (_on(TISHREI, 15),)),
    Occasion("chol_hamoed_succos", (_on(TISHREI, 16, 17, 18, 19, 20),)),
    Occasion("simchas_torah", (_on(TISHREI, 22),)),
    Occasion("pesach", (_on(NISAN, 15),)),
    Occasion("chol_hamoed_pesach", (_on(NISAN, 16, 17, 18, 19),)),
    Occasion("shvii_pesach", (_on(NISAN, 21),)),
    Occasion("shavuos", (_on(SIVAN, 6),)),
)

_PURIM_REGULAR_OCCASIONS = (
    Occasion("erev_purim", (DateRule(PURIM_MONTHS, (13,)),)),
    Occasion("purim", (DateRule(PURIM_MONTHS, (14,)),)),
)

_PURIM_SHUSHAN_OCCASIONS = (
    Occasion("erev_purim", (DateRule(PURIM_MONTHS, (14,)),)),
    Occasion("purim", (DateRule(PURIM_MONTHS, (15,)),)),
    # Sunday 16 Adar, after Purim on Shabbos, when the seuda is held.
    Occasion(
        "sunday_after_purim",
        (DateRule(PURIM_MONTHS, (16,), (SUN,)),),
        standalone=False,
    ),
)

_COMMON_COMBINATIONS = (
    _combo("erev_rosh_hashana", FRIDAY),
    _combo("rosh_hashana_2", FRIDAY),
    _combo("erev_yom_kippur", FRIDAY),
    _combo("erev_succos", FRIDAY),
    _combo("chol_hamoed_succos", FRIDAY),
    _combo("hoshana_rabba", FRIDAY),
    Combination(
        "friday_before_erev_pesach_shabbos",
        "day_before_erev_pesach_shabbos",
        FRIDAY,
        when_off=FRIDAY,
    ),
    _combo("erev_pesach", FRIDAY),
    _combo("chol_hamoed_pesach", FRIDAY),
    _combo("erev_shvii_pesach", FRIDAY),
    _combo("shvii_pesach", FRIDAY),
    _combo("rosh_hashana_1", SHABBOS),
    _combo("chol_hamoed_succos", SHABBOS),
    _combo("erev_pesach", SHABBOS),
    _combo("chol_hamoed_pesach", SHABBOS),
    _combo("shvii_pesach", SHABBOS),
    _combo("erev_shavuos", SHABBOS),
    _combo("erev_tisha_bav", SHABBOS),
    Combination(
        "tisha_bav_deferred__shabbos", "tisha_bav_deferred", SHABBOS, when_off=SHABBOS
    ),
)

_TWO_DAY_COMBINATIONS = (
    _combo("succos_2", FRIDAY),
    _combo("simchas_torah", FRIDAY),
    _combo("pesach_2", FRIDAY),
    _combo("shavuos_1", FRIDAY),
    _combo("succos_1", SHABBOS),
    _combo("shmini_atzeres", SHABBOS),
    _combo("pesach_1", SHABBOS),
    _combo("acharon_pesach", SHABBOS),
    _combo("shavuos_2", SHABBOS),
)

_ONE_DAY_COMBINATIONS = (
    _combo("shavuos", FRIDAY),
    _combo("succos", SHABBOS),
    _combo("simchas_torah", SHABBOS),
    _combo("pesach", SHABBOS),
)

_PURIM_REGULAR_COMBINATIONS = (
    _combo("purim", FRIDAY),
    _combo("erev_purim", SHABBOS),
)

_PURIM_SHUSHAN_COMBINATIONS = (
    _combo("purim", FRIDAY),
    _combo("erev_purim", FRIDAY),
    _combo("purim", SHABBOS),
    Combination(
        "sunday_after_purim_shabbos", "sunday_after_purim", WEEKDAY, when_off=WEEKDAY
    ),
)

# On a Friday, each of these is followed by a Shabbos that is Yom Tov.
_ERUVEI_YOM_TOV = frozenset(
    {
        "erev_rosh_hashana", "erev_yom_kippur", "erev_succos", "hoshana_rabba",
        "erev_pesach", "erev_shvii_pesach",
    }
)
# With two days of Yom Tov, so are these: the next day is the second day.
_TWO_DAY_FIRST_DAYS = frozenset({"shvii_pesach", "shavuos_1"})

# Yom Kippur on Shabbos has no combination. That date runs the Yom Kippur day.
_UNCOMBINED = frozenset({("yom_kippur", SHABBOS)})

PURIM_REGULAR = "regular"
PURIM_SHUSHAN = "shushan"


def table_for(yom_tov_days: int, purim: str) -> DayTable:
    """Return the day table for a house's ``yom_tov_days`` and ``purim`` settings."""
    if yom_tov_days == 2:
        occasions = _COMMON_OCCASIONS + _TWO_DAY_OCCASIONS
        combinations = _COMMON_COMBINATIONS + _TWO_DAY_COMBINATIONS
        before_yom_tov = _ERUVEI_YOM_TOV | _TWO_DAY_FIRST_DAYS
    elif yom_tov_days == 1:
        occasions = _COMMON_OCCASIONS + _ONE_DAY_OCCASIONS
        combinations = _COMMON_COMBINATIONS + _ONE_DAY_COMBINATIONS
        before_yom_tov = _ERUVEI_YOM_TOV
    else:
        raise ValueError(f"yom_tov_days must be 1 or 2, not {yom_tov_days!r}")

    if purim == PURIM_REGULAR:
        occasions += _PURIM_REGULAR_OCCASIONS
        combinations += _PURIM_REGULAR_COMBINATIONS
    elif purim == PURIM_SHUSHAN:
        occasions += _PURIM_SHUSHAN_OCCASIONS
        combinations += _PURIM_SHUSHAN_COMBINATIONS
    else:
        raise ValueError(f"purim must be 'regular' or 'shushan', not {purim!r}")

    return DayTable(
        occasions, SHABBOS_VARIANTS, combinations, _UNCOMBINED, before_yom_tov
    )
