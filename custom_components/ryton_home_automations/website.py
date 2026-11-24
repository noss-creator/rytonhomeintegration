"""Calls the website's house functions.

This is the only place the house uses the network. Nothing that runs an
automation depends on it: when a call fails the house keeps running the
schedule it has.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import WEBSITE_PUBLISHABLE_KEY, WEBSITE_URL

TIMEOUT_SECONDS = 30


class WebsiteError(Exception):
    """The website could not be reached."""


class WebsiteRefused(WebsiteError):
    """The website answered and said no, for example to a wrong key or code."""


async def async_call(hass: HomeAssistant, function: str, payload: dict[str, Any]) -> Any:
    """Call one of the house functions and return its answer."""
    session = async_get_clientsession(hass)
    url = f"{WEBSITE_URL}/rest/v1/rpc/{function}"
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async with session.post(
                url, json=payload, headers={"apikey": WEBSITE_PUBLISHABLE_KEY}
            ) as response:
                if response.status == 204:
                    return None
                try:
                    body = await response.json(content_type=None)
                except ValueError:
                    body = None
                if response.status == 200:
                    return body
                message = body.get("message") if isinstance(body, dict) else None
                raise WebsiteRefused(message or f"the website answered {response.status}")
    except (aiohttp.ClientError, TimeoutError) as err:
        raise WebsiteError(f"the website could not be reached: {err}") from err


async def async_pair(hass: HomeAssistant, pairing_code: str) -> dict[str, Any]:
    """Exchange a pairing code for this house's key."""
    answer = await async_call(hass, "automations_pair", {"pairing_code": pairing_code})
    if not isinstance(answer, dict) or not answer.get("house_key") or not answer.get("house_id"):
        raise WebsiteRefused("the website did not send a house key")
    return answer
