"""Saying in words what an automation changes. Runs without Home Assistant."""

from __future__ import annotations

from engine.describe import describe_rooms

SCENES = {
    "ryton_den_bright": {
        "id": "ryton_den_bright",
        "name": "Bright",
        "room": "den",
        "fade_seconds": 0,
        "entities": {"light.den_a": {"state": "on", "brightness_pct": 80}},
    }
}
ROOMS = {"den": "Den", "hall": "Hall"}
NAMES = {"light.den_a": "Den lamp", "cover.hall": "Hall shade", "scene.evening": "Evening"}


def lines(rooms, rooms_off=()):
    return describe_rooms(
        rooms, SCENES, lambda room: ROOMS.get(room, room), lambda e: NAMES.get(e, e), rooms_off
    )


def test_entities_are_listed_by_name_with_what_they_are_set_to():
    rooms = {
        "den": {"entities": {"light.den_a": {"state": "off"}}},
        "hall": {"entities": {"cover.hall": {"position": 25}, "switch.fan": {"state": "on"}}},
    }
    assert lines(rooms) == ["Den: Den lamp off", "Hall: Hall shade 25% open, switch.fan on"]


def test_a_scene_made_in_the_form_is_shown_by_what_it_sets():
    assert lines({"den": {"scene": "scene.ryton_den_bright"}}) == ["Den: Den lamp on, 80%"]


def test_a_scene_made_in_home_assistant_is_shown_by_its_name():
    assert lines({"hall": {"scene": "scene.evening"}}) == ["Hall: scene Evening"]


def test_a_scene_with_entities_set_after_it_shows_both():
    rooms = {"hall": {"scene": "scene.evening", "entities": {"cover.hall": {"state": "closed"}}}}
    assert lines(rooms) == ["Hall: scene Evening, Hall shade closed"]


def test_rooms_switched_off_and_rooms_with_nothing_set_are_left_out():
    rooms = {
        "den": {"entities": {"light.den_a": {"state": "on"}}},
        "hall": {"entities": {}},
    }
    assert lines(rooms) == ["Den: Den lamp on"]
    assert lines(rooms, rooms_off={"den"}) == []


def test_a_days_identifier_in_words():
    from engine.describe import day_name

    assert day_name("weekday") == "Weekday"
    assert day_name("shabbos_hagadol") == "Shabbos hagadol"
    assert day_name("succos_1") == "Succos, first day"
    assert day_name("succos_1__shabbos") == "Succos, first day on Shabbos"
    assert day_name("erev_pesach__friday") == "Erev pesach on Friday"
    assert day_name("rosh_hashana_2__friday") == "Rosh hashana, second day on Friday"


def test_an_automation_with_no_name_of_its_own_is_named_from_its_identifier():
    from engine.describe import automation_title

    assert automation_title("after_day_seuda", None) == "After day seuda"
    assert automation_title("after_day_seuda", "after_day_seuda") == "After day seuda"
    assert automation_title("x1", "Guests leave") == "Guests leave"
