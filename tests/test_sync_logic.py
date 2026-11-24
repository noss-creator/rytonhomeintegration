"""The decisions of the sync with the website. Runs without Home Assistant or a network."""

from __future__ import annotations

import pytest

from engine.sync_logic import accept_schedule, build_inventory, fingerprint
from engine.time_resolver import ScheduleError

from .test_day_list import make_schedule

HOUSE = "0f8fad5b-d9cb-469f-a165-70867728950e"


def fetched(**changes):
    schedule = make_schedule()
    schedule.update({"house_id": HOUSE, "revision": 3})
    schedule.update(changes)
    return schedule


# --- which schedules the house accepts -------------------------------------


def test_a_newer_schedule_for_this_house_is_accepted():
    assert accept_schedule(fetched(), HOUSE, 2)["revision"] == 3
    assert accept_schedule(fetched(), HOUSE, None)["revision"] == 3


@pytest.mark.parametrize("have", [3, 4])
def test_a_schedule_that_is_not_newer_is_refused(have):
    with pytest.raises(ScheduleError, match="not newer"):
        accept_schedule(fetched(), HOUSE, have)


def test_another_houses_schedule_is_refused():
    with pytest.raises(ScheduleError, match="another house"):
        accept_schedule(fetched(house_id="some-other-house"), HOUSE, None)


def test_a_format_the_engine_does_not_know_is_refused():
    with pytest.raises(ScheduleError, match="not understood"):
        accept_schedule(fetched(format_version=2), HOUSE, None)


@pytest.mark.parametrize("revision", [None, 0, -1, "3", True, 2.5])
def test_a_schedule_with_no_proper_revision_is_refused(revision):
    with pytest.raises(ScheduleError):
        accept_schedule(fetched(revision=revision), HOUSE, None)


@pytest.mark.parametrize("junk", [None, "schedule", [], 7, {"days": {}}])
def test_something_that_is_not_a_schedule_is_refused(junk):
    with pytest.raises(ScheduleError):
        accept_schedule(junk, HOUSE, None)


# --- the room and entity list ----------------------------------------------

FLOORS = [
    {"id": "first_floor", "name": "First Floor", "level": 1},
    {"id": "basement", "name": "Basement", "level": -1},
    {"id": "ground_floor", "name": "Ground Floor", "level": 0},
]
AREAS = [
    {"id": "kitchen", "name": "Kitchen", "floor_id": "ground_floor"},
    {"id": "bedroom", "name": "Master Bedroom", "floor_id": "first_floor"},
    {"id": "shed", "name": "Shed", "floor_id": None},
]
ENTITIES = [
    {"entity_id": "light.kitchen_spots", "name": "Kitchen Spots", "area_id": "kitchen", "dimmable": True},
    {"entity_id": "select.kitchen_freezer_mode", "name": "Freezer Mode", "area_id": "kitchen",
     "options": ["Normal", "Sabbath"]},
    {"entity_id": "cover.bedroom_shade", "name": "Shade", "area_id": "bedroom", "position": True},
    {"entity_id": "sensor.kitchen_temperature", "name": "Temperature", "area_id": "kitchen"},
    {"entity_id": "light.shed", "name": "Shed Light", "area_id": "shed"},
    {"entity_id": "switch.loose", "name": "Loose Switch", "area_id": None},
    {"entity_id": "scene.kitchen_shabbos", "name": "Kitchen Shabbos", "area_id": "kitchen"},
]


def test_floors_are_in_order_from_the_bottom_with_their_rooms():
    inventory = build_inventory(FLOORS, AREAS, ENTITIES)
    assert [f["id"] for f in inventory["floors"]] == ["basement", "ground_floor", "first_floor"]
    ground = inventory["floors"][1]
    assert [r["id"] for r in ground["rooms"]] == ["kitchen"]
    assert inventory["floors"][0]["rooms"] == []


def test_only_schedulable_entities_are_listed_with_what_they_support():
    kitchen = build_inventory(FLOORS, AREAS, ENTITIES)["floors"][1]["rooms"][0]
    assert kitchen["entities"] == [
        {"entity_id": "light.kitchen_spots", "name": "Kitchen Spots", "dimmable": True},
        {"entity_id": "scene.kitchen_shabbos", "name": "Kitchen Shabbos"},
        {"entity_id": "select.kitchen_freezer_mode", "name": "Freezer Mode",
         "options": ["Normal", "Sabbath"]},
    ]


def test_a_room_with_no_floor_and_an_entity_with_no_room_are_kept_apart():
    inventory = build_inventory(FLOORS, AREAS, ENTITIES)
    assert [r["id"] for r in inventory["rooms_with_no_floor"]] == ["shed"]
    assert inventory["rooms_with_no_floor"][0]["entities"][0]["entity_id"] == "light.shed"
    assert inventory["entities_with_no_room"] == [
        {"entity_id": "switch.loose", "name": "Loose Switch"}
    ]


def test_the_same_house_gives_the_same_list_whatever_the_order():
    one = build_inventory(FLOORS, AREAS, ENTITIES)
    two = build_inventory(FLOORS[::-1], AREAS[::-1], ENTITIES[::-1])
    assert one == two
    assert fingerprint(one) == fingerprint(two)


def test_a_change_in_the_house_changes_the_fingerprint():
    before = fingerprint(build_inventory(FLOORS, AREAS, ENTITIES))
    more = ENTITIES + [{"entity_id": "light.new", "name": "New", "area_id": "kitchen"}]
    assert fingerprint(build_inventory(FLOORS, AREAS, more)) != before
    renamed = [dict(ENTITIES[0], name="Renamed")] + ENTITIES[1:]
    assert fingerprint(build_inventory(FLOORS, AREAS, renamed)) != before


def test_an_empty_house():
    assert build_inventory([], [], []) == {
        "floors": [], "rooms_with_no_floor": [], "entities_with_no_room": [],
    }
