"""Ryton Home Automations."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_started
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
from .engine.day_list import build_day_list
from .engine.run_through import automations_of_dates, every_automation
from .engine.time_resolver import ScheduleError
from .scheduler import ENGINE_ERRORS, Scheduler
from .sync import Syncer

SERVICE_PREVIEW = "preview"
SERVICE_RELOAD_SCHEDULE = "reload_schedule"
SERVICE_RUN_THROUGH = "run_through"
SERVICE_STOP_RUN_THROUGH = "stop_run_through"
SERVICE_SYNC_NOW = "sync_now"

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
    for name in ("state", "sync"):
        await Store(hass, 1, f"{DOMAIN}.{name}").async_remove()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Ryton Home Automations."""
    hass.services.async_remove(DOMAIN, SERVICE_PREVIEW)
    hass.services.async_remove(DOMAIN, SERVICE_RELOAD_SCHEDULE)
    hass.services.async_remove(DOMAIN, SERVICE_RUN_THROUGH)
    hass.services.async_remove(DOMAIN, SERVICE_STOP_RUN_THROUGH)
    hass.services.async_remove(DOMAIN, SERVICE_SYNC_NOW)
    return True
