"""Keeps the house in step with the website.

Down: the house fetches its schedule when a newer one is published.
Up: the house sends its floors, rooms and entities when they change, its year
preview, and any problems it reported.

The house only fetches. A failed sync changes nothing: the house keeps running
the schedule it has, with no internet if need be.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .calendar_reader import async_read_calendar
from .const import CONF_HOUSE_ID, CONF_HOUSE_KEY, DOMAIN, SYNC_MINUTES
from .engine.calendar_snapshot import CalendarDataError
from .engine.preview import LOOK_AHEAD_DAYS, LOOK_BACK_DAYS, build_preview
from .engine.scenes import describe_state
from .engine.sync_logic import accept_schedule, build_inventory, fingerprint
from .engine.time_resolver import ScheduleError
from .scheduler import Scheduler
from .website import WebsiteError, WebsiteRefused, async_call

_LOGGER = logging.getLogger(__name__)

PREVIEW_DAYS = 365
COVER_SET_POSITION = 4  # the cover feature flag for setting a position


class Syncer:
    """The house's side of the sync."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, scheduler: Scheduler) -> None:
        self.hass = hass
        self.scheduler = scheduler
        self.house_id: str | None = entry.data.get(CONF_HOUSE_ID)
        self._house_key: str | None = entry.data.get(CONF_HOUSE_KEY)
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.sync")
        self._sent: dict[str, Any] = {}
        self._interval: CALLBACK_TYPE | None = None
        self.last_result = "not synced yet"

    @property
    def paired(self) -> bool:
        return bool(self.house_id and self._house_key)

    async def async_load(self) -> None:
        self._sent = await self._store.async_load() or {}
        # What was sent went to one house on the website. Paired with another,
        # or with the same one made anew, everything is sent again.
        if self._sent.get("house_id") != self.house_id:
            self._sent = {"house_id": self.house_id}

    @callback
    def async_start(self) -> None:
        """Sync now and then every few minutes."""
        if not self.paired:
            return

        @callback
        def tick(now) -> None:
            self.hass.async_create_task(self.async_sync())

        self._interval = async_track_time_interval(
            self.hass, tick, timedelta(minutes=SYNC_MINUTES)
        )
        self.hass.async_create_task(self.async_sync())

    @callback
    def async_stop(self) -> None:
        if self._interval is not None:
            self._interval()
            self._interval = None

    async def _async_call(self, function: str, **payload: Any) -> Any:
        return await async_call(
            self.hass, function, {"house_key": self._house_key, **payload}
        )

    # --- one round of syncing ---------------------------------------------

    async def async_sync(self) -> str:
        """Fetch a newer schedule if there is one, then send what changed."""
        if not self.paired:
            self.last_result = "this house is not paired with the website"
            return self.last_result
        try:
            fetched = await self._async_fetch_schedule()
            await self._async_send_inventory()
            await self._async_send_preview()
            await self._async_send_report()
        except WebsiteRefused as err:
            # The key no longer works, or the website refused something.
            self.last_result = f"the website refused: {err}"
            _LOGGER.warning("Sync: %s", self.last_result)
        except WebsiteError as err:
            # No internet is normal. The house keeps running what it has.
            self.last_result = str(err)
            _LOGGER.debug("Sync: %s", self.last_result)
        else:
            self.last_result = fetched
        return self.last_result

    async def _async_fetch_schedule(self) -> str:
        current = self.scheduler.schedule or {}
        have = None
        if str(current.get("house_id")) == str(self.house_id):
            have = current.get("revision")
        if isinstance(have, bool) or not isinstance(have, int):
            have = None

        answer = await self._async_call("automations_get_schedule", have_revision=have)
        fetched = answer.get("schedule") if isinstance(answer, dict) else None
        if fetched is None:
            if isinstance(answer, dict) and answer.get("revision") is None:
                return "no schedule has been published for this house yet"
            return f"up to date at revision {have}"

        try:
            schedule = accept_schedule(fetched, self.house_id, have)
            await self.scheduler.async_set_schedule(schedule)
        except (ScheduleError, HomeAssistantError) as err:
            # The house keeps the schedule it was running.
            message = f"A schedule from the website was refused: {err}"
            self.scheduler.report(message)
            return message
        return f"took revision {schedule['revision']} from the website"

    # --- what the house sends up ------------------------------------------

    def inventory(self) -> dict[str, Any]:
        """The house's floors, rooms and entities, as sent to the website."""
        return self._inventory()

    def _inventory(self) -> dict[str, Any]:
        floors = [
            {"id": floor.floor_id, "name": floor.name, "level": floor.level}
            for floor in fr.async_get(self.hass).floors.values()
        ]
        areas = [
            {"id": area.id, "name": area.name, "floor_id": area.floor_id}
            for area in ar.async_get(self.hass).async_list_areas()
        ]
        devices = dr.async_get(self.hass)
        entities = []
        for entry in er.async_get(self.hass).entities.values():
            if entry.disabled_by is not None:
                continue
            area_id = entry.area_id
            if area_id is None and entry.device_id:
                device = devices.async_get(entry.device_id)
                area_id = device.area_id if device else None
            state = self.hass.states.get(entry.entity_id)
            attributes = state.attributes if state else {}
            modes = attributes.get("supported_color_modes") or []
            entities.append(
                {
                    "sets": self._scene_sets(entry.entity_id),
                    "entity_id": entry.entity_id,
                    "name": (state.name if state else None)
                    or entry.name
                    or entry.original_name
                    or entry.entity_id,
                    "area_id": area_id,
                    "options": list(attributes.get("options") or []),
                    "dimmable": any(mode != "onoff" for mode in modes),
                    "position": bool(
                        entry.domain == "cover"
                        and (attributes.get("supported_features") or 0) & COVER_SET_POSITION
                    ),
                }
            )
        return build_inventory(floors, areas, entities)

    def _scene_sets(self, entity_id: str) -> dict[str, str]:
        """What a scene made in Home Assistant sets each of its entities to, in words.

        Empty for anything else, and for a scene whose contents cannot be read.
        """
        if not entity_id.startswith("scene."):
            return {}
        component = self.hass.data.get("scene")
        scene = component.get_entity(entity_id) if component is not None else None
        states = getattr(getattr(scene, "scene_config", None), "states", None)
        if not isinstance(states, dict):
            return {}
        try:
            return {
                str(inside): describe_state(str(inside), state.state, state.attributes)
                for inside, state in sorted(states.items())
            }
        except (AttributeError, TypeError, ValueError):
            return {}

    async def _async_send(self, what: str, function: str, mark: str, **payload: Any) -> None:
        """Send something to the website unless this exact thing was sent already."""
        if self._sent.get(what) == mark:
            return
        await self._async_call(function, **payload)
        self._sent[what] = mark
        await self._store.async_save(self._sent)

    async def _async_send_inventory(self) -> None:
        inventory = self._inventory()
        await self._async_send(
            "inventory", "automations_put_inventory", fingerprint(inventory), inventory=inventory
        )

    async def _async_send_preview(self) -> None:
        """Send the coming year, once a day and whenever the schedule changes."""
        schedule = self.scheduler.schedule
        if schedule is None:
            return
        tz = ZoneInfo(self.hass.config.time_zone)
        today = dt_util.now().astimezone(tz).date()
        # The "2" is the layout of the rows. Raising it makes every house send
        # its preview again after an update that changed what a row holds.
        mark = f"2 {today.isoformat()} revision {schedule.get('revision')}"
        if self._sent.get("preview") == mark:
            return
        try:
            calendar = await async_read_calendar(
                self.hass,
                today - timedelta(days=LOOK_BACK_DAYS),
                today + timedelta(days=PREVIEW_DAYS - 1 + LOOK_AHEAD_DAYS),
            )
        except (CalendarDataError, HomeAssistantError) as err:
            _LOGGER.debug("Sync: no year preview, the Jewish Calendar could not be read: %s", err)
            return
        rows = await self.hass.async_add_executor_job(
            build_preview, schedule, calendar, tz, today, PREVIEW_DAYS
        )
        await self._async_send("preview", "automations_put_preview", mark, preview=rows)

    async def _async_send_report(self) -> None:
        problems = list(self.scheduler.problems)
        await self._async_send(
            "report", "automations_put_report", fingerprint(problems), report={"problems": problems}
        )
