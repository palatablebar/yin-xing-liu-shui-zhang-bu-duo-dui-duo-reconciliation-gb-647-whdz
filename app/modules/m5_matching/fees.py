"""手续费分摊：按组内银行签向金额比例分摊，尾差用最大余额法分到分。

返回的每一分钱都能加起来回到总额，不依赖浮点，也不会因输入顺序不同而变。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def allocate(total: Decimal, weights: list[Decimal], quantum: Decimal,
             tie_keys: list[str] | None = None) -> list[Decimal]:
    if not weights:
        return []
    cents_total = int((total / quantum).to_integral_value(rounding=ROUND_HALF_UP))
    safe_weights = [max(weight, Decimal("0")) for weight in weights]
    weight_sum = sum(safe_weights, Decimal("0"))
    if weight_sum <= 0:
        safe_weights = [Decimal("1")] * len(weights)
        weight_sum = Decimal(len(weights))
    raw = [Decimal(cents_total) * weight / weight_sum for weight in safe_weights]
    floors = [int(value) for value in raw]
    remainder = cents_total - sum(floors)
    keys = tie_keys or [str(index) for index in range(len(weights))]
    order = sorted(
        range(len(weights)),
        key=lambda index: (-(raw[index] - floors[index]), keys[index]),
    )
    cents = floors[:]
    for index in order[: max(remainder, 0)]:
        cents[index] += 1
    return [(Decimal(value) * quantum).quantize(quantum) for value in cents]
