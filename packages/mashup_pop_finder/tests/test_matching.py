from mashup_pop_finder.matching import classify_match_type, is_harmonic_match, ratio_to_base


class TestIsHarmonicMatch:
    def test_exact_1x_passes(self) -> None:
        assert is_harmonic_match(100, 100, 0.20)

    def test_within_pos_tol_1x(self) -> None:
        # 100 → upper bound 120
        assert is_harmonic_match(100, 119.9, 0.20)
        assert not is_harmonic_match(100, 120.1, 0.20)

    def test_within_neg_tol_1x(self) -> None:
        # 100 → lower bound 80
        assert is_harmonic_match(100, 80.1, 0.20)
        assert not is_harmonic_match(100, 79.9, 0.20)

    def test_2x_match(self) -> None:
        # 100 → 200 ±20% = [160, 240]
        assert is_harmonic_match(100, 200, 0.20)
        assert is_harmonic_match(100, 161, 0.20)
        assert is_harmonic_match(100, 239, 0.20)
        assert not is_harmonic_match(100, 159, 0.20)
        assert not is_harmonic_match(100, 241, 0.20)

    def test_half_match(self) -> None:
        # 100 → 50 ±20% = [40, 60]
        assert is_harmonic_match(100, 50, 0.20)
        assert is_harmonic_match(100, 41, 0.20)
        assert is_harmonic_match(100, 59, 0.20)
        assert not is_harmonic_match(100, 39, 0.20)
        assert not is_harmonic_match(100, 61, 0.20)

    def test_gap_between_1x_and_2x_fails(self) -> None:
        # 100: 1x covers up to 120, 2x starts at 160 → 140 is a gap
        assert not is_harmonic_match(100, 140, 0.20)

    def test_gap_between_05_and_1x_fails(self) -> None:
        # 100: 0.5x covers up to 60, 1x starts at 80 → 70 is a gap
        assert not is_harmonic_match(100, 70, 0.20)

    def test_zero_or_negative_inputs(self) -> None:
        assert not is_harmonic_match(0, 100, 0.20)
        assert not is_harmonic_match(100, 0, 0.20)
        assert not is_harmonic_match(-1, 100, 0.20)


class TestClassifyMatchType:
    def test_classifies_1x(self) -> None:
        assert classify_match_type(100, 102, 0.20) == "1x"

    def test_classifies_2x(self) -> None:
        assert classify_match_type(100, 200, 0.20) == "2x"

    def test_classifies_half(self) -> None:
        assert classify_match_type(100, 50, 0.20) == "0.5x"

    def test_no_match_returns_empty(self) -> None:
        assert classify_match_type(100, 140, 0.20) == ""

    def test_closest_ratio_wins_when_both_in_range(self) -> None:
        # Edge case: with tolerance=0.50, both 1x and 2x might cover 140.
        # 1x deviation = |140/100 - 1| = 0.40
        # 2x deviation = |140/200 - 1| = 0.30 → 2x wins
        result = classify_match_type(100, 140, 0.50)
        assert result == "2x"


class TestRatioToBase:
    def test_basic(self) -> None:
        assert ratio_to_base(100, 200) == 2.0
        assert ratio_to_base(100, 50) == 0.5
        assert ratio_to_base(100, 100) == 1.0

    def test_zero_base(self) -> None:
        assert ratio_to_base(0, 100) == 0.0
