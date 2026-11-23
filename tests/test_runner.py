"""Carrying out an automation, then checking and retrying.

Runs without Home Assistant. A small pretend house stands in for it: it
records what was sent and when, and can be told to ignore an entity.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

from engine.actions import plan_steps
from engine.day_list import DayList, ScheduledAutomation
from engine.day_resolver import ResolvedDay
from engine.due import split_due
from engine.runner import carry_out

ON, OFF = {"state": "on"}, {"state": "off"}


class House:
    """A pretend Home Assistant with a clock that only moves when asked to sleep."""

    def __init__(self, states, ignores=None, missing=(), broken=()):
        self.states = dict(states)
        self.ignores = dict(ignores or {})  # entity -> how many sends it ignores
        self.missing = set(missing)
        self.broken = set(broken)  # sending to these raises
        self.clock = 0.0
        self.log = []  # (time, entity, service)

    async def send(self, call):
        self.log.append((self.clock, call.entity_id, call.service))
        if call.entity_id in self.broken:
            raise RuntimeError("service not found")
        if call.entity_id in self.missing:
            return
        if self.ignores.get(call.entity_id, 0) > 0:
            self.ignores[call.entity_id] -= 1
            return
        self.states[call.entity_id] = {
            "turn_on": "on", "turn_off": "off", "open_cover": "open",
            "close_cover": "closed",
        }.get(call.service, call.data.get("option"))

    def get_state(self, entity_id):
        if entity_id in self.missing or entity_id not in self.states:
            return None
        return self.states[entity_id], {}

    async def sleep(self, seconds):
        self.clock += seconds

    def run(self, rooms, **kwargs):
        steps = plan_steps(rooms, **kwargs)
        return asyncio.run(carry_out(steps, self.send, self.get_state, self.sleep))

    def sends(self, entity_id):
        return [time for time, entity, _ in self.log if entity == entity_id]


def room(**entities):
    return {"room": {"entities": dict(entities)}}


# --- when everything works -------------------------------------------------


def test_everything_works_first_time():
    house = House({"light.a": "off", "light.b": "on"})
    failures = house.run(room(**{"light.a": ON, "light.b": OFF}))
    assert failures == []
    assert house.states == {"light.a": "on", "light.b": "off"}
    assert len(house.log) == 2  # nothing is sent twice
    assert house.clock == 1 + 10  # the pause after the group, then one check


def test_an_automation_that_does_nothing_does_not_wait():
    house = House({})
    assert house.run({}) == []
    assert house.clock == 0


def test_groups_are_sent_with_the_pause_between_them():
    lights = {f"light.l{n}": ON for n in range(12)}
    house = House({name: "off" for name in lights})
    assert house.run(room(**lights)) == []
    times = [time for time, _, _ in house.log]
    assert times == [0] * 5 + [1] * 5 + [2] * 2
    assert house.clock == 3 + 10


# --- retries ---------------------------------------------------------------


def test_a_miss_is_sent_again_after_ten_seconds_and_then_works():
    house = House({"light.a": "off", "light.b": "off"}, ignores={"light.a": 1})
    failures = house.run(room(**{"light.a": ON, "light.b": ON}))
    assert failures == []
    assert house.sends("light.a") == [0, 11]  # sent, checked at 11, sent again
    assert house.sends("light.b") == [0]  # the one that worked is left alone
    assert house.states["light.a"] == "on"


def test_the_decided_sequence_three_sends_three_checks_then_report():
    house = House({"light.a": "off"}, ignores={"light.a": 99})
    [failure] = house.run(room(**{"light.a": ON}))
    assert failure.call.entity_id == "light.a"
    assert failure.reason == "its state is off"
    # Sent at 0. Checked at 11, sent again. Checked at 22, sent again.
    # Checked at 33 and reported.
    assert house.sends("light.a") == [0, 11, 22]
    assert house.clock == 33


def test_it_works_on_the_third_send():
    house = House({"light.a": "off"}, ignores={"light.a": 2})
    assert house.run(room(**{"light.a": ON})) == []
    assert house.sends("light.a") == [0, 11, 22]


def test_only_the_failures_are_reported():
    states = {f"light.l{n}": "off" for n in range(7)}
    house = House(states, ignores={"light.l2": 99, "light.l5": 99})
    failures = house.run(room(**{name: ON for name in states}))
    assert [f.call.entity_id for f in failures] == ["light.l2", "light.l5"]
    assert all(house.states[name] == "on" for name in states if name not in ("light.l2", "light.l5"))


def test_an_entity_the_house_no_longer_has_is_reported():
    house = House({"light.a": "off"}, missing={"light.gone"})
    [failure] = house.run(room(**{"light.a": ON, "light.gone": ON}))
    assert failure.call.entity_id == "light.gone"
    assert failure.reason == "Home Assistant has no such entity"
    assert house.states["light.a"] == "on"  # the rest still ran


def test_a_send_that_raises_is_retried_and_reported():
    house = House({"light.a": "off"}, broken={"light.a"})
    [failure] = house.run(room(**{"light.a": ON}))
    assert "could not be set" in failure.reason
    assert len(house.sends("light.a")) == 3


def test_one_failing_send_does_not_stop_the_others():
    house = House({"light.a": "off", "light.b": "off"}, broken={"light.a"})
    failures = house.run(room(**{"light.a": ON, "light.b": ON}))
    assert [f.call.entity_id for f in failures] == ["light.a"]
    assert house.states["light.b"] == "on"


# --- scenes, shades and mode lists -----------------------------------------


def test_a_scene_is_sent_once_and_not_checked():
    house = House({})
    assert house.run({"living_room": {"scene": "scene.shabbos"}}) == []
    assert house.sends("scene.shabbos") == [0]


def test_a_scene_that_cannot_be_sent_is_reported():
    house = House({}, broken={"scene.gone"})
    [failure] = house.run({"living_room": {"scene": "scene.gone"}})
    assert failure.call.entity_id == "scene.gone"
    assert len(house.sends("scene.gone")) == 3


def test_shades_and_mode_lists_are_checked_too():
    house = House(
        {"cover.shade": "open", "select.freezer": "Normal"},
        ignores={"select.freezer": 1},
    )
    failures = house.run(
        room(**{"cover.shade": {"state": "closed"}, "select.freezer": {"option": "Sabbath"}})
    )
    assert failures == []
    assert house.states == {"cover.shade": "closed", "select.freezer": "Sabbath"}
    assert house.sends("select.freezer") == [0, 11]


# --- what is upcoming and what was missed ----------------------------------

UTC = timezone.utc
START = datetime(2027, 6, 18, 4, 0, tzinfo=UTC)


def _day_list(*hours):
    automations = tuple(
        ScheduledAutomation(f"at_{hour}", f"At {hour}", START + timedelta(hours=hour), 0, {})
        for hour in hours
    )
    day = date(2027, 6, 18)
    return DayList(day, ResolvedDay(day, "weekday", "weekday"), None, automations)


def _ids(automations):
    return [a.id for a in automations]


def test_upcoming_and_missed_are_split_at_now():
    lists = [_day_list(3, 12, 14, 19)]
    now = START + timedelta(hours=15)
    missed, upcoming = split_due(lists, START + timedelta(hours=5), now)
    assert _ids(missed) == ["at_12", "at_14"]
    assert _ids(upcoming) == ["at_19"]


def test_what_ran_before_the_engine_last_ran_is_not_missed():
    lists = [_day_list(3, 12, 14)]
    now = START + timedelta(hours=15)
    missed, _ = split_due(lists, START + timedelta(hours=12), now)
    assert _ids(missed) == ["at_14"]


def test_nothing_is_missed_the_first_time_the_engine_starts():
    lists = [_day_list(3, 12, 14, 19)]
    missed, upcoming = split_due(lists, None, START + timedelta(hours=15))
    assert missed == []
    assert _ids(upcoming) == ["at_19"]


def test_lists_of_two_days_are_put_in_one_time_order():
    yesterday, today = _day_list(20, 26), _day_list(27, 30)
    now = START + timedelta(hours=25)
    missed, upcoming = split_due([today, yesterday], START, now)
    assert _ids(missed) == ["at_20"]
    assert _ids(upcoming) == ["at_26", "at_27", "at_30"]


def test_an_automation_due_exactly_now_counts_as_missed_not_upcoming():
    lists = [_day_list(12)]
    now = START + timedelta(hours=12)
    missed, upcoming = split_due(lists, START, now)
    assert _ids(missed) == ["at_12"] and upcoming == []
