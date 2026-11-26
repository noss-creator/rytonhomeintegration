"""The client's view: its page in the sidebar, and what that page reads.

The page is for short-term changes only. It reads the upcoming schedule from
the engine, and makes its changes through the integration's own actions. It
never changes the schedule, and it needs no internet.

A second sidebar entry, for administrators only, opens the setup form on the
website.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.util import dt as dt_util

from .calendar_reader import async_read_calendar
from .const import DOMAIN, FORM_URL
from .engine.away import (
    OFF,
    ROOMS,
    away_changes,
    meals_on,
    mode_at,
    motzei_end,
    schedule_date,
    schedule_presets,
)
from .engine.changes import AWAY, MEAL_OUT
from .engine.preview import LOOK_AHEAD_DAYS, LOOK_BACK_DAYS
from .engine.describe import automation_title, day_name, describe_by_entity, describe_by_room
from .engine.scenes import schedule_scenes
from .engine.time_resolver import ScheduleError

_LOGGER = logging.getLogger(__name__)

STATIC_URL = f"/{DOMAIN}_static"
VIEW_PATH = "ryton-home-automations"
FORM_PATH = "ryton-setup-form"
DATA_VIEW = f"{DOMAIN}_view"


# How many days of meals the client can be away for.
MEAL_DAYS = 8


def _ended(change: Any, now: Any) -> bool:
    """Whether an away choice is over. It is kept a while, but no longer shown."""
    if not isinstance(change, dict) or change.get("kind") != AWAY:
        return False
    try:
        return dt_util.parse_datetime(change["ends_at"]) <= now
    except (KeyError, TypeError, ValueError):
        return True


async def _async_away_and_meals(hass: HomeAssistant, scheduler: Any, now: Any, tz: Any) -> dict[str, Any]:
    """Away mode as it stands now, what the client can choose, and the coming meals."""
    schedule = scheduler.schedule
    changes = list(scheduler.changes)
    today = schedule_date(now, schedule, tz)
    try:
        presets = schedule_presets(schedule)
    except ScheduleError:
        presets = {}
    try:
        calendar = await async_read_calendar(
            hass,
            today - timedelta(days=LOOK_BACK_DAYS),
            today + timedelta(days=LOOK_AHEAD_DAYS + MEAL_DAYS + 2),
        )
    except Exception:  # noqa: BLE001 - the view still shows the rest
        _LOGGER.debug("The calendar could not be read for the client's view", exc_info=True)
        calendar = None

    def work() -> dict[str, Any]:
        client = away_changes(schedule, changes)
        try:
            mode = mode_at(schedule, client, now, tz)
        except ScheduleError:
            mode = None
        current = next(
            (
                change
                for change in reversed(client)
                if dt_util.parse_datetime(change["starts_at"])
                <= now
                < dt_util.parse_datetime(change["ends_at"])
            ),
            None,
        )
        away = None
        if mode is not None:
            preset = presets.get(mode.run) or {}
            away = {
                "run": mode.run,
                "name": {OFF: "Everything off", ROOMS: "Only some rooms"}.get(
                    mode.run, preset.get("name") or mode.run
                ),
                "rooms": sorted(mode.rooms),
                # The client's own choice, or the dates set up for this house.
                "by": "client" if current else "dates",
                "id": current["id"] if current else None,
                "ends_at": current["ends_at"] if current else None,
            }
        meals, motzei = [], None
        if calendar is not None:
            out = {
                (change.get("from"), change.get("meal")): change.get("id")
                for change in changes
                if isinstance(change, dict) and change.get("kind") == MEAL_OUT
            }
            for n in range(MEAL_DAYS):
                day = today + timedelta(days=n)
                try:
                    found = meals_on(schedule, day, calendar)
                except Exception:  # noqa: BLE001 - one date must not hide the others
                    continue
                meals += [
                    {
                        "date": day.isoformat(),
                        "meal": meal,
                        "name": name,
                        "out": out.get((day.isoformat(), meal)),
                    }
                    for meal, name in found
                ]
            try:
                last, ends_at = motzei_end(schedule, today, calendar)
                motzei = {
                    "last": last.isoformat(),
                    "ends_at": ends_at.astimezone(tz).isoformat(timespec="minutes"),
                }
            except Exception:  # noqa: BLE001 - then only "until a date" is offered
                motzei = None
        return {
            "away": away,
            "presets": [
                {"id": preset_id, "name": preset.get("name") or preset_id}
                for preset_id, preset in presets.items()
            ],
            "motzei": motzei,
            "meals": meals,
        }

    return await hass.async_add_executor_job(work)


async def async_view_data(hass: HomeAssistant, days: int) -> dict[str, Any]:
    """Everything the client's view shows: the coming days, the rooms, the changes."""
    held = hass.data.get(DATA_VIEW) or {}
    scheduler, syncer = held.get("scheduler"), held.get("syncer")
    if scheduler is None or scheduler.schedule is None:
        return {"ready": False, "days": [], "rooms": [], "rooms_off": [], "changes": []}

    tz = ZoneInfo(hass.config.time_zone)
    now = dt_util.now()
    today = now.astimezone(tz).date()
    areas = ar.async_get(hass)

    def room_name(room: str) -> str:
        area = areas.async_get_area(room)
        return area.name if area else room

    def entity_name(entity_id: str) -> str:
        state = hass.states.get(entity_id)
        return state.name if state else entity_id

    try:
        scenes = schedule_scenes(scheduler.schedule)
    except ScheduleError:
        scenes = {}

    inventory = syncer.inventory() if syncer is not None else {}
    floors = [*inventory.get("floors", []), {"rooms": inventory.get("rooms_with_no_floor", [])}]
    # What each scene made in Home Assistant sets its entities to, in words.
    scene_sets = {
        entity["entity_id"]: entity["sets"]
        for floor in floors
        for room in floor.get("rooms", [])
        for entity in room["entities"]
        if entity.get("sets")
    }

    # Yesterday's list too: its Night may still be to come, after midnight.
    lists = await scheduler.async_day_lists(
        today - timedelta(days=1), today + timedelta(days=days - 1)
    )
    shown = []
    for day_list in lists:
        automations = [
            {
                "id": automation.id,
                "name": automation_title(automation.id, automation.name),
                "time": automation.time.astimezone(tz).isoformat(timespec="minutes"),
                "past": automation.time <= now,
                "alongside": automation.alongside,
                "rooms": [
                    {"room": room, "name": room_name(room), "text": words}
                    for room, words in describe_by_room(
                        automation.rooms, scenes, entity_name, day_list.rooms_off
                    )
                ],
                # The same, one entry for each entity it sets.
                "sets": describe_by_entity(
                    automation.rooms, scenes, scene_sets, day_list.rooms_off
                ),
            }
            for automation in day_list.automations
        ]
        if day_list.date < today:
            automations = [automation for automation in automations if not automation["past"]]
            if not automations:
                continue
        shown.append(
            {
                "date": day_list.date.isoformat(),
                "day": day_list.day.day_id,
                "day_name": day_name(day_list.day.day_id),
                "shabbos_start": day_list.shabbos_start.astimezone(tz).isoformat(timespec="minutes")
                if day_list.shabbos_start and day_list.date.weekday() == 4
                else None,
                "rooms_off": sorted(day_list.rooms_off),
                "automations": automations,
            }
        )

    rooms = [
        {"id": room["id"], "name": room["name"], "floor": floor.get("name"), "entities": room["entities"]}
        for floor in floors
        for room in floor.get("rooms", [])
    ]
    settings = scheduler.schedule.get("settings", {})
    # The automations of every day of the schedule, for choosing one to change.
    automations_by_day = {
        day_id: [
            {"id": a.get("id"), "name": automation_title(str(a.get("id")), a.get("name"))}
            for a in (entry.get("automations") or [])
            if isinstance(a, dict) and a.get("id")
        ]
        for day_id, entry in (scheduler.schedule.get("days") or {}).items()
        if isinstance(entry, dict)
    }
    alongside = [
        {"id": a.get("id"), "name": automation_title(str(a.get("id")), a.get("name"))}
        for a in (scheduler.schedule.get("alongside") or [])
        if isinstance(a, dict) and a.get("id")
    ]
    return {
        **await _async_away_and_meals(hass, scheduler, now, tz),
        "ready": True,
        "today": today.isoformat(),
        "now": now.astimezone(tz).isoformat(timespec="minutes"),
        "days": shown,
        "rooms": rooms,
        "rooms_off": list(scheduler.rooms_off),
        "changes": [change for change in scheduler.changes if not _ended(change, now)],
        "has_simcha_time": bool((settings.get("simcha") or {}).get("night_time")),
        "rollover": settings.get("day_rollover", "04:00"),
        "automations_by_day": automations_by_day,
        "alongside": alongside,
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/view",
        vol.Optional("days", default=7): vol.All(int, vol.Range(min=1, max=31)),
    }
)
@websocket_api.async_response
async def ws_view(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    connection.send_result(msg["id"], await async_view_data(hass, msg["days"]))


async def async_setup_view(hass: HomeAssistant, scheduler: Any, syncer: Any, version: str) -> None:
    """Offer the view's data, and add the two sidebar entries where the sidebar exists."""
    hass.data[DATA_VIEW] = {"scheduler": scheduler, "syncer": syncer}
    websocket_api.async_register_command(hass, ws_view)

    # A Home Assistant with no screens, as in the tests, has no sidebar.
    if "frontend" not in hass.config.components or hass.http is None:
        return
    try:
        from homeassistant.components import panel_custom
        from homeassistant.components.http import StaticPathConfig
    except ImportError:
        return

    if not hass.data.get(f"{DATA_VIEW}_static"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "frontend"), False)]
        )
        hass.data[f"{DATA_VIEW}_static"] = True

    module_url = f"{STATIC_URL}/client-view.js?v={version}"
    house_id = getattr(syncer, "house_id", None)
    try:
        await panel_custom.async_register_panel(
            hass,
            webcomponent_name="ryton-client-view",
            frontend_url_path=VIEW_PATH,
            sidebar_title="Ryton Home Automations",
            sidebar_icon="mdi:calendar-star",
            module_url=module_url,
            require_admin=False,
            config={},
        )
        await panel_custom.async_register_panel(
            hass,
            webcomponent_name="ryton-setup-form",
            frontend_url_path=FORM_PATH,
            sidebar_title="Ryton setup form",
            sidebar_icon="mdi:cog-outline",
            module_url=module_url,
            require_admin=True,
            config={"url": f"{FORM_URL}/houses/{house_id}" if house_id else FORM_URL},
        )
    except ValueError as err:
        _LOGGER.warning("The sidebar entries could not be added: %s", err)


@callback
def async_remove_view(hass: HomeAssistant) -> None:
    hass.data.pop(DATA_VIEW, None)
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components import frontend

    for path in (VIEW_PATH, FORM_PATH):
        frontend.async_remove_panel(hass, path, warn_if_unknown=False)
