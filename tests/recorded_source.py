"""A calendar source for tests, backed by events recorded from a real
Jewish Calendar integration (tests/recorded/jewish_calendar_events.json).

It knows only the dates that were recorded. Asking for anything else about
the Hebrew date raises, so a test can never pass on data that was not read
from Home Assistant.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from engine import calendar_source as cs

_FILE = Path(__file__).parent / "recorded" / "jewish_calendar_events.json"

# Event summaries as the integration gives them with Home Assistant in English.
ZMAN_SUMMARIES = {
    "Alot HaShachar": "alos",
    "Netz Hachama": "netz",
    "Chatzot Hayom": "chatzos",
    "Mincha Gedola": "mincha_gedola",
    "Mincha Ketana": "mincha_ketana",
    "Plag Hamincha": "plag",
    "Shkia": "shkia",
    "Tset Hakochavim (18 minutes)": "tzeis",
    "Candle Lighting": "candle_lighting",
    "Havdalah": "havdalah",
}

# Only the month names seen in the recording so far.
_MONTHS = {"Kislev": cs.KISLEV}


class RecordedSource:
    def __init__(self) -> None:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        self._zmanim: dict[tuple[date, str], datetime] = {}
        self._hebrew_dates: dict[date, cs.HebrewDate] = {}
        self.holidays: dict[date, str] = {}

        for event in data["daily"] + data["yearly"]:
            start, summary = event["start"], event["summary"]
            description = event.get("description", "")
            if "T" in start:
                moment = datetime.fromisoformat(start)
                self._zmanim[(moment.date(), ZMAN_SUMMARIES[summary])] = moment
            elif description.startswith("Hebrew date:"):
                day, month, year = summary.split()
                self._hebrew_dates[date.fromisoformat(start)] = cs.HebrewDate(
                    int(year), _MONTHS[month], int(day)
                )
            elif description.startswith("Jewish Holiday:"):
                self.holidays[date.fromisoformat(start)] = summary

    def hebrew_date(self, day: date) -> cs.HebrewDate:
        return self._hebrew_dates[day]

    def zman(self, day: date, key: str) -> datetime | None:
        return self._zmanim.get((day, key))
