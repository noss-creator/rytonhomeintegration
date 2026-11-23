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

SERVICE_PREVIEW = "preview"

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ryton Home Automations."""

    async def handle_preview(call: ServiceCall) -> ServiceResponse:
        """Work out the day and the times of a span of dates. Switches nothing."""
        first = call.data.get("start_date") or dt_util.now().date()
        days = call.data["days"]
        last = first + timedelta(days=days - 1)

        schedule_path = _config_file(hass, call.data["schedule_file"])
        try:
            schedule = await hass.async_add_executor_job(_read_json, schedule_path)
        except FileNotFoundError as err:
            raise HomeAssistantError(f"No schedule file at {schedule_path}") from err
        except ValueError as err:
            raise HomeAssistantError(f"{schedule_path} is not valid JSON: {err}") from err

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

    hass.services.async_register(
        DOMAIN,
        SERVICE_PREVIEW,
        handle_preview,
        schema=PREVIEW_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Ryton Home Automations."""
    hass.services.async_remove(DOMAIN, SERVICE_PREVIEW)
    return True
