"""What the Jewish Calendar integration's settings must be for a schedule.

The house keeps that integration in step with its schedule: candle lighting
and havdalah minutes, Israel or diaspora, English event names, and every
event the engine reads switched on. This module works out the settings and
says what would change. It does not touch Home Assistant.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .time_resolver import ScheduleError

# The Jewish Calendar integration's own names for its settings.
DIASPORA = "diaspora"
LANGUAGE = "language"
CANDLE_LIGHTING = "candle_lighting_minutes_before_sunset"
HAVDALAH = "havdalah_minutes_after_sunset"
DAILY_EVENTS = "daily_events"
YEARLY_EVENTS = "yearly_events"

# Every event the engine reads.
REQUIRED_DAILY_EVENTS = (
    "date", "alot_hashachar", "netz_hachama", "sof_zman_shema_gra",
    "sof_zman_shema_mga", "sof_zman_tfilla_gra", "sof_zman_tfilla_mga",
    "chatzot_hayom", "mincha_gedola", "mincha_ketana", "plag_hamincha", "shkia",
    "tset_hakohavim",
)
REQUIRED_YEARLY_EVENTS = ("candle_lighting", "havdalah")


def _with_required(current: Any, required: tuple[str, ...]) -> list[str]:
    """Keep what is switched on already and add what the engine needs."""
    events = list(current) if isinstance(current, (list, tuple)) else []
    return events + [event for event in required if event not in events]


def wanted_settings(
    settings: Mapping[str, Any],
    data: Mapping[str, Any],
    options: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Return the Jewish Calendar's new data, new options, and what changed.

    ``settings`` is the schedule's ``settings``. ``data`` and ``options`` are
    the Jewish Calendar's current ones. Settings the engine has no say over
    are kept as they are. The list of changes is empty when nothing differs.
    """
    yom_tov_days = settings.get("yom_tov_days")
    if yom_tov_days not in (1, 2):
        raise ScheduleError(f"yom_tov_days must be 1 or 2, not {yom_tov_days!r}")
    minutes = {}
    for key, name in (
        ("candle_lighting_minutes", CANDLE_LIGHTING),
        ("havdalah_minutes", HAVDALAH),
    ):
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ScheduleError(f"{key} must be a whole number of minutes, not {value!r}")
        minutes[name] = value

    new_data = dict(data)
    new_data[DIASPORA] = yom_tov_days == 2
    new_data[LANGUAGE] = "en"

    new_options = dict(options)
    new_options.update(minutes)
    new_options[DAILY_EVENTS] = _with_required(
        options.get(DAILY_EVENTS), REQUIRED_DAILY_EVENTS
    )
    new_options[YEARLY_EVENTS] = _with_required(
        options.get(YEARLY_EVENTS), REQUIRED_YEARLY_EVENTS
    )

    changes: list[str] = []
    if data.get(DIASPORA) != new_data[DIASPORA]:
        place = "diaspora" if new_data[DIASPORA] else "Israel"
        changes.append(f"Israel or diaspora set to {place}")
    if data.get(LANGUAGE, "en") != "en":
        changes.append(f"language set to English (was {data.get(LANGUAGE)})")
    for name, label in ((CANDLE_LIGHTING, "candle lighting"), (HAVDALAH, "havdalah")):
        if options.get(name) != new_options[name]:
            changes.append(
                f"{label} set to {new_options[name]} minutes (was {options.get(name)})"
            )
    for name, label in ((DAILY_EVENTS, "daily"), (YEARLY_EVENTS, "yearly")):
        added = [e for e in new_options[name] if e not in (options.get(name) or [])]
        if added:
            changes.append(f"{label} events switched on: {', '.join(added)}")

    return new_data, new_options, changes
