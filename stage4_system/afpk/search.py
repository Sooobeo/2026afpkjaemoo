"""Bounded finite-grid search, with no unjustified monotonicity assumption."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from .engine import simulate
from .constraints import evaluate


def find_loan(case, scenario, policy, events=None, lower=0, upper=75000,
              step=100, max_evaluations=1000):
    lower, upper, step = (Decimal(str(x)) for x in (lower, upper, step))
    if (not all(x.is_finite() for x in (lower, upper, step)) or lower < 0
            or upper < lower or step <= 0 or not isinstance(max_evaluations, int)
            or max_evaluations < 1):
        raise ValueError("탐색 범위·단위·최대 횟수를 확인하세요.")
    if scenario.get("purchase_year") is None:
        raise ValueError("전세 유지안에는 대출 역산을 적용하지 않습니다.")
    if (scenario.get("approval_status") == "evidence_verified"
            and scenario.get("approval_evidence_ref")
            and scenario.get("approved_limit") is not None):
        upper = min(upper, Decimal(str(scenario["approved_limit"])))
    metadata = {"lower": float(lower), "upper": float(upper), "resolution": float(step),
                "scope": "지정한 유한 후보 격자, 연속 범위의 최적값을 뜻하지 않음",
                "evaluations": 0, "loan": None, "approval_status": scenario.get("approval_status", "UNKNOWN")}
    candidate = lower
    while candidate <= upper:
        if metadata["evaluations"] >= max_evaluations:
            return {**metadata, "status": "SEARCH_INCONCLUSIVE",
                    "reason": "검사 예산 소진. 미검사 구간에 해가 있을 수 있음"}
        trial = deepcopy(scenario)
        trial["loan"] = float(candidate)
        result = simulate(case, trial, policy, events)
        metadata["evaluations"] += 1
        if metadata["evaluations"] == 1:
            contract = next((r for r in result.get("events", [])
                             if (r.get("event_id") == "housing_contract"
                                 or "계약금" in str(r.get("event", "")))
                             and r.get("date", "") < scenario["close_date"]), None)
            if contract and (contract["cash_after"] < -1e-7 or contract["free"] < -1e-7):
                return {**metadata, "status": "CONTRACT_BLOCKED",
                        "reason": "잔금일 이전 계약금 보호자금 부족은 미래 주담대 증액으로 해결할 수 없음",
                        "first_breach_at": contract["date"], "amount": -min(contract["free"], 0)}
        checks = evaluate(case, trial, result, policy)
        numeric = [r for r in checks if r["rule_id"] in
                   {"CASH_NONNEGATIVE", "PROTECTED_FUNDS", "RETIREMENT_SAVING"}
                   or (r["rule_id"] == "REPAYMENT_LIMIT" and r["status"] != "UNKNOWN")]
        # The search is for the numeric amount. Approval and missing evidence
        # are returned separately and can never be fixed by increasing a loan.
        if all(r["status"] == "PASS" for r in numeric):
            return {**metadata, "status": "FOUND", "loan": float(candidate),
                    "reason": "오름차순으로 검사한 지정 격자에서 첫 수치 통과액. 은행 승인 아님",
                    "constraints": checks}
        candidate += step
    return {**metadata, "status": "NO_FEASIBLE_LOAN",
            "reason": "명시한 격자 후보 전체에서 수치 통과액 없음. 다른 단위·범위로 일반화하지 않음"}
