"""Deterministic financial arithmetic in KRW ten-thousand units.

These functions calculate the supplied policy snapshot.  A computed amount is
not an eligibility, tax, or lending approval.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a finite number")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be a finite number")
    return result


def pmt(principal: Any, annual_rate: Any, term_months: int = 360) -> Decimal:
    """Monthly equal principal-and-interest payment; no intermediate rounding."""
    principal = _decimal(principal, "principal")
    annual_rate = _decimal(annual_rate, "annual_rate")
    if principal < 0 or annual_rate < 0 or annual_rate > 1:
        raise ValueError("principal must be nonnegative; annual_rate must be in [0, 1]")
    if isinstance(term_months, bool) or not isinstance(term_months, int) or term_months <= 0:
        raise ValueError("term_months must be a positive integer")
    with localcontext() as context:
        context.prec = 40
        if annual_rate == 0:
            return +(principal / Decimal(term_months))
        monthly_rate = annual_rate / Decimal(12)
        return +(principal * monthly_rate / (1 - (1 + monthly_rate) ** (-term_months)))


def acquisition_costs(price: Any, policy: dict) -> dict:
    """Calculate costs only inside an explicitly supplied ordinary-tax scope.

    ``PASS`` means arithmetic within the stated assumptions.  Unspecified or
    unsupported tax/property/brokerage conditions return ``UNKNOWN`` and no
    total, rather than silently substituting zero.
    """
    price = _decimal(price, "price")
    if price <= 0:
        raise ValueError("price must be positive")
    cost_policy = policy.get("acquisition", policy)
    limitations = [
        "가상 사례의 일반세율·면적·중과 없음·감면 전 가정에 따른 계산입니다.",
        "실제 취득일의 세법·주택 수·면적·견적·과세 여부를 별도 확인해야 합니다.",
    ]
    required_scope = ("ordinary_tax", "area_le85", "no_surcharge", "no_relief")
    if any(cost_policy.get(key) is not True for key in required_scope):
        return {"status": "UNKNOWN", "total": None, "components": {},
                "limitations": limitations + ["일반세율 적용 범위와 면적·중과·감면 조건이 확인되지 않았습니다."]}

    with localcontext() as context:
        context.prec = 40
        if price <= Decimal(60000):
            tax_rate = Decimal("0.01")
        elif price <= Decimal(90000):
            tax_rate = (price / Decimal(10000) * Decimal(2) / Decimal(3) - Decimal(3)) / Decimal(100)
        else:
            tax_rate = Decimal("0.03")

        brokerage_rate = None
        if cost_policy.get("brokerage_quote") is not None:
            brokerage = _decimal(cost_policy["brokerage_quote"], "brokerage_quote")
            if brokerage < 0:
                raise ValueError("brokerage_quote must be nonnegative")
        else:
            for band in cost_policy.get("brokerage_bands", []):
                lower = _decimal(band["min"], "brokerage minimum")
                upper = None if band.get("max") is None else _decimal(band["max"], "brokerage maximum")
                if price >= lower and (upper is None or price < upper):
                    brokerage_rate = _decimal(band["rate"], "brokerage rate")
                    break
            if brokerage_rate is None:
                return {"status": "UNKNOWN", "total": None,
                        "components": {"acquisition_tax_rate": +tax_rate},
                        "limitations": limitations + ["입력한 가격에 해당하는 중개보수 구간 또는 견적이 없습니다."]}
            if brokerage_rate < 0 or brokerage_rate > 1:
                raise ValueError("brokerage rate must be in [0, 1]")
            brokerage = price * brokerage_rate

        education_ratio = _decimal(cost_policy.get("education_ratio", "0.1"), "education_ratio")
        vat_rate = _decimal(cost_policy.get("brokerage_vat_rate", "0.1"), "brokerage_vat_rate")
        other = _decimal(cost_policy.get("other_budget", 900), "other_budget")
        if education_ratio < 0 or vat_rate < 0 or other < 0:
            raise ValueError("cost components must be nonnegative")
        acquisition_tax = price * tax_rate
        education_tax = acquisition_tax * education_ratio
        brokerage_vat = brokerage * vat_rate
        components = {
            "acquisition_tax_rate": +tax_rate,
            "acquisition_tax": +acquisition_tax,
            "education_tax": +education_tax,
            "brokerage": +brokerage,
            "brokerage_vat": +brokerage_vat,
            "other_budget": +other,
        }
        total = acquisition_tax + education_tax + brokerage + brokerage_vat + other
        limitations.append("세율·세액의 실제 신고 반올림은 미적용이며, 재현용 Decimal 산식을 사용합니다.")
        return {"status": "PASS", "total": +total, "components": components,
                "limitations": limitations}
