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
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Collection, Mapping
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
from .engine.changes import FORMAT_VERSION as CHANGES_FORMAT_VERSION
from .engine.changes import check_change, still_wanted
from .engine.day_list import (
    DayList,
    ScheduledAutomation,
    build_day_list,
    check_schedule,
)
from .engine.day_resolver import UnresolvedDayError
from .engine.due import split_due
from .engine.preview import LOOK_AHEAD_DAYS, LOOK_BACK_DAYS
from .engine.run_through import RunThroughItem
from .engine.runner import CHECK_WAIT_SECONDS, carry_out
from .engine.scenes import expand_scenes, schedule_scenes
from .engine.time_resolver import (
    PastRolloverError,
    ScheduleError,
    ZmanUnavailableError,
)

_LOGGER = logging.getLogger(__name__)


async def _sleep(seconds: float) -> None:
    """Wait. Kept as one function so tests can make the waits instant."""
    await asyncio.sleep(seconds)

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
        self._run_through: asyncio.Task[None] | None = None
        self.problems: deque[dict[str, str]] = deque(maxlen=50)
        self._listeners: list[Callable[[], Awaitable[None]]] = []
        # The client's temporary changes and room switches. They are kept
        # apart from the schedule and never leave the house.
        self.changes: list[dict[str, Any]] = []
        self.rooms_off: list[str] = []
        self._changes_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.changes"
        )
        # The automations of yesterday's and today's lists that have run,
        # each as "date|identifier", so a change to a time never makes one
        # run twice.
        self._ran: set[str] = set()
        # For each automation of the fixed lists: its key, and the rooms
        # skipped on its date.
        self._of: dict[int, tuple[str, frozenset[str]]] = {}

    def async_listen(self, listener: Callable[[], Awaitable[None]]) -> CALLBACK_TYPE:
        """Call ``listener`` each time the house takes a schedule."""
        self._listeners.append(listener)

        def stop() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return stop

    # --- storage ----------------------------------------------------------

    async def async_load(self) -> None:
        """Read the stored schedule, if there is one."""
        stored = await self._store.async_load() or {}
        self.schedule = stored.get("schedule")
        last_run = stored.get("last_run")
        self.last_run = dt_util.parse_datetime(last_run) if last_run else None
        self._ran = {key for key in stored.get("ran") or () if isinstance(key, str)}

        kept = await self._changes_store.async_load() or {}
        changes = kept.get("changes")
        rooms_off = kept.get("rooms_off")
        self.changes = [c for c in changes if isinstance(c, dict)] if isinstance(changes, list) else []
        self.rooms_off = (
            [room for room in rooms_off if isinstance(room, str)]
            if isinstance(rooms_off, list)
            else []
        )

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "schedule": self.schedule,
                "last_run": self.last_run.isoformat() if self.last_run else None,
                "ran": sorted(self._ran),
            }
        )

    async def _async_save_changes(self) -> None:
        await self._changes_store.async_save(
            {
                "format_version": CHANGES_FORMAT_VERSION,
                "rooms_off": self.rooms_off,
                "changes": self.changes,
            }
        )

    # --- the client's temporary changes -----------------------------------

    async def async_add_change(self, change: Mapping[str, Any]) -> dict[str, Any]:
        """Store a temporary change and apply it from now. Return it as stored.

        Raises ``ChangeError`` where the change is not understood.
        """
        made = {
            **change,
            "id": uuid.uuid4().hex[:8],
            "made_at": dt_util.now().isoformat(timespec="seconds"),
        }
        check_change(made)
        self.changes.append(made)
        await self._async_save_changes()
        await self._async_changes_made()
        return made

    async def async_remove_change(self, change_id: str) -> bool:
        """Remove a temporary change. Return whether there was one."""
        kept = [change for change in self.changes if change.get("id") != change_id]
        if len(kept) == len(self.changes):
            return False
        self.changes = kept
        await self._async_save_changes()
        await self._async_changes_made()
        return True

    async def async_set_room_scheduling(self, room: str, on: bool) -> None:
        """Set a room's own scheduling switch, which has no end date."""
        rooms = [other for other in self.rooms_off if other != room]
        if not on:
            rooms.append(room)
        self.rooms_off = rooms
        await self._async_save_changes()
        await self._async_changes_made()

    async def _async_changes_made(self) -> None:
        """Fix the lists again, so the automations still to run follow the changes.

        An automation that has already run does not run again, whatever its
        time becomes. One that has not run, and whose time is now past, runs
        at once.
        """
        if self.last_run is not None:
            for day_list in self.day_lists:
                for automation in day_list.automations:
                    if automation.time <= self.last_run:
                        self._ran.add(f"{day_list.date.isoformat()}|{automation.id}")
        await self.async_rebuild(recover=True)

    # --- taking a schedule ------------------------------------------------

    async def async_set_schedule(self, schedule: dict[str, Any]) -> list[str]:
        """Store a schedule and run from it. Return what changed in the Jewish Calendar."""
        check_schedule(schedule)
        changes = await self._async_apply_calendar_settings(schedule["settings"])
        self.schedule = schedule
        # A new schedule starts from now: nothing timed earlier is replayed,
        # and anything timed later that does not run counts as missed.
        self.last_run = dt_util.now()
        self._ran = set()
        await self._async_save()
        for listener in list(self._listeners):
            await listener()
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
        With ``recover``, automations that came due since the engine last ran
        and did not run are caught up. That is used at startup and at the
        rollover. It is not used when a new schedule is loaded.
        """
        self._cancel_timers()
        self.day_lists, self.upcoming = [], []
        self._of = {}
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
            self.report(f"The Jewish Calendar could not be read, so nothing is scheduled: {err}")
            return

        # A change is dropped the day after its last date. Yesterday's list
        # is still being fixed, so a change that ended yesterday is kept
        # one more day.
        wanted = still_wanted(self.changes, yesterday)
        if len(wanted) != len(self.changes):
            self.changes = wanted
            await self._async_save_changes()

        for day in (yesterday, today):
            try:
                day_list = build_day_list(
                    self.schedule,
                    day,
                    calendar,
                    tz,
                    changes=self.changes,
                    rooms_off=self.rooms_off,
                )
            except ENGINE_ERRORS as err:
                self.report(f"The list for {day} could not be fixed: {err}")
                continue
            self.day_lists.append(day_list)
            for automation in day_list.automations:
                self._of[id(automation)] = (
                    f"{day.isoformat()}|{automation.id}",
                    day_list.rooms_off,
                )
            for change_id, reason in day_list.skipped_changes:
                _LOGGER.info(
                    "Temporary change %s is not applied on %s: %s", change_id, day, reason
                )

        days = {yesterday.isoformat(), today.isoformat()}
        self._ran = {key for key in self._ran if key.split("|", 1)[0] in days}

        # Reading the calendar took a moment, and the timers were off
        # meanwhile. Anything that came due in that moment, or just before
        # the rebuild began, is in ``missed`` and must not be lost.
        now = dt_util.now()
        missed, self.upcoming = split_due(self.day_lists, self.last_run, now)
        missed = [a for a in missed if self._of[id(a)][0] not in self._ran]
        self.upcoming = [a for a in self.upcoming if self._of[id(a)][0] not in self._ran]
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
        # With catch-up, so an automation due at the moment of the rollover
        # still runs.
        self.hass.async_create_task(self.async_rebuild(recover=True))

    def _timer_for(self, automation: ScheduledAutomation):
        key, rooms_off = self._of.get(id(automation), ("", frozenset()))

        async def fire(now: datetime) -> None:
            await self._async_carry_out(
                automation.rooms,
                automation.name,
                fade_seconds=automation.fade_seconds,
                rooms_off=rooms_off,
            )
            if key:
                self._ran.add(key)
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
            self.report(f"Could not catch up after a restart: {err}")
            return
        # The rooms skipped are today's.
        rooms_off = self.day_lists[-1].rooms_off if self.day_lists else frozenset()
        await self._async_carry_out(
            rooms, "Catching up", merged=True, rooms_off=rooms_off
        )
        self._ran.update(
            self._of[id(automation)][0] for automation in missed if id(automation) in self._of
        )
        self.last_run = now
        await self._async_save()

    # --- carrying an automation out ---------------------------------------

    async def _async_carry_out(
        self,
        rooms: Mapping[str, Any],
        name: str,
        *,
        fade_seconds: float = 0,
        merged: bool = False,
        rooms_off: Collection[str] = (),
        check_wait: float = CHECK_WAIT_SECONDS,
        report: bool = True,
    ) -> list[str]:
        """Carry out one automation. Return a line for each entity still failing."""
        pacing = (self.schedule or {}).get("settings", {}).get("pacing", {})
        group_size = pacing.get("group_size", 5)
        pause_seconds = pacing.get("pause_seconds", 1)
        try:
            # A room that uses one of the schedule's own scenes gets that
            # scene's entities, so each is paced, checked and retried.
            rooms = expand_scenes(
                rooms, schedule_scenes(self.schedule), fade=not merged
            )
            # Where the client changed a room that uses a scene made in Home
            # Assistant, the room holds the scene and entities together.
            together = any(
                isinstance(body, Mapping) and "scene" in body and "entities" in body
                for body in rooms.values()
            )
            steps = plan_steps(
                rooms,
                fade_seconds=fade_seconds,
                group_size=group_size,
                pause_seconds=pause_seconds,
                rooms_off=rooms_off,
                merged=merged or together,
            )
        except ScheduleError as err:
            if report:
                self.report(f"{name} could not run: {err}")
            return [f"could not run: {err}"]

        async with self._running:
            _LOGGER.info("Running %s", name)
            failures = await carry_out(
                steps,
                self._async_send,
                self._get_state,
                _sleep,
                group_size=group_size,
                pause_seconds=pause_seconds,
                check_wait=check_wait,
            )

        lines = [f"{failure.call.entity_id}: {failure.reason}" for failure in failures]
        if lines and report:
            listed = "\n".join(f"- {line}" for line in lines)
            self.report(f"{name}: {len(lines)} still failing after three tries.\n{listed}")
        return lines

    async def async_run_scene(
        self, scene_id: str, fade_seconds: float | None = None
    ) -> None:
        """Set one of the schedule's own scenes, as when it is turned on by hand.

        It fades as saved with the scene, unless a fade is given.
        """
        try:
            scene = schedule_scenes(self.schedule).get(scene_id)
        except ScheduleError:
            scene = None
        if scene is None:
            self.report(f"The scene {scene_id} is not in the schedule")
            return
        await self._async_carry_out(
            {
                scene["room"]: {
                    "entities": scene["entities"],
                    "fade_seconds": scene["fade_seconds"]
                    if fade_seconds is None
                    else fade_seconds,
                }
            },
            f"The scene {scene['name']}",
        )

    # --- running through automations back to back ---------------------------

    @property
    def run_through_running(self) -> bool:
        return self._run_through is not None and not self._run_through.done()

    @callback
    def async_start_run_through(
        self,
        items: list[RunThroughItem],
        check_wait: float,
        write_report: Callable[[str], Awaitable[None]],
    ) -> None:
        """Carry out ``items`` one after another in the background."""
        if self.run_through_running:
            raise HomeAssistantError("A run-through is already running")
        self._run_through = self.hass.async_create_background_task(
            self._async_run_through(items, check_wait, write_report),
            name=f"{DOMAIN} run-through",
        )

    @callback
    def async_stop_run_through(self) -> bool:
        """Stop a run-through. Return whether one was running."""
        if not self.run_through_running:
            return False
        self._run_through.cancel()
        return True

    async def _async_run_through(
        self,
        items: list[RunThroughItem],
        check_wait: float,
        write_report: Callable[[str], Awaitable[None]],
    ) -> None:
        lines: list[str] = []
        failed = done = 0
        stopped = False
        try:
            for item in items:
                failures = await self._async_carry_out(
                    item.rooms,
                    f"{item.label}: {item.name}",
                    fade_seconds=item.fade_seconds,
                    check_wait=check_wait,
                    report=False,
                )
                done += 1
                failed += len(failures)
                result = "ok" if not failures else f"{len(failures)} FAILED"
                lines.append(f"{item.label:<40} {item.automation_id:<28} {result}")
                lines += [f"    {failure}" for failure in failures]
        except asyncio.CancelledError:
            stopped = True
        summary = (
            f"Run-through {'stopped' if stopped else 'finished'}: {done} of "
            f"{len(items)} automations run, {failed} entities failed."
        )
        await write_report("\n".join([summary, "", *lines]) + "\n")
        self.report(summary)

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

    def report(self, message: str) -> None:
        """Report a problem in the log and as a notification in Home Assistant.

        The latest problems are also kept, to be sent to the website.
        """
        _LOGGER.warning(message)
        self.problems.append({"at": dt_util.now().isoformat(timespec="seconds"), "message": message})
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
        self.async_stop_run_through()
