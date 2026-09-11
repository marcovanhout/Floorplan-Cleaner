from src.core.pipeline import assign_placeholder_names
from src.core.types import RoomRecord


def test_assign_placeholder_names_orders_top_to_bottom_then_left_to_right():
    # Bewust door elkaar aangemaakt, niet al in kijkvolgorde - de functie
    # moet zelf op bbox-positie sorteren, niet op lijstvolgorde vertrouwen.
    rooms = [
        RoomRecord(id="room_a", bbox=(300, 0, 400, 100), name=None),  # rij 1, rechts
        RoomRecord(id="room_b", bbox=(0, 0, 100, 100), name=None),  # rij 1, links
        RoomRecord(id="room_c", bbox=(0, 200, 100, 300), name=None),  # rij 2
    ]
    assign_placeholder_names(rooms)
    by_id = {r.id: r.name for r in rooms}
    assert by_id["room_b"] == "room_01"
    assert by_id["room_a"] == "room_02"
    assert by_id["room_c"] == "room_03"


def test_assign_placeholder_names_skips_already_named_rooms():
    rooms = [
        RoomRecord(id="room_a", bbox=(0, 0, 100, 100), name="Toilet"),
        RoomRecord(id="room_b", bbox=(200, 0, 300, 100), name=None),
        RoomRecord(id="room_c", bbox=(0, 200, 100, 300), name="Kantoor"),
    ]
    assign_placeholder_names(rooms)
    by_id = {r.id: r.name for r in rooms}
    # Bestaande namen blijven ongewijzigd en tellen niet mee in de telling.
    assert by_id["room_a"] == "Toilet"
    assert by_id["room_c"] == "Kantoor"
    assert by_id["room_b"] == "room_01"


def test_assign_placeholder_names_is_noop_when_all_rooms_already_named():
    rooms = [RoomRecord(id="room_a", bbox=(0, 0, 100, 100), name="Toilet")]
    assign_placeholder_names(rooms)
    assert rooms[0].name == "Toilet"
