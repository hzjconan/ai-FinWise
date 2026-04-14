from decimal import Decimal

from app.services.risk_calculator import (
    calculate_product_risk,
    calculate_risk_preference,
    MATCH_RULES,
)


class TestCalculateProductRisk:
    def test_no_data(self):
        er, sd, rl = calculate_product_risk([])
        assert er is None and sd is None and rl is None

    def test_single_data_point(self):
        er, sd, rl = calculate_product_risk([Decimal("5.0")])
        assert er == Decimal("5.0")
        assert sd == Decimal("0")
        assert rl == "R1"

    def test_low_risk(self):
        # Very close rates → small stddev → R1
        rates = [Decimal("4.00"), Decimal("4.01"), Decimal("3.99")]
        er, sd, rl = calculate_product_risk(rates)
        assert rl == "R1"
        assert sd < Decimal("1")

    def test_medium_low_risk(self):
        # stddev between 1% and 3% → R2
        rates = [Decimal("2.0"), Decimal("5.0"), Decimal("3.0"), Decimal("4.0")]
        er, sd, rl = calculate_product_risk(rates)
        assert rl == "R2"

    def test_medium_risk(self):
        # stddev between 3% and 8% → R3
        rates = [Decimal("2.0"), Decimal("10.0"), Decimal("5.0"), Decimal("8.0")]
        er, sd, rl = calculate_product_risk(rates)
        assert rl == "R3"

    def test_medium_high_risk(self):
        # stddev between 8% and 15% → R4
        rates = [Decimal("-5.0"), Decimal("20.0"), Decimal("5.0"), Decimal("15.0")]
        er, sd, rl = calculate_product_risk(rates)
        assert rl == "R4"

    def test_high_risk(self):
        # stddev >= 15% → R5
        rates = [Decimal("-20.0"), Decimal("40.0"), Decimal("0.0"), Decimal("30.0")]
        er, sd, rl = calculate_product_risk(rates)
        assert rl == "R5"

    def test_expected_return_calculation(self):
        rates = [Decimal("4.0"), Decimal("6.0")]
        er, sd, rl = calculate_product_risk(rates)
        assert er == Decimal("5.0")


class TestCalculateRiskPreference:
    def test_conservative(self):
        # score 1 out of 10 → 10% → C1
        norm, code, label, desc = calculate_risk_preference(1, 10)
        assert code == "C1"
        assert label == "保守型"

    def test_steady(self):
        # score 3 out of 10 → 30% → C2
        norm, code, label, desc = calculate_risk_preference(3, 10)
        assert code == "C2"

    def test_balanced(self):
        # score 5 out of 10 → 50% → C3
        norm, code, label, desc = calculate_risk_preference(5, 10)
        assert code == "C3"

    def test_growth(self):
        # score 7 out of 10 → 70% → C4
        norm, code, label, desc = calculate_risk_preference(7, 10)
        assert code == "C4"

    def test_aggressive(self):
        # score 9 out of 10 → 90% → C5
        norm, code, label, desc = calculate_risk_preference(9, 10)
        assert code == "C5"

    def test_boundary_20(self):
        # Exactly 20% → C2 (not C1)
        norm, code, label, desc = calculate_risk_preference(20, 100)
        assert code == "C2"

    def test_boundary_below_20(self):
        norm, code, label, desc = calculate_risk_preference(19, 100)
        assert code == "C1"


class TestMatchRules:
    def test_all_preferences_covered(self):
        for code in ["C1", "C2", "C3", "C4", "C5"]:
            assert code in MATCH_RULES

    def test_c1_no_conservative(self):
        assert MATCH_RULES["C1"]["conservative"] == []

    def test_c5_no_aggressive(self):
        assert MATCH_RULES["C5"]["aggressive"] == []

    def test_c3_has_both_adjacent(self):
        rules = MATCH_RULES["C3"]
        assert rules["exact"] == ["R3"]
        assert rules["conservative"] == ["R2"]
        assert rules["aggressive"] == ["R4"]
