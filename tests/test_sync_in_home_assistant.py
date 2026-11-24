"""Pairing and syncing with the website, inside a real Home Assistant core.

The website is a stand-in: these tests never use the network. They check
what the house sends, what it does with the answer, and that it keeps running
when the website cannot be reached.

Needs Home Assistant's test tools, which do not load on Windows. On GitHub
these tests run on Linux.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component.common")

import aiohttp  # noqa: E402

from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402

from custom_components.ryton_home_automations.const import (  # noqa: E402
    DOMAIN,
    WEBSITE_PUBLISHABLE_KEY,
    WEBSITE_URL,
)

from .test_day_list import make_schedule  # noqa: E402
from .test_time_travel import (  # noqa: E402, F401
    START,
    _enable_custom_integrations,
    _instant_waits,
    house,
    local,
)

RPC = f"{WEBSITE_URL}/rest/v1/rpc"
HOUSE_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
HOUSE_KEY = "k" * 64


def published(revision: int, house_id: str = HOUSE_ID):
    schedule = make_schedule()
    schedule.update({"house_id": house_id, "revision": revision})
    return schedule


def calls_to(aioclient_mock, function: str):
    return [
        call for call in aioclient_mock.mock_calls if str(call[1]).endswith(f"/rpc/{function}")
    ]


async def sync_now(hass):
    return await hass.services.async_call(
        DOMAIN, "sync_now", {}, blocking=True, return_response=True
    )


@pytest.fixture
async def paired(house, aioclient_mock):
    """The test house, paired, with a website that has published nothing yet."""
    await house.hass.config_entries.async_remove(house.entry.entry_id)
    await house.hass.async_block_till_done()
    house.entry = None
    house.entry_data = {"house_id": HOUSE_ID, "house_name": "Test", "house_key": HOUSE_KEY}

    aioclient_mock.post(f"{RPC}/automations_get_schedule", json={"revision": None, "schedule": None})
    for function in ("automations_put_inventory", "automations_put_preview", "automations_put_report"):
        aioclient_mock.post(f"{RPC}/{function}", status=204)
    await house.start_integration()
    return house


def publish(aioclient_mock, answer=None, **kwargs):
    """Change what the stand-in website answers to "give me my schedule"."""
    aioclient_mock.clear_requests()
    if answer is not None:
        kwargs["json"] = answer
    aioclient_mock.post(f"{RPC}/automations_get_schedule", **kwargs)
    for function in ("automations_put_inventory", "automations_put_preview", "automations_put_report"):
        aioclient_mock.post(f"{RPC}/{function}", status=204)


# --- pairing ---------------------------------------------------------------


async def test_pairing_with_a_code_stores_the_houses_key(hass: HomeAssistant, aioclient_mock, enable_custom_integrations):
    aioclient_mock.post(
        f"{RPC}/automations_pair",
        json={"house_id": HOUSE_ID, "house_name": "Cohen", "house_key": HOUSE_KEY},
    )
    aioclient_mock.post(f"{RPC}/automations_get_schedule", json={"revision": None, "schedule": None})
    for function in ("automations_put_inventory", "automations_put_preview", "automations_put_report"):
        aioclient_mock.post(f"{RPC}/{function}", status=204)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pairing_code": " ab12-cd34-ef56 "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"house_id": HOUSE_ID, "house_name": "Cohen", "house_key": HOUSE_KEY}

    [call] = calls_to(aioclient_mock, "automations_pair")
    assert call[2] == {"pairing_code": "ab12-cd34-ef56"}
    assert call[3]["apikey"] == WEBSITE_PUBLISHABLE_KEY
    assert "Authorization" not in call[3]
    await hass.async_block_till_done()


async def test_a_refused_pairing_code_shows_an_error(hass: HomeAssistant, aioclient_mock, enable_custom_integrations):
    aioclient_mock.post(
        f"{RPC}/automations_pair", status=400, json={"message": "invalid pairing code"}
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pairing_code": "AAAA-BBBB-CCCC"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_pairing_code"}


async def test_pairing_with_no_internet_shows_an_error(hass: HomeAssistant, aioclient_mock, enable_custom_integrations):
    aioclient_mock.post(f"{RPC}/automations_pair", exc=aiohttp.ClientError("no route"))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pairing_code": "AAAA-BBBB-CCCC"}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_an_unpaired_house_never_calls_the_website(house, aioclient_mock):
    await house.reload_schedule()
    response = await sync_now(house.hass)
    assert response["paired"] is False
    assert aioclient_mock.mock_calls == []


# --- fetching a schedule ---------------------------------------------------


async def test_a_published_schedule_is_fetched_and_run(paired, aioclient_mock):
    publish(aioclient_mock, {"revision": 5, "schedule": published(5)})
    response = await sync_now(paired.hass)
    assert response["result"] == "took revision 5 from the website"
    assert response["revision"] == 5

    [call] = calls_to(aioclient_mock, "automations_get_schedule")
    assert call[2] == {"house_key": HOUSE_KEY, "have_revision": None}
    assert call[3]["apikey"] == WEBSITE_PUBLISHABLE_KEY

    # The Jewish Calendar was set to match, and the schedule runs.
    assert paired.jewish_calendar.options["candle_lighting_minutes_before_sunset"] == 18
    await paired.move_to(local(START, "07:00"))
    assert [scene for _, scene in paired.scenes] == ["scene.weekday"]


async def test_the_house_says_which_revision_it_has(paired, aioclient_mock):
    publish(aioclient_mock, {"revision": 5, "schedule": published(5)})
    await sync_now(paired.hass)
    publish(aioclient_mock, {"revision": 5, "schedule": None})
    response = await sync_now(paired.hass)
    assert response["result"] == "up to date at revision 5"
    [call] = calls_to(aioclient_mock, "automations_get_schedule")
    assert call[2]["have_revision"] == 5


async def test_the_fetched_schedule_survives_a_restart_with_no_internet(paired, aioclient_mock):
    publish(aioclient_mock, {"revision": 5, "schedule": published(5)})
    await sync_now(paired.hass)
    await paired.stop_integration()
    publish(aioclient_mock, exc=aiohttp.ClientError("offline"))
    await paired.start_integration()
    await paired.move_to(local(START, "07:00"))
    assert [scene for _, scene in paired.scenes] == ["scene.weekday"]


async def test_with_no_internet_the_house_keeps_running(paired, aioclient_mock):
    await paired.reload_schedule()
    publish(aioclient_mock, exc=aiohttp.ClientError("offline"))
    response = await sync_now(paired.hass)
    assert "could not be reached" in response["result"]
    await paired.move_to(local(START, "07:00"))
    await paired.move_to(local(START, "18:00"))
    assert len(paired.scenes) == 2


async def test_a_schedule_for_another_house_is_refused_and_the_old_one_kept(paired, aioclient_mock, caplog):
    publish(aioclient_mock, {"revision": 5, "schedule": published(5)})
    await sync_now(paired.hass)
    publish(aioclient_mock, {"revision": 6, "schedule": published(6, house_id="another-house")})
    response = await sync_now(paired.hass)
    assert "another house" in response["result"]
    assert response["revision"] == 5
    assert "A schedule from the website was refused" in caplog.text


async def test_a_schedule_in_an_unknown_format_is_refused(paired, aioclient_mock):
    newer = published(7)
    newer["format_version"] = 2
    publish(aioclient_mock, {"revision": 7, "schedule": newer})
    response = await sync_now(paired.hass)
    assert "refused" in response["result"]
    assert response["revision"] is None


async def test_a_key_that_no_longer_works_is_reported_and_nothing_breaks(paired, aioclient_mock):
    await paired.reload_schedule()
    publish(aioclient_mock, status=400, json={"message": "invalid house key"})
    response = await sync_now(paired.hass)
    assert response["result"] == "the website refused: invalid house key"
    await paired.move_to(local(START, "07:00"))
    assert len(paired.scenes) == 1


# --- what the house sends up -----------------------------------------------


async def test_the_room_list_is_sent_once_and_again_only_when_it_changes(paired, aioclient_mock):
    assert len(calls_to(aioclient_mock, "automations_put_inventory")) == 1
    [call] = calls_to(aioclient_mock, "automations_put_inventory")
    assert call[2]["house_key"] == HOUSE_KEY
    assert set(call[2]["inventory"]) == {"floors", "rooms_with_no_floor", "entities_with_no_room"}

    await sync_now(paired.hass)
    await sync_now(paired.hass)
    assert len(calls_to(aioclient_mock, "automations_put_inventory")) == 1


async def test_the_year_preview_is_sent_once_a_schedule_is_running(paired, aioclient_mock):
    assert calls_to(aioclient_mock, "automations_put_preview") == []
    publish(aioclient_mock, {"revision": 5, "schedule": published(5)})
    await sync_now(paired.hass)
    [call] = calls_to(aioclient_mock, "automations_put_preview")
    rows = call[2]["preview"]
    assert len(rows) == 365
    assert rows[0]["date"] == START.isoformat()
    assert rows[0]["day"] == "weekday"
    assert [r for r in rows if "error" in r] == []

    await sync_now(paired.hass)
    assert len(calls_to(aioclient_mock, "automations_put_preview")) == 1
