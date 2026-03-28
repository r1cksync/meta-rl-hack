"""Buggy v2.3.2 of payments-api — NUMERIC(12,2) instead of NUMERIC(12,4).

This file demonstrates the bug used in Task 3 (hard difficulty).
The total_amount column uses 2 decimal places instead of 4, causing
silent truncation of order totals.
"""

from __future__ import annotations

from decimal import Decimal


def calculate_total_buggy(items: list[dict]) -> float:
    """Buggy calculation: truncates to 2 decimal places instead of 4."""
    total = sum(Decimal(str(item["unit_price"])) * item["quantity"] for item in items)
    # BUG: NUMERIC(12,2) causes truncation
    return float(total.quantize(Decimal("0.01")))  # Should be Decimal("0.0001")
