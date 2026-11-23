"""The settings the house gives the Jewish Calendar integration.

Runs without Home Assistant. The starting settings are the test
installation's own, as read on 23 November 2026.
"""

from __future__ import annotations

import pytest

from engine.calendar_settings import wanted_settings
from engine.time_resolver import ScheduleError

SCHEDULE = {"yom_tov_days": 2, "candle_lighting_minutes": 18, "havdalah_minutes": 72}

DATA = {"diaspora": True, "language": "en", "latitude": 31.78, "time_zone": "Asia/Jerusalem"}
OPTIONS = {
    "candle_lighting_minutes_before_sunset": 18,
    "havdalah_minutes_after_sunset": 72,
    "daily_events": [
        "date", "netz_hachama", "shkia", "tset_hakohavim", "mincha_gedola",
        "mincha_ketana", "plag_hamincha", "alot_hashachar", "chatzot_hayom",
    ],
    "learning_schedule": [],
    "yearly_events": ["holiday", "weekly_portion", "candle_lighting", "havdalah", "omer_count"],
}
SOF_ZMAN = [
    "sof_zman_shema_gra", "sof_zman_shema_mga", "sof_zman_tfilla_gra",
    "sof_zman_tfilla_mga",
]


def test_the_test_installation_only_needs_the_four_sof_zman_events():
    data, options, changes = wanted_settings(SCHEDULE, DATA, OPTIONS)
    assert data == DATA
    assert options["daily_events"] == OPTIONS["daily_events"] + SOF_ZMAN
    assert changes == [f"daily events switched on: {', '.join(SOF_ZMAN)}"]
    # Everything else is left as it was.
    rest = {k: v for k, v in options.items() if k != "daily_events"}
    assert rest == {k: v for k, v in OPTIONS.items() if k != "daily_events"}


def test_nothing_changes_when_everything_already_matches():
    _, options, _ = wanted_settings(SCHEDULE, DATA, OPTIONS)
    data, again, changes = wanted_settings(SCHEDULE, DATA, options)
    assert (data, again, changes) == (DATA, options, [])


def test_wrong_settings_are_put_right():
    """Set to Israel, with other candle lighting and havdalah times."""
    data = {**DATA, "diaspora": False}
    options = {
        **OPTIONS,
        "candle_lighting_minutes_before_sunset": 40,
        "havdalah_minutes_after_sunset": 50,
    }
    new_data, new_options, changes = wanted_settings(SCHEDULE, data, options)
    assert new_data["diaspora"] is True
    assert new_options["candle_lighting_minutes_before_sunset"] == 18
    assert new_options["havdalah_minutes_after_sunset"] == 72
    assert changes[:3] == [
        "Israel or diaspora set to diaspora",
        "candle lighting set to 18 minutes (was 40)",
        "havdalah set to 72 minutes (was 50)",
    ]


def test_one_day_of_yom_tov_sets_israel():
    schedule = {**SCHEDULE, "yom_tov_days": 1}
    data, _, changes = wanted_settings(schedule, DATA, OPTIONS)
    assert data["diaspora"] is False
    assert "Israel or diaspora set to Israel" in changes


def test_another_language_is_set_to_english():
    data, _, changes = wanted_settings(SCHEDULE, {**DATA, "language": "he"}, OPTIONS)
    assert data["language"] == "en"
    assert "language set to English (was he)" in changes


def test_events_the_house_already_shows_are_kept():
    options = {**OPTIONS, "yearly_events": ["omer_count"], "daily_events": []}
    _, new_options, changes = wanted_settings(SCHEDULE, DATA, options)
    assert new_options["yearly_events"] == ["omer_count", "candle_lighting", "havdalah"]
    assert new_options["daily_events"][0] == "date"
    assert len(new_options["daily_events"]) == 13
    assert "yearly events switched on: candle_lighting, havdalah" in changes


def test_location_and_other_settings_are_never_touched():
    data, options, _ = wanted_settings(SCHEDULE, DATA, OPTIONS)
    assert data["latitude"] == 31.78 and data["time_zone"] == "Asia/Jerusalem"
    assert options["learning_schedule"] == []


def test_the_current_settings_are_not_altered_in_place():
    before_data, before_options = dict(DATA), {k: list(v) if isinstance(v, list) else v for k, v in OPTIONS.items()}
    wanted_settings({**SCHEDULE, "yom_tov_days": 1}, DATA, OPTIONS)
    assert DATA == before_data and OPTIONS == before_options


@pytest.mark.parametrize(
    "bad",
    [
        {"yom_tov_days": 3},
        {"yom_tov_days": None},
        {"candle_lighting_minutes": "18"},
        {"candle_lighting_minutes": -5},
        {"havdalah_minutes": 72.5},
        {"havdalah_minutes": None},
    ],
)
def test_schedule_settings_that_make_no_sense_are_refused(bad):
    with pytest.raises(ScheduleError):
        wanted_settings({**SCHEDULE, **bad}, DATA, OPTIONS)
