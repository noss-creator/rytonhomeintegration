"""Carries out an automation's steps, then checks and retries.

The sequence, as decided:

1. send every call, scenes one at a time, entities in groups with a pause
2. wait, then check the state of every entity that was set
3. send the failures again, wait, check
4. send the failures again, wait, check
5. report whatever is still failing

Home Assistant is reached only through the three functions passed in, so
this runs in tests without it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .actions import Call, Step

CHECK_WAIT_SECONDS = 10
ATTEMPTS = 3

Send = Callable[[Call], Awaitable[None]]
# Returns (state, attributes), or None when Home Assistant has no such entity.
GetState = Callable[[str], "tuple[str, Mapping[str, Any]] | None"]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class Failure:
    """A call that still had not taken effect after the last attempt."""

    call: Call
    reason: str


def _problem(call: Call, send_error: str | None, get_state: GetState) -> str | None:
    """Return why ``call`` has not taken effect, or None if it has."""
    if send_error is not None:
        return send_error
    if call.expected is None:
        return None  # a scene: it was sent, and there is nothing to check
    found = get_state(call.entity_id)
    if found is None:
        return "Home Assistant has no such entity"
    state, attributes = found
    if call.expected.is_met(state, attributes):
        return None
    return f"its state is {state}"


async def carry_out(
    steps: Sequence[Step],
    send: Send,
    get_state: GetState,
    sleep: Sleep,
    *,
    group_size: int = 5,
    pause_seconds: float = 1,
    check_wait: float = CHECK_WAIT_SECONDS,
    attempts: int = ATTEMPTS,
) -> list[Failure]:
    """Carry out ``steps`` and return what still failed after the last attempt."""
    errors: dict[int, str] = {}

    async def send_all(groups: Sequence[Step]) -> None:
        for group in groups:
            for call in group.calls:
                errors.pop(id(call), None)
                try:
                    await send(call)
                except Exception as err:  # noqa: BLE001 - any failure is retried and reported
                    errors[id(call)] = f"could not be set: {err}"
            await sleep(group.pause_seconds)

    await send_all(steps)
    pending = [call for step in steps for call in step.calls]
    if not pending:
        return []

    problems: dict[int, str] = {}
    for attempt in range(1, attempts + 1):
        await sleep(check_wait)
        problems = {}
        for call in pending:
            problem = _problem(call, errors.get(id(call)), get_state)
            if problem is not None:
                problems[id(call)] = problem
        pending = [call for call in pending if id(call) in problems]
        if not pending or attempt == attempts:
            break
        await send_all(
            [
                Step(tuple(pending[start : start + group_size]), pause_seconds)
                for start in range(0, len(pending), group_size)
            ]
        )

    return [Failure(call, problems[id(call)]) for call in pending]
