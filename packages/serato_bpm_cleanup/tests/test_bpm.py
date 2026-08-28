from serato_bpm_cleanup.bpm import is_non_integer_bpm, proposed_integer_bpm


def test_integer_stays():
    assert not is_non_integer_bpm(128.0)
    assert not is_non_integer_bpm(128.00)
    assert not is_non_integer_bpm(128.01)


def test_fractional_flagged():
    assert is_non_integer_bpm(128.31)
    assert is_non_integer_bpm(128.5)
    assert is_non_integer_bpm(128.02)


def test_round_nearest_not_double_half():
    assert proposed_integer_bpm(128.31) == 128
    assert proposed_integer_bpm(127.6) == 128
    assert proposed_integer_bpm(140.4) == 140
    assert proposed_integer_bpm(69.6) == 70
