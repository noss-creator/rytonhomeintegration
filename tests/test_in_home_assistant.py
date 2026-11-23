"""The integration loaded into a real Home Assistant core, started for the test.

NOT YET RUN. These tests need Home Assistant's test tools, which do not work
on the Windows computer this was written on.

This checks the parts that cannot run without Home Assistant: adding the
integration, the preview action, and the reader's request to the calendar.

The Jewish Calendar integration itself is not loaded. A stand-in answers the
calendar request in the shape the real one was recorded to use: dates for
all-day events, UTC times for zmanim, and the last date's all-day event left
out. Its zmanim are made up.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import hdate
import pytest
from hdate.translator import set_language

# Home Assistant's test tools do not run on Windows. Without them these tests
# are skipped. Install pytest-homeassistant-custom-component on Linux to run them.
_common = pytest.importorskip("pytest_homeassistant_custom_component.common")
MockConfigEntry = _common.MockConfigEntry

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402

from custom_components.ryton_home_automations.const import DOMAIN

from .test_day_list import make_schedule

TZ = ZoneInfo("Asia/Jerusalem")
DAILY = "calendar.jewish_calendar_daily_events"
YEARLY = "calendar.jewish_calendar_yearly_events"

_ZMANIM = {
    "Alot HaShachar": "04:40",
    "Netz Hachama": "06:00",
    "Plag Hamincha": "16:45",
    "Shkia": "18:00",
    "Tset Hakochavim (18 minutes)": "18:40",
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    yield


def _utc(day: date, clock: str) -> str:
    local = datetime.combine(day, time.fromisoformat(clock), TZ)
    return local.astimezone(timezone.utc).isoformat()


def _stand_in_events(entity_id: str, start: datetime, end: datetime) -> list[dict]:
    # The hdate library writes in Hebrew unless told otherwise. The real
    # integration sets the language it was configured with.
    set_language("en")
    events = []
    day = start.date()
    last = end.date() - timedelta(days=1)
    while day <= last:
        if entity_id == DAILY:
            if day < last:  # the real calendar leaves out the last all-day event
                text = str(hdate.HebrewDate.from_gdate(day))
                events.append({"start": day.isoformat(), "summary": text})
            for summary, clock in _ZMANIM.items():
                events.append({"start": _utc(day, clock), "summary": summary})
        elif day.weekday() == 4:
            events.append({"start": _utc(day, "17:42"), "summary": "Candle Lighting"})
        elif day.weekday() == 5:
            events.append({"start": _utc(day, "19:12"), "summary": "Havdalah"})
        day += timedelta(days=1)
    return events


@pytest.fixture
async def house(hass: HomeAssistant, tmp_path):
    """A Home Assistant with the integration added and a schedule file in place."""
    await hass.config.async_set_time_zone("Asia/Jerusalem")
    hass.config.config_dir = str(tmp_path)
    assert await async_setup_component(hass, "calendar", {})

    requests = []

    async def get_events(call: ServiceCall):
        requests.append(dict(call.data))
        start = datetime.fromisoformat(call.data["start_date_time"])
        end = datetime.fromisoformat(call.data["end_date_time"])
        return {
            entity_id: {"events": _stand_in_events(entity_id, start, end)}
            for entity_id in call.data["entity_id"]
        }

    hass.services.async_register(
        "calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY
    )

    (tmp_path / "ryton_schedule.json").write_text(
        json.dumps(make_schedule()), encoding="utf-8"
    )

    entry = MockConfigEntry(domain=DOMAIN, title="Ryton Home Automations")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass, entry, requests, tmp_path


async def _preview(hass, **data):
    return await hass.services.async_call(
        DOMAIN, "preview", data, blocking=True, return_response=True
    )


async def test_adding_the_integration_from_the_screen(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ryton Home Automations"


async def test_preview_works_out_a_week(house):
    hass, _, _, _ = house
    response = await _preview(hass, start_date="2027-06-14", days=7)
    rows = response["rows"]
    assert [r["day"] for r in rows] == [
        "weekday", "weekday", "weekday", "weekday", "friday", "shabbos", "weekday",
    ]
    assert rows[0]["hebrew_date"] == "9 sivan 5787"
    friday = rows[4]
    assert friday["shabbos_start"] == "17:42"
    assert [(a["id"], a["time"]) for a in friday["automations"]] == [
        ("morning", "07:00"),
        ("erev_shabbos", "17:32"),
        ("sunset", "18:00"),
        ("night", "23:00"),
    ]
    assert "written_to" not in response


async def test_reader_asks_for_both_calendars_and_enough_days_around(house):
    hass, _, requests, _ = house
    await _preview(hass, start_date="2027-06-14", days=7)
    [request] = requests
    assert request["entity_id"] == [DAILY, YEARLY]
    start = datetime.fromisoformat(request["start_date_time"])
    end = datetime.fromisoformat(request["end_date_time"])
    assert start.utcoffset() is not None and end.utcoffset() is not None
    # Eight days before the first date, for the first evening of Chanukah.
    assert start.date() == date(2027, 6, 6)
    # Ten days after the last date for Rosh Hashana, and two more so the last
    # date's all-day event is returned.
    assert end.date() == date(2027, 7, 2)


async def test_preview_over_chanukah_and_a_combination_day(house):
    hass, _, _, _ = house
    response = await _preview(hass, start_date="2026-12-04", days=2)
    friday, shabbos = response["rows"]
    assert {"id": "chanukah_candle_lighting", "time": "17:27", "alongside": True} in (
        friday["automations"]
    )
    assert {"id": "chanukah_candle_lighting", "time": "19:22", "alongside": True} in (
        shabbos["automations"]
    )

    response = await _preview(hass, start_date="2026-09-26", days=1)
    assert response["rows"][0]["day"] == "succos_1__shabbos"


async def test_preview_for_two_years_has_no_errors(house):
    hass, _, _, _ = house
    response = await _preview(hass, start_date="2026-11-23", days=730)
    rows = response["rows"]
    assert len(rows) == 730
    assert [r for r in rows if "error" in r] == []


async def test_preview_writes_the_list_to_a_file(house):
    hass, _, _, folder = house
    response = await _preview(
        hass, start_date="2027-06-14", days=7, output_file="ryton_preview.txt"
    )
    written = folder / "ryton_preview.txt"
    assert response == {
        "written_to": str(written),
        "dates": 7,
        "errors": 0,
        "first_errors": [],
    }
    lines = written.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("2027-06-14 Monday")
    assert "erev_shabbos 17:32" in lines[4]


async def test_preview_starts_today_when_no_date_is_given(house):
    hass, _, _, _ = house
    response = await _preview(hass, days=1)
    today = datetime.now(TZ).date().isoformat()
    assert response["rows"][0]["date"] == today


async def test_missing_schedule_file_is_reported(house):
    hass, _, _, _ = house
    with pytest.raises(HomeAssistantError, match="No schedule file"):
        await _preview(hass, days=1, schedule_file="not_there.json")


async def test_files_outside_the_configuration_folder_are_refused(house):
    hass, _, _, _ = house
    with pytest.raises(HomeAssistantError, match="outside the configuration folder"):
        await _preview(hass, days=1, schedule_file="../elsewhere.json")
    with pytest.raises(HomeAssistantError, match="outside the configuration folder"):
        await _preview(hass, days=1, output_file="../elsewhere.txt")


async def test_calendar_with_no_hebrew_dates_is_reported(house):
    hass, _, _, _ = house

    async def empty(call: ServiceCall):
        return {entity_id: {"events": []} for entity_id in call.data["entity_id"]}

    hass.services.async_register(
        "calendar", "get_events", empty, supports_response=SupportsResponse.ONLY
    )
    with pytest.raises(HomeAssistantError, match="no Hebrew date"):
        await _preview(hass, days=1)


async def test_removing_the_integration_removes_the_action(house):
    hass, entry, _, _ = house
    assert hass.services.has_service(DOMAIN, "preview")
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, "preview")
