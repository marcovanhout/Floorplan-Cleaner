from src.core.names import is_code_text, sanitize_filename


def test_sanitize_filename_basic():
    assert sanitize_filename("Toilet") == "toilet"
    assert sanitize_filename("  Wacht ruimte  ") == "wacht_ruimte"
    assert sanitize_filename("Berging/Techniek") == "bergingtechniek"
    assert sanitize_filename("Kamer #3!") == "kamer_3"


def test_sanitize_filename_empty_falls_back():
    assert sanitize_filename("") == "ruimte"
    assert sanitize_filename("   ") == "ruimte"
    assert sanitize_filename("###") == "ruimte"


def test_is_code_text_recognizes_room_codes_and_dimensions():
    assert is_code_text("ZHD-1.234")
    assert is_code_text("P-P2d")
    assert is_code_text("12.5m2")
    assert is_code_text("3600")
    assert is_code_text("")
    assert is_code_text("   ")


def test_is_code_text_does_not_flag_real_names():
    assert not is_code_text("Toilet")
    assert not is_code_text("Wachtruimte")
    assert not is_code_text("Voorbereiding kamer PET-CT")
