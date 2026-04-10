import math
from decimal import Decimal


RISK_LEVEL_THRESHOLDS = [
    (Decimal("1"), "R1"),   # σ < 1%
    (Decimal("3"), "R2"),   # 1% ≤ σ < 3%
    (Decimal("8"), "R3"),   # 3% ≤ σ < 8%
    (Decimal("15"), "R4"),  # 8% ≤ σ < 15%
]

PREFERENCE_THRESHOLDS = [
    (20, "C1", "保守型"),
    (40, "C2", "稳健型"),
    (60, "C3", "平衡型"),
    (80, "C4", "成长型"),
]

PREFERENCE_LABELS = {
    "C1": "保守型",
    "C2": "稳健型",
    "C3": "平衡型",
    "C4": "成长型",
    "C5": "激进型",
}

PREFERENCE_DESCRIPTIONS = {
    "C1": "您属于保守型投资者，偏好低风险、稳定收益的产品，不愿意承受本金损失。",
    "C2": "您属于稳健型投资者，希望获得相对稳定的收益，可以承受小幅波动。",
    "C3": "您属于平衡型投资者，愿意承担适度风险以获得合理回报。",
    "C4": "您属于成长型投资者，追求较高收益，能够承受一定程度的损失。",
    "C5": "您属于激进型投资者，追求高收益，能够承受较大的短期波动和潜在损失。",
}

# C-level → matching R-levels
MATCH_RULES: dict[str, dict[str, list[str]]] = {
    "C1": {"exact": ["R1"], "conservative": [], "aggressive": ["R2"]},
    "C2": {"exact": ["R2"], "conservative": ["R1"], "aggressive": ["R3"]},
    "C3": {"exact": ["R3"], "conservative": ["R2"], "aggressive": ["R4"]},
    "C4": {"exact": ["R4"], "conservative": ["R3"], "aggressive": ["R5"]},
    "C5": {"exact": ["R5"], "conservative": ["R4"], "aggressive": []},
}


def calculate_product_risk(return_rates: list[Decimal]) -> tuple[Decimal | None, Decimal | None, str | None]:
    """Calculate expected return, stddev, and risk level from historical return rates.

    Returns (expected_return, stddev, risk_level). All None if less than 2 data points.
    """
    n = len(return_rates)
    if n < 2:
        if n == 1:
            return return_rates[0], Decimal("0"), "R1"
        return None, None, None

    mean = sum(return_rates) / n
    variance = sum((r - mean) ** 2 for r in return_rates) / (n - 1)
    stddev = Decimal(str(math.sqrt(float(variance))))

    risk_level = "R5"
    for threshold, level in RISK_LEVEL_THRESHOLDS:
        if stddev < threshold:
            risk_level = level
            break

    return round(mean, 4), round(stddev, 4), risk_level


def calculate_risk_preference(total_score: int, max_possible_score: int) -> tuple[Decimal, str, str, str]:
    """Calculate risk preference from questionnaire score.

    Returns (normalized_score, preference_code, label, description).
    """
    normalized = Decimal(str(total_score / max_possible_score * 100))
    normalized = round(normalized, 2)

    preference = "C5"
    for threshold, code, _label in PREFERENCE_THRESHOLDS:
        if float(normalized) < threshold:
            preference = code
            break

    label = PREFERENCE_LABELS[preference]
    description = PREFERENCE_DESCRIPTIONS[preference]
    return normalized, preference, label, description
