"""Tests for Camelot key conversion helpers."""


from library_sync.camelot import (
    get_adjacent_keys,
    get_compatible_keys,
    get_relative_key,
    musical_to_camelot,
    normalize_camelot,
    parse_musical_key,
)


class TestNormalizeCamelot:
    def test_valid_keys(self):
        assert normalize_camelot("8A") == "8A"
        assert normalize_camelot("8a") == "8A"
        assert normalize_camelot("12B") == "12B"
        assert normalize_camelot("1A") == "1A"

    def test_invalid_keys(self):
        assert normalize_camelot("13A") is None
        assert normalize_camelot("0A") is None
        assert normalize_camelot("8C") is None
        assert normalize_camelot("A8") is None


class TestParseMusicalKey:
    def test_major_keys(self):
        assert parse_musical_key("C major") == "C major"
        assert parse_musical_key("C") == "C major"
        assert parse_musical_key("F# major") == "F# major"
        assert parse_musical_key("Db major") == "Db major"

    def test_minor_keys(self):
        assert parse_musical_key("A minor") == "A minor"
        assert parse_musical_key("Am") == "A minor"
        assert parse_musical_key("A min") == "A minor"
        assert parse_musical_key("A m") == "A minor"
        assert parse_musical_key("F#m") == "F# minor"


class TestMusicalToCamelot:
    def test_major_keys(self):
        assert musical_to_camelot("C major") == "8B"
        assert musical_to_camelot("G major") == "9B"
        assert musical_to_camelot("F# major") == "2B"

    def test_minor_keys(self):
        assert musical_to_camelot("A minor") == "8A"
        assert musical_to_camelot("Am") == "8A"
        assert musical_to_camelot("E minor") == "9A"
        assert musical_to_camelot("F#m") == "11A"

    def test_camelot_passthrough(self):
        assert musical_to_camelot("8A") == "8A"
        assert musical_to_camelot("12B") == "12B"


class TestRelativeKey:
    def test_relative_major_minor(self):
        assert get_relative_key("8A") == "8B"
        assert get_relative_key("8B") == "8A"
        assert get_relative_key("1A") == "1B"
        assert get_relative_key("12B") == "12A"


class TestAdjacentKeys:
    def test_middle_keys(self):
        assert sorted(get_adjacent_keys("8A")) == ["7A", "9A"]
        assert sorted(get_adjacent_keys("6B")) == ["5B", "7B"]

    def test_wrap_around(self):
        assert sorted(get_adjacent_keys("1A")) == ["12A", "2A"]
        assert sorted(get_adjacent_keys("12B")) == ["11B", "1B"]


class TestCompatibleKeys:
    def test_8a_compatible(self):
        compatible = get_compatible_keys("8A")
        assert "8A" in compatible
        assert "8B" in compatible  # relative major
        assert "7A" in compatible  # -1
        assert "9A" in compatible  # +1
        assert len(compatible) == 4

    def test_1a_wrap(self):
        compatible = get_compatible_keys("1A")
        assert "1A" in compatible
        assert "1B" in compatible
        assert "12A" in compatible
        assert "2A" in compatible

    def test_lowercase_input(self):
        compatible = get_compatible_keys("8a")
        assert "8A" in compatible
        assert "8B" in compatible
