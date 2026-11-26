"""Ryton Home Automations."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_started
from homeassistant.loader import async_get_integration
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .calendar_reader import async_read_calendar
from .const import DEFAULT_SCHEDULE_FILE, DOMAIN
from .engine.calendar_snapshot import CalendarDataError
from .engine.preview import (
    LOOK_AHEAD_DAYS,
    LOOK_BACK_DAYS,
    build_preview,
    format_preview,
)
from .engine.changes import ChangeError, dates_between
from .engine.day_list import build_day_list, resolve_schedule_day
from .engine.run_through import automations_of_dates, every_automation
from .engine.sync_logic import on_off_rooms
from .engine.time_resolver import ScheduleError
from .scheduler import ENGINE_ERRORS, Scheduler
from .sync import Syncer
from .view import async_remove_view, async_setup_view

PLATFORMS = [Platform.CALENDAR, Platform.SCENE, Platform.SENSOR]

SERVICE_PREVIEW = "preview"
SERVICE_RELOAD_SCHEDULE = "reload_schedule"
SERVICE_RUN_THROUGH = "run_through"
SERVICE_STOP_RUN_THROUGH = "stop_run_through"
SERVICE_SYNC_NOW = "sync_now"
SERVICE_ADD_CHANGE = "add_change"
SERVICE_REMOVE_CHANGE = "remove_change"
SERVICE_LIST_CHANGES = "list_changes"
SERVICE_SET_ROOM_SCHEDULING = "set_room_scheduling"
SERVICE_DAYS_IN_DATES = "days_in_dates"
SERVICE_START_AWAY = "start_away"
SERVICE_SET_ROOM_NIGHT = "set_room_night"
SERVICE_END_AWAY = "end_away"

ADD_CHANGE_SCHEMA = vol.Schema({vol.Required("change"): dict})
REMOVE_CHANGE_SCHEMA = vol.Schema({vol.Required("id"): cv.string})
ROOM_SCHEDULING_SCHEMA = vol.Schema(
    {vol.Required("room"): cv.string, vol.Required("scheduling"): vol.In(["on", "off"])}
)
ROOM_NIGHT_SCHEMA = vol.Schema(
    {
        vol.Required("room"): cv.string,
        # A child's Night is earlier than the house's, an adult's later.
        vol.Optional("mode"): vol.In(("child", "adult")),
        # Minutes from the house's Night, or a clock time. Neither turns it off.
        vol.Exclusive("minutes", "how"): vol.All(vol.Coerce(int), vol.Range(min=1, max=720)),
        vol.Exclusive("at", "how"): cv.string,
    }
)
START_AWAY_SCHEMA = vol.Schema(
    {
        vol.Required("run"): cv.string,
        vol.Optional("rooms", default=list): [cv.string],
        vol.Required("until"): vol.Any("motzei", cv.date),
    }
)
DAYS_IN_DATES_SCHEMA = vol.Schema(
    {vol.Required("from"): cv.date, vol.Required("until"): cv.date}
)
# The longest span of dates a temporary change's days are listed for.
MAX_CHANGE_DAYS = 366

PREVIEW_SCHEMA = vol.Schema(
    {
        vol.Optional("start_date"): cv.date,
        vol.Optional("days", default=7): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=800)
        ),
        vol.Optional("schedule_file", default=DEFAULT_SCHEDULE_FILE): cv.string,
        vol.Optional("output_file"): cv.string,
    }
)

RELOAD_SCHEMA = vol.Schema(
    {vol.Optional("schedule_file", default=DEFAULT_SCHEDULE_FILE): cv.string}
)

RUN_THROUGH_SCHEMA = vol.Schema(
    {
        vol.Optional("start_date"): cv.date,
        vol.Optional("days", default=7): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=400)
        ),
        vol.Optional("each_day_once", default=True): cv.boolean,
        vol.Optional("check_wait_seconds", default=10): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=60)
        ),
        vol.Optional("output_file", default="ryton_run_through.txt"): cv.string,
    }
)


def _config_file(hass: HomeAssistant, name: str) -> Path:
    """Return a path inside Home Assistant's configuration folder."""
    folder = Path(hass.config.config_dir).resolve()
    path = (folder / name).resolve()
    if not path.is_relative_to(folder):
        raise ServiceValidationError(f"{name} is outside the configuration folder")
    return path


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


async def _async_read_schedule_file(hass: HomeAssistant, name: str) -> Any:
    path = _config_file(hass, name)
    try:
        return await hass.async_add_executor_job(_read_json, path)
    except FileNotFoundError as err:
        raise HomeAssistantError(f"No schedule file at {path}") from err
    except ValueError as err:
        raise HomeAssistantError(f"{path} is not valid JSON: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ryton Home Automations."""
    scheduler = Scheduler(hass)
    await scheduler.async_load()
    syncer = Syncer(hass, entry, scheduler)
    await syncer.async_load()
    scheduler.house_rooms = lambda: on_off_rooms(syncer.inventory())
    # The schedule's own scenes are offered from the stored schedule.
    entry.runtime_data = scheduler
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    integration = await async_get_integration(hass, DOMAIN)
    await async_setup_view(hass, scheduler, syncer, str(integration.version))

    async def handle_preview(call: ServiceCall) -> ServiceResponse:
        """Work out the day and the times of a span of dates. Switches nothing."""
        first = call.data.get("start_date") or dt_util.now().date()
        days = call.data["days"]
        last = first + timedelta(days=days - 1)

        schedule = await _async_read_schedule_file(hass, call.data["schedule_file"])

        try:
            calendar = await async_read_calendar(
                hass,
                first - timedelta(days=LOOK_BACK_DAYS),
                last + timedelta(days=LOOK_AHEAD_DAYS),
            )
        except CalendarDataError as err:
            raise HomeAssistantError(str(err)) from err

        tz = ZoneInfo(hass.config.time_zone)
        rows = await hass.async_add_executor_job(
            build_preview, schedule, calendar, tz, first, days
        )

        output_file = call.data.get("output_file")
        if not output_file:
            return {"rows": rows}

        # With a file the list goes there, and the answer is only a summary.
        output_path = _config_file(hass, output_file)
        await hass.async_add_executor_job(_write_text, output_path, format_preview(rows))
        errors = [row for row in rows if "error" in row]
        return {
            "written_to": str(output_path),
            "dates": len(rows),
            "errors": len(errors),
            "first_errors": [
                {"date": row["date"], "error": row["error"]} for row in errors[:20]
            ],
        }

    async def handle_reload_schedule(call: ServiceCall) -> ServiceResponse:
        """Take the schedule from its file and run the house from it."""
        schedule = await _async_read_schedule_file(hass, call.data["schedule_file"])
        if not isinstance(schedule, dict):
            raise HomeAssistantError("The schedule file does not hold a schedule")
        try:
            changes = await scheduler.async_set_schedule(schedule)
        except ScheduleError as err:
            raise HomeAssistantError(f"The schedule was refused: {err}") from err

        tz = ZoneInfo(hass.config.time_zone)
        return {
            "revision": schedule.get("revision"),
            "jewish_calendar_changes": changes,
            "days": [
                {"date": day_list.date.isoformat(), "day": day_list.day.day_id}
                for day_list in scheduler.day_lists
            ],
            "upcoming": [
                {
                    "id": automation.id,
                    "time": automation.time.astimezone(tz).isoformat(timespec="seconds"),
                    "alongside": automation.alongside,
                }
                for automation in scheduler.upcoming
            ],
        }

    async def handle_run_through(call: ServiceCall) -> ServiceResponse:
        """Carry out automations back to back. This really switches devices."""
        schedule = scheduler.schedule
        if schedule is None:
            raise HomeAssistantError("There is no schedule yet. Reload the schedule first.")

        first = call.data.get("start_date")
        if first is None:
            items = every_automation(schedule)
        else:
            days = call.data["days"]
            tz = ZoneInfo(hass.config.time_zone)
            try:
                calendar = await async_read_calendar(
                    hass,
                    first - timedelta(days=LOOK_BACK_DAYS),
                    first + timedelta(days=days - 1 + LOOK_AHEAD_DAYS),
                )
                day_lists = [
                    build_day_list(schedule, first + timedelta(days=n), calendar, tz)
                    for n in range(days)
                ]
            except ENGINE_ERRORS as err:
                raise HomeAssistantError(str(err)) from err
            items = automations_of_dates(
                day_lists, each_day_once=call.data["each_day_once"]
            )

        output_path = _config_file(hass, call.data["output_file"])

        async def write_report(text: str) -> None:
            await hass.async_add_executor_job(_write_text, output_path, text)

        check_wait = call.data["check_wait_seconds"]
        scheduler.async_start_run_through(items, check_wait, write_report)
        # About one pause per group, three for a typical automation, plus the check.
        estimate = len(items) * (check_wait + 3)
        return {
            "started": True,
            "automations": len(items),
            "about_minutes": round(estimate / 60, 1),
            "report_file": str(output_path),
        }

    async def handle_stop_run_through(call: ServiceCall) -> ServiceResponse:
        return {"stopped": scheduler.async_stop_run_through()}

    async def handle_sync_now(call: ServiceCall) -> ServiceResponse:
        """Check the website for a newer schedule now."""
        result = await syncer.async_sync()
        schedule = scheduler.schedule or {}
        return {
            "paired": syncer.paired,
            "house_id": syncer.house_id,
            "result": result,
            "revision": schedule.get("revision"),
        }

    async def handle_add_change(call: ServiceCall) -> ServiceResponse:
        """Store one of the client's temporary changes. It applies from now."""
        try:
            made = await scheduler.async_add_change(call.data["change"])
        except ChangeError as err:
            raise ServiceValidationError(f"The change was refused: {err}") from err
        return {"change": made}

    async def handle_remove_change(call: ServiceCall) -> ServiceResponse:
        return {"removed": await scheduler.async_remove_change(call.data["id"])}

    async def handle_list_changes(call: ServiceCall) -> ServiceResponse:
        return {"rooms_off": list(scheduler.rooms_off), "changes": list(scheduler.changes)}

    async def handle_set_room_scheduling(call: ServiceCall) -> ServiceResponse:
        """Set a room's own scheduling switch. It stays until it is set again."""
        await scheduler.async_set_room_scheduling(
            call.data["room"], call.data["scheduling"] == "on"
        )
        return {"rooms_off": list(scheduler.rooms_off)}

    async def handle_set_room_night(call: ServiceCall) -> ServiceResponse:
        """Give a room its own Night, or take it away. It stays until it is set again."""
        how = {key: call.data[key] for key in ("minutes", "at") if key in call.data}
        if how:
            how["mode"] = call.data.get("mode", "child")
        try:
            await scheduler.async_set_room_night(call.data["room"], how or None)
        except ScheduleError as err:
            raise ServiceValidationError(f"The room's own Night was not set: {err}") from err
        return {"room_night": dict(scheduler.room_night)}

    async def handle_start_away(call: ServiceCall) -> ServiceResponse:
        """Turn away mode on from now, until motzei Shabbos or Yom Tov or the end of a date."""
        until = call.data["until"]
        end = {"kind": "motzei"} if until == "motzei" else {"kind": "date", "date": until}
        try:
            made = await scheduler.async_start_away(call.data["run"], call.data["rooms"], end)
        except ChangeError as err:
            raise ServiceValidationError(f"Away mode was not turned on: {err}") from err
        except ENGINE_ERRORS as err:
            raise HomeAssistantError(f"Away mode was not turned on: {err}") from err
        return {"change": made}

    async def handle_end_away(call: ServiceCall) -> ServiceResponse:
        """End the client's away mode now."""
        return {"ended": await scheduler.async_end_away()}

    async def handle_days_in_dates(call: ServiceCall) -> ServiceResponse:
        """Say which of the schedule's days occur in a span of dates.

        This is what the client chooses from when a change is to touch only
        some kinds of day. The engine works it out; nothing else does.
        """
        schedule = scheduler.schedule
        if schedule is None:
            raise HomeAssistantError("There is no schedule yet")
        first, last = call.data["from"], call.data["until"]
        if last < first or (last - first).days >= MAX_CHANGE_DAYS:
            raise ServiceValidationError("The dates must be in order and within a year")
        try:
            calendar = await async_read_calendar(
                hass,
                first - timedelta(days=LOOK_BACK_DAYS),
                last + timedelta(days=LOOK_AHEAD_DAYS),
            )
            found: dict[str, list[str]] = {}
            for day in dates_between(first, last):
                day_id = resolve_schedule_day(schedule, day, calendar).day_id
                found.setdefault(day_id, []).append(day.isoformat())
        except ENGINE_ERRORS as err:
            raise HomeAssistantError(str(err)) from err
        return {
            "days": [{"day": day_id, "dates": dates} for day_id, dates in found.items()]
        }

    for name, handler, schema, response in (
        (SERVICE_ADD_CHANGE, handle_add_change, ADD_CHANGE_SCHEMA, SupportsResponse.OPTIONAL),
        (SERVICE_REMOVE_CHANGE, handle_remove_change, REMOVE_CHANGE_SCHEMA, SupportsResponse.OPTIONAL),
        (SERVICE_LIST_CHANGES, handle_list_changes, None, SupportsResponse.ONLY),
        (
            SERVICE_SET_ROOM_SCHEDULING,
            handle_set_room_scheduling,
            ROOM_SCHEDULING_SCHEMA,
            SupportsResponse.OPTIONAL,
        ),
        (SERVICE_DAYS_IN_DATES, handle_days_in_dates, DAYS_IN_DATES_SCHEMA, SupportsResponse.ONLY),
        (SERVICE_START_AWAY, handle_start_away, START_AWAY_SCHEMA, SupportsResponse.OPTIONAL),
        (SERVICE_SET_ROOM_NIGHT, handle_set_room_night, ROOM_NIGHT_SCHEMA, SupportsResponse.OPTIONAL),
        (SERVICE_END_AWAY, handle_end_away, None, SupportsResponse.OPTIONAL),
    ):
        hass.services.async_register(
            DOMAIN, name, handler, schema=schema, supports_response=response
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_NOW,
        handle_sync_now,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_THROUGH,
        handle_run_through,
        schema=RUN_THROUGH_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_RUN_THROUGH,
        handle_stop_run_through,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PREVIEW,
        handle_preview,
        schema=PREVIEW_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RELOAD_SCHEDULE,
        handle_reload_schedule,
        schema=RELOAD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def started(hass: HomeAssistant) -> None:
        """Once Home Assistant is up, fix today's list and catch up on anything missed."""
        await scheduler.async_rebuild(recover=True)
        syncer.async_start()

    entry.async_on_unload(async_at_started(hass, started))
    entry.async_on_unload(scheduler.async_stop)
    entry.async_on_unload(syncer.async_stop)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Removing the integration from a house removes everything it stored there.

    Otherwise the schedule it last ran would come back, and run, the next
    time the integration is added.
    """
    for name in ("state", "sync", "changes"):
        await Store(hass, 1, f"{DOMAIN}.{name}").async_remove()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Ryton Home Automations."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    async_remove_view(hass)
    hass.services.async_remove(DOMAIN, SERVICE_PREVIEW)
    hass.services.async_remove(DOMAIN, SERVICE_RELOAD_SCHEDULE)
    hass.services.async_remove(DOMAIN, SERVICE_RUN_THROUGH)
    hass.services.async_remove(DOMAIN, SERVICE_STOP_RUN_THROUGH)
    hass.services.async_remove(DOMAIN, SERVICE_SYNC_NOW)
    for name in (
        SERVICE_ADD_CHANGE,
        SERVICE_REMOVE_CHANGE,
        SERVICE_LIST_CHANGES,
        SERVICE_SET_ROOM_SCHEDULING,
        SERVICE_DAYS_IN_DATES,
        SERVICE_START_AWAY,
        SERVICE_END_AWAY,
        SERVICE_SET_ROOM_NIGHT,
    ):
        hass.services.async_remove(DOMAIN, name)
    return True
