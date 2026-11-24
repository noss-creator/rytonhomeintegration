"""The schedule running inside a real Home Assistant core, with its clock moved by hand.

A year passes in seconds. This checks what cannot be checked any other way:
that every automation fires at its time, that the daily rollover fixes the
next day's list, and that a restart is caught up.

The devices are pretend ones. The made-up schedule of tests/test_day_list.py
gives every automation one scene named after its day, so the record of
scenes turned on shows exactly what ran and when.

Needs Home Assistant's test tools, which do not load on Windows. On GitHub
these tests run on Linux.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock

import pytest

_common = pytest.importorskip("pytest_homeassistant_custom_component.common")
MockConfigEntry = _common.MockConfigEntry
async_fire_time_changed = _common.async_fire_time_changed

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402

from custom_components.ryton_home_automations import scheduler as scheduler_module  # noqa: E402
from custom_components.ryton_home_automations.const import DOMAIN  # noqa: E402
from engine.day_list import build_day_list  # noqa: E402

from .hdate_source import HdateSource  # noqa: E402
from .test_day_list import make_schedule  # noqa: E402
from .test_in_home_assistant import TZ, _stand_in_events  # noqa: E402

START = date(2026, 11, 23)


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def _instant_waits(monkeypatch):
    """The pauses and the 10-second checks take no time in these tests."""

    async def no_wait(seconds):
        return None

    monkeypatch.setattr(scheduler_module, "_sleep", no_wait)


def local(day: date, clock: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(clock), TZ)


class ExpectedSource(HdateSource):
    """The same made-up zmanim the stand-in calendar answers with."""

    _EVERY_DAY = {"alos": "04:40", "netz": "06:00", "plag": "16:45", "shkia": "18:00", "tzeis": "18:40"}

    def zman(self, day, key):
        clock = self._EVERY_DAY.get(key)
        if key == "candle_lighting" and day.weekday() == 4:
            clock = "17:42"
        if key == "havdalah" and day.weekday() == 5:
            clock = "19:12"
        return local(day, clock) if clock else None


def expected_runs(schedule, first: date, days: int):
    """What the engine says should run, as (time, scene) in time order."""
    source = ExpectedSource()
    runs = []
    for n in range(days):
        day_list = build_day_list(schedule, first + timedelta(days=n), source, TZ)
        for automation in day_list.automations:
            [room] = automation.rooms.values()
            runs.append((automation.time, room["scene"]))
    return sorted(runs)


class House:
    def __init__(self, hass, freezer, folder):
        self.hass, self.freezer, self.folder = hass, freezer, folder
        self.scenes: list[tuple[datetime, str]] = []
        self.light_calls: list[tuple[str, str]] = []
        self.ignore: dict[str, int] = {}
        self.entry = None
        self.entry_data: dict = {}

    async def move_to(self, when: datetime) -> None:
        self.freezer.move_to(when)
        async_fire_time_changed(self.hass, when)
        await self.hass.async_block_till_done()

    def write_schedule(self, schedule) -> None:
        (self.folder / "ryton_schedule.json").write_text(json.dumps(schedule), encoding="utf-8")

    async def reload_schedule(self):
        return await self.hass.services.async_call(
            DOMAIN, "reload_schedule", {}, blocking=True, return_response=True
        )

    async def start_integration(self) -> None:
        if self.entry is None:
            self.entry = MockConfigEntry(
                domain=DOMAIN, title="Ryton Home Automations", data=self.entry_data
            )
            self.entry.add_to_hass(self.hass)
        assert await self.hass.config_entries.async_setup(self.entry.entry_id)
        await self.hass.async_block_till_done()

    async def stop_integration(self) -> None:
        assert await self.hass.config_entries.async_unload(self.entry.entry_id)
        await self.hass.async_block_till_done()

    def scene_times(self):
        return [(when.astimezone(TZ), scene) for when, scene in self.scenes]


@pytest.fixture
async def house(hass: HomeAssistant, freezer, tmp_path, monkeypatch):
    """A Home Assistant at 03:00 on the first day, with pretend devices."""
    await hass.config.async_set_time_zone("Asia/Jerusalem")
    hass.config.config_dir = str(tmp_path)
    freezer.move_to(local(START, "03:00"))
    assert await async_setup_component(hass, "calendar", {})
    home = House(hass, freezer, tmp_path)

    async def get_events(call: ServiceCall):
        start = datetime.fromisoformat(call.data["start_date_time"])
        end = datetime.fromisoformat(call.data["end_date_time"])
        return {
            entity_id: {"events": _stand_in_events(entity_id, start, end)}
            for entity_id in call.data["entity_id"]
        }

    async def scene_on(call: ServiceCall) -> None:
        home.scenes.append((dt_util.now(), call.data["entity_id"]))

    async def light(call: ServiceCall) -> None:
        entity_id = call.data["entity_id"]
        home.light_calls.append((entity_id, call.service))
        if home.ignore.get(entity_id, 0) > 0:
            home.ignore[entity_id] -= 1
            return
        if hass.states.get(entity_id) is not None:
            hass.states.async_set(entity_id, "on" if call.service == "turn_on" else "off")

    hass.services.async_register(
        "calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register("scene", "turn_on", scene_on)
    hass.services.async_register("light", "turn_on", light)
    hass.services.async_register("light", "turn_off", light)

    # A Jewish Calendar entry set wrongly on purpose. It is never loaded, so
    # reloading it is replaced by a recorder.
    jewish_calendar = MockConfigEntry(
        domain="jewish_calendar",
        data={"diaspora": False, "language": "en"},
        options={
            "candle_lighting_minutes_before_sunset": 35,
            "havdalah_minutes_after_sunset": 40,
            "daily_events": ["date"],
            "yearly_events": [],
        },
    )
    jewish_calendar.add_to_hass(hass)
    home.jewish_calendar = jewish_calendar
    home.calendar_reloaded = AsyncMock(return_value=True)
    monkeypatch.setattr(hass.config_entries, "async_reload", home.calendar_reloaded)

    home.write_schedule(make_schedule())
    await home.start_integration()
    return home


# --- the Jewish Calendar's settings ----------------------------------------


async def test_reload_sets_the_jewish_calendar_to_match_the_schedule(house):
    response = await house.reload_schedule()
    entry = house.jewish_calendar
    assert entry.data["diaspora"] is True
    assert entry.options["candle_lighting_minutes_before_sunset"] == 18
    assert entry.options["havdalah_minutes_after_sunset"] == 72
    assert "sof_zman_tfilla_gra" in entry.options["daily_events"]
    assert entry.options["yearly_events"] == ["candle_lighting", "havdalah"]
    assert response["jewish_calendar_changes"][:3] == [
        "Israel or diaspora set to diaspora",
        "candle lighting set to 18 minutes (was 35)",
        "havdalah set to 72 minutes (was 40)",
    ]
    house.calendar_reloaded.assert_awaited_once_with(entry.entry_id)

    again = await house.reload_schedule()
    assert again["jewish_calendar_changes"] == []
    house.calendar_reloaded.assert_awaited_once()  # not reloaded when nothing changed


# --- a day, and then a year ------------------------------------------------


async def test_first_start_does_not_replay_the_day(house):
    await house.move_to(local(START, "15:00"))
    response = await house.reload_schedule()
    assert house.scenes == []
    assert [a["id"] for a in response["upcoming"]] == ["sunset", "night"]
    await house.move_to(local(START, "18:00"))
    await house.move_to(local(START, "23:00"))
    assert house.scene_times() == [
        (local(START, "18:00"), "scene.weekday"),
        (local(START, "23:00"), "scene.weekday"),
    ]


async def test_each_automation_runs_once_at_its_own_time(house):
    await house.reload_schedule()
    for clock in ("06:59", "07:00", "07:01", "12:00", "18:00", "22:59", "23:00", "23:30"):
        await house.move_to(local(START, clock))
    assert house.scene_times() == [
        (local(START, "07:00"), "scene.weekday"),
        (local(START, "18:00"), "scene.weekday"),
        (local(START, "23:00"), "scene.weekday"),
    ]


async def _walk(house, schedule, days):
    """Move the clock through every rollover and every automation of ``days`` dates."""
    expected = expected_runs(schedule, START, days)
    by_day: dict[date, list[datetime]] = {}
    for when, _ in expected:
        by_day.setdefault(when.astimezone(TZ).date(), []).append(when)
    for n in range(days):
        day = START + timedelta(days=n)
        if n:
            await house.move_to(local(day, "04:00"))  # the rollover
        for when in sorted(set(by_day.get(day, []))):
            await house.move_to(when)
    return expected


async def test_a_fortnight_runs_exactly_what_the_engine_lists(house):
    schedule = make_schedule()
    await house.reload_schedule()
    expected = await _walk(house, schedule, 14)
    assert house.scene_times() == expected
    # The fortnight from 23 November 2026 reaches the first nights of Chanukah.
    assert {scene for _, scene in expected} == {
        "scene.weekday", "scene.friday", "scene.shabbos", "scene.chanukah",
    }


async def test_a_whole_year_runs_exactly_what_the_engine_lists(house):
    """Every day of a year: Chanukah, Purim, Pesach, the Omer, Shavuos, Selichos, Tishrei."""
    schedule = make_schedule()
    await house.reload_schedule()
    expected = await _walk(house, schedule, 366)
    ran = house.scene_times()
    assert len(ran) == len(expected)
    assert ran == expected
    scenes = {scene for _, scene in expected}
    assert {"scene.chanukah", "scene.omer", "scene.selichos"} <= scenes
    assert {"scene.purim", "scene.pesach_1", "scene.rosh_hashana_1__shabbos"} <= scenes


async def test_the_rollover_is_what_brings_in_the_next_day(house):
    """Without passing 04:00, tomorrow's automations are not scheduled."""
    await house.reload_schedule()
    tomorrow = START + timedelta(days=1)
    for clock in ("07:00", "18:00", "23:00"):
        await house.move_to(local(START, clock))
    assert len(house.scenes) == 3
    await house.move_to(local(tomorrow, "04:00"))
    await house.move_to(local(tomorrow, "07:00"))
    assert house.scene_times()[-1] == (local(tomorrow, "07:00"), "scene.weekday")


# --- restarts --------------------------------------------------------------


async def test_a_restart_catches_up_what_was_missed_and_nothing_else(house):
    await house.reload_schedule()
    await house.move_to(local(START, "07:00"))
    assert len(house.scenes) == 1

    await house.stop_integration()
    await house.move_to(local(START, "20:00"))  # Sunset at 18:00 was missed
    assert len(house.scenes) == 1
    await house.start_integration()

    # Morning ran before the restart and is not run again.
    assert house.scene_times() == [
        (local(START, "07:00"), "scene.weekday"),
        (local(START, "20:00"), "scene.weekday"),
    ]
    await house.move_to(local(START, "23:00"))
    assert len(house.scenes) == 3


async def test_two_missed_automations_bring_the_room_to_its_latest_state_once(house):
    friday = START + timedelta(days=4)
    await house.reload_schedule()
    for n in range(1, 5):
        await house.move_to(local(START + timedelta(days=n), "04:00"))
    await house.move_to(local(friday, "07:00"))
    before = len(house.scenes)

    await house.stop_integration()
    await house.move_to(local(friday, "20:00"))  # Erev Shabbos and Sunset were missed
    await house.start_integration()

    caught_up = house.scene_times()[before:]
    assert caught_up == [(local(friday, "20:00"), "scene.friday")]


async def test_a_restart_with_nothing_missed_runs_nothing(house):
    await house.reload_schedule()
    await house.move_to(local(START, "07:00"))
    await house.stop_integration()
    await house.move_to(local(START, "09:00"))
    await house.start_integration()
    assert len(house.scenes) == 1
    await house.move_to(local(START, "18:00"))
    assert len(house.scenes) == 2


async def test_the_schedule_survives_a_restart(house):
    await house.reload_schedule()
    await house.stop_integration()
    (house.folder / "ryton_schedule.json").unlink()
    await house.start_integration()
    await house.move_to(local(START, "07:00"))
    assert len(house.scenes) == 1


# --- check and retry, through Home Assistant's own service calls -----------


def _with_lights(*entity_ids):
    schedule = make_schedule()
    schedule["days"]["weekday"]["automations"][0]["rooms"] = {
        "kitchen": {"entities": {entity_id: {"state": "on"} for entity_id in entity_ids}}
    }
    return schedule


async def test_a_light_that_misses_once_is_sent_again(house, caplog):
    house.hass.states.async_set("light.a", "off")
    house.hass.states.async_set("light.b", "off")
    house.ignore = {"light.a": 1}
    house.write_schedule(_with_lights("light.a", "light.b"))
    await house.reload_schedule()
    await house.move_to(local(START, "07:00"))
    assert house.light_calls == [
        ("light.a", "turn_on"), ("light.b", "turn_on"), ("light.a", "turn_on"),
    ]
    assert house.hass.states.get("light.a").state == "on"
    assert "still failing" not in caplog.text


async def test_what_still_fails_after_three_tries_is_reported(house, caplog):
    house.hass.states.async_set("light.a", "off")
    house.hass.states.async_set("light.stuck", "off")
    house.ignore = {"light.stuck": 99}
    house.write_schedule(_with_lights("light.a", "light.stuck", "light.gone"))
    await house.reload_schedule()
    await house.move_to(local(START, "07:00"))
    assert house.light_calls.count(("light.stuck", "turn_on")) == 3
    assert house.light_calls.count(("light.gone", "turn_on")) == 3
    assert house.light_calls.count(("light.a", "turn_on")) == 1
    assert "2 still failing after three tries" in caplog.text
    assert "light.stuck: its state is off" in caplog.text
    assert "light.gone: Home Assistant has no such entity" in caplog.text


# --- running through every automation --------------------------------------


async def test_run_through_carries_out_every_automation_of_every_day(house):
    schedule = make_schedule()
    await house.reload_schedule()
    response = await house.hass.services.async_call(
        DOMAIN, "run_through", {"check_wait_seconds": 0}, blocking=True, return_response=True
    )
    total = sum(len(day["automations"]) for day in schedule["days"].values()) + 3
    assert response["started"] is True and response["automations"] == total
    await house.hass.async_block_till_done(wait_background_tasks=True)
    assert len(house.scenes) == total
    assert {scene for _, scene in house.scenes} >= {f"scene.{day}" for day in schedule["days"]}
    report = (house.folder / "ryton_run_through.txt").read_text(encoding="utf-8")
    assert report.startswith(f"Run-through finished: {total} of {total} automations run, 0 entities failed.")


async def test_run_through_over_dates_runs_each_kind_of_day_once(house):
    await house.reload_schedule()
    await house.hass.services.async_call(
        DOMAIN,
        "run_through",
        {"start_date": "2027-06-14", "days": 14, "check_wait_seconds": 0},
        blocking=True,
        return_response=True,
    )
    await house.hass.async_block_till_done(wait_background_tasks=True)
    assert [scene for _, scene in house.scenes] == (
        ["scene.weekday"] * 3 + ["scene.friday"] * 4 + ["scene.shabbos"] * 3
    )
