"""Runs the house's schedule inside Home Assistant.

It keeps the schedule in the integration's own storage, fixes each day's
list, sets a timer for every automation, carries each one out, and catches
up after a restart. Every decision is made by the engine; this file only
connects the engine to Home Assistant.

Nothing here uses the network. The house runs from its stored schedule.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components import persistent_notification
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .calendar_reader import async_read_calendar
from .const import DOMAIN
from .engine.actions import Call, latest_state, plan_steps
from .engine.calendar_settings import wanted_settings
from .engine.calendar_snapshot import CalendarDataError
from .engine.day_list import (
    DayList,
    ScheduledAutomation,
    build_day_list,
    check_schedule,
)
from .engine.day_resolver import UnresolvedDayError
from .engine.due import split_due
from .engine.preview import LOOK_AHEAD_DAYS, LOOK_BACK_DAYS
from .engine.runner import carry_out
from .engine.time_resolver import (
    PastRolloverError,
    ScheduleError,
    ZmanUnavailableError,
)

_LOGGER = logging.getLogger(__name__)

JEWISH_CALENDAR = "jewish_calendar"
TITLE = "Ryton Home Automations"
STORAGE_VERSION = 1

ENGINE_ERRORS = (
    CalendarDataError,
    PastRolloverError,
    ScheduleError,
    UnresolvedDayError,
    ZmanUnavailableError,
)


class Scheduler:
    """The house's running schedule."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.schedule: dict[str, Any] | None = None
        self.last_run: datetime | None = None
        self.day_lists: list[DayList] = []
        self.upcoming: list[ScheduledAutomation] = []
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.state"
        )
        self._timers: list[CALLBACK_TYPE] = []
        self._rollover: CALLBACK_TYPE | None = None
        self._running = asyncio.Lock()

    # --- storage ----------------------------------------------------------

    async def async_load(self) -> None:
        """Read the stored schedule, if there is one."""
        stored = await self._store.async_load() or {}
        self.schedule = stored.get("schedule")
        last_run = stored.get("last_run")
        self.last_run = dt_util.parse_datetime(last_run) if last_run else None

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "schedule": self.schedule,
                "last_run": self.last_run.isoformat() if self.last_run else None,
            }
        )

    # --- taking a schedule ------------------------------------------------

    async def async_set_schedule(self, schedule: dict[str, Any]) -> list[str]:
        """Store a schedule and run from it. Return what changed in the Jewish Calendar."""
        check_schedule(schedule)
        changes = await self._async_apply_calendar_settings(schedule["settings"])
        self.schedule = schedule
        if self.last_run is None:
            # From now on, anything not run counts as missed.
            self.last_run = dt_util.now()
        await self._async_save()
        await self.async_rebuild(recover=False)
        return changes

    async def _async_apply_calendar_settings(self, settings: dict[str, Any]) -> list[str]:
        """Keep the Jewish Calendar integration in step with the schedule."""
        entries = self.hass.config_entries.async_entries(JEWISH_CALENDAR)
        if not entries:
            raise HomeAssistantError(
                "The Jewish Calendar integration is not set up in this Home Assistant"
            )
        entry = entries[0]
        data, options, changes = wanted_settings(settings, entry.data, entry.options)
        if data != dict(entry.data) or options != dict(entry.options):
            self.hass.config_entries.async_update_entry(entry, data=data, options=options)
            await self.hass.config_entries.async_reload(entry.entry_id)
            _LOGGER.info("Jewish Calendar settings changed: %s", "; ".join(changes))
        return changes

    # --- fixing the day's list --------------------------------------------

    async def async_rebuild(self, *, recover: bool) -> None:
        """Fix the lists for yesterday and today and set their timers.

        Yesterday's list is included because a Night may run after midnight.
        With ``recover``, automations missed since the engine last ran are
        caught up.
        """
        self._cancel_timers()
        self.day_lists, self.upcoming = [], []
        if self.schedule is None:
            return

        now = dt_util.now()
        tz = ZoneInfo(self.hass.config.time_zone)
        today = now.astimezone(tz).date()
        yesterday = today - timedelta(days=1)

        try:
            calendar = await async_read_calendar(
                self.hass,
                yesterday - timedelta(days=LOOK_BACK_DAYS),
                today + timedelta(days=LOOK_AHEAD_DAYS),
            )
        except (CalendarDataError, HomeAssistantError) as err:
            self._report(f"The Jewish Calendar could not be read, so nothing is scheduled: {err}")
            return

        for day in (yesterday, today):
            try:
                self.day_lists.append(build_day_list(self.schedule, day, calendar, tz))
            except ENGINE_ERRORS as err:
                self._report(f"The list for {day} could not be fixed: {err}")

        missed, self.upcoming = split_due(self.day_lists, self.last_run, now)
        for automation in self.upcoming:
            self._timers.append(
                async_track_point_in_time(
                    self.hass, self._timer_for(automation), automation.time
                )
            )

        rollover = dt_util.parse_time(
            self.schedule["settings"].get("day_rollover", "04:00")
        )
        if rollover is not None:
            self._rollover = async_track_time_change(
                self.hass,
                self._at_rollover,
                hour=rollover.hour,
                minute=rollover.minute,
                second=0,
            )

        if recover and missed:
            self.hass.async_create_task(self._async_catch_up(missed, now))

    @callback
    def _at_rollover(self, now: datetime) -> None:
        self.hass.async_create_task(self.async_rebuild(recover=False))

    def _timer_for(self, automation: ScheduledAutomation):
        async def fire(now: datetime) -> None:
            await self._async_carry_out(
                automation.rooms, automation.name, fade_seconds=automation.fade_seconds
            )
            if self.last_run is None or automation.time > self.last_run:
                self.last_run = automation.time
                await self._async_save()

        return fire

    async def _async_catch_up(
        self, missed: list[ScheduledAutomation], now: datetime
    ) -> None:
        """Bring the house to where it should be now, after a restart."""
        names = ", ".join(automation.name for automation in missed)
        _LOGGER.info("Catching up after a restart; missed: %s", names)
        try:
            rooms = latest_state([automation.rooms for automation in missed])
        except ScheduleError as err:
            self._report(f"Could not catch up after a restart: {err}")
            return
        await self._async_carry_out(rooms, "Catching up after a restart", merged=True)
        self.last_run = now
        await self._async_save()

    # --- carrying an automation out ---------------------------------------

    async def _async_carry_out(
        self,
        rooms: dict[str, Any],
        name: str,
        *,
        fade_seconds: float = 0,
        merged: bool = False,
    ) -> None:
        pacing = (self.schedule or {}).get("settings", {}).get("pacing", {})
        group_size = pacing.get("group_size", 5)
        pause_seconds = pacing.get("pause_seconds", 1)
        try:
            steps = plan_steps(
                rooms,
                fade_seconds=fade_seconds,
                group_size=group_size,
                pause_seconds=pause_seconds,
                merged=merged,
            )
        except ScheduleError as err:
            self._report(f"{name} could not run: {err}")
            return

        async with self._running:
            _LOGGER.info("Running %s", name)
            failures = await carry_out(
                steps,
                self._async_send,
                self._get_state,
                asyncio.sleep,
                group_size=group_size,
                pause_seconds=pause_seconds,
            )

        if failures:
            lines = "\n".join(
                f"- {failure.call.entity_id}: {failure.reason}" for failure in failures
            )
            self._report(f"{name}: {len(failures)} still failing after three tries.\n{lines}")

    async def _async_send(self, call: Call) -> None:
        await self.hass.services.async_call(
            call.domain,
            call.service,
            {"entity_id": call.entity_id, **call.data},
            blocking=True,
        )

    def _get_state(self, entity_id: str):
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return state.state, state.attributes

    # --- reporting and stopping -------------------------------------------

    def _report(self, message: str) -> None:
        """Report a problem in the log and as a notification in Home Assistant."""
        _LOGGER.warning(message)
        persistent_notification.async_create(
            self.hass,
            message,
            title=TITLE,
            notification_id=f"{DOMAIN}_{dt_util.utcnow().timestamp():.0f}",
        )

    def _cancel_timers(self) -> None:
        for cancel in self._timers:
            cancel()
        self._timers = []
        if self._rollover is not None:
            self._rollover()
            self._rollover = None

    @callback
    def async_stop(self) -> None:
        self._cancel_timers()
