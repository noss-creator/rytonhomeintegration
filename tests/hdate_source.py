"""A calendar source for tests only, backed by the hdate library.

The engine never imports hdate. In a house the Hebrew date comes from Home
Assistant's Jewish Calendar integration. This stands in for it until results
recorded from a real installation are available.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import hdate
from hdate.hebrew_date import Months

from engine import calendar_source as cs

_MONTHS = {
    Months.TISHREI: cs.TISHREI,
    Months.MARCHESHVAN: cs.CHESHVAN,
    Months.KISLEV: cs.KISLEV,
    Months.TEVET: cs.TEVES,
    Months.SHVAT: cs.SHEVAT,
    Months.ADAR: cs.ADAR,
    Months.ADAR_I: cs.ADAR_1,
    Months.ADAR_II: cs.ADAR_2,
    Months.NISAN: cs.NISAN,
    Months.IYYAR: cs.IYAR,
    Months.SIVAN: cs.SIVAN,
    Months.TAMMUZ: cs.TAMMUZ,
    Months.AV: cs.AV,
    Months.ELUL: cs.ELUL,
}


@lru_cache(maxsize=None)
def _convert(day: date) -> cs.HebrewDate:
    h = hdate.HebrewDate.from_gdate(day)
    return cs.HebrewDate(h.year, _MONTHS[h.month], h.day)


class HdateSource:
    def hebrew_date(self, day: date) -> cs.HebrewDate:
        return _convert(day)
