"""Separate financial failures, missing evidence, and unassessed goals."""
from __future__ import annotations

import calendar

EPSILON = 0.0000001


def point_date(row):
    if row.get("date"):
        return str(row["date"])
    year, month = map(int, row["month"].split("-"))
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def points(result):
    data = []
    # Engine timeline includes individual receipts/payments. Primary events can
    # aggregate same-day closing flows, so include them as well, harmlessly.
    for row in result.get("rows", []):
        data.append({**row, "date": point_date(row), "kind": "monthend",
                     "cash_value": row["cash"], "free_value": row["free"]})
    timeline = result.get("event_rows")
    if timeline is None:
        timeline = [r for r in result.get("timeline", []) if r.get("point_type") != "monthend"]
    seen = set()
    for row in timeline + result.get("events", []):
        marker = (row.get("event_id"), point_date(row), row.get("sequence", 999))
        if marker in seen:
            continue
        seen.add(marker)
        data.append({**row, "date": point_date(row), "kind": "event",
                     "cash_value": row.get("cash_after", row.get("cash", 0)),
                     "free_value": row.get("free", 0)})
    for row in result.get("timeline", []):
        if row.get("point_type") == "opening":
            data.append({**row, "date": point_date(row), "kind": "opening",
                         "cash_value": row.get("cash_after", row.get("cash", 0)),
                         "free_value": row["free"]})
    return sorted(data, key=lambda row: (row["date"], row.get("sequence", 999)))


def evaluate(case, scenario, result, policy):
    period = {"start": case["as_of_date"], "end": scenario["analysis_end"]}
    checks = []

    def add(rule, label, status, cause, *, blocking=True, breach=None, amount=None,
            unit="만원", evidence=None):
        checks.append({"rule_id": rule, "label": label, "status": status,
                       "blocking": blocking, "first_breach_at": breach,
                       "amount": amount, "unit": unit, "cause": cause,
                       "evidence_refs": evidence or [], "evaluated_period": period})

    all_points = points(result)
    for rule, label, key in (("CASH_NONNEGATIVE", "총현금 지급 가능", "cash_value"),
                             ("PROTECTED_FUNDS", "비상·목적자금 유지", "free_value")):
        first = next((p for p in all_points if p[key] < -EPSILON), None)
        add(rule, label, "FAIL" if first else "PASS",
            (f"{first['date']} {first.get('event', '월말')} 기준 부족" if first
             else "표시된 기간의 월말·등록 사건에서 기준 충족"),
            breach=first["date"] if first else None,
            amount=-first[key] if first else 0)

    transaction_points = [p for p in all_points if p["kind"] == "event"]
    first = next((p for p in transaction_points if p["cash_value"] < -EPSILON), None)
    add("TRANSACTION_LIQUIDITY", "사건별 지급일 유동성", "FAIL" if first else "PASS",
        "지급일에 현금 자체가 부족" if first else "등록된 사건별 현금 지급 가능",
        breach=first["date"] if first else None,
        amount=-first["cash_value"] if first else 0)

    target = float(case["budget"]["retirement"])
    first = next((r for r in result["rows"] if r["retirement"] < target - EPSILON), None)
    add("RETIREMENT_SAVING", "월 은퇴저축 유지", "FAIL" if first else "PASS",
        f"월 {target:g}만 원 납입 여부. 노후 충분성과 별개",
        breach=point_date(first) if first else None,
        amount=target-first["retirement"] if first else 0)
    first = next((r for r in result["rows"] if r["monthly_surplus"] < -EPSILON), None)
    add("MONTHLY_SURPLUS", "월수지 적자", "FAIL" if first else "PASS",
        "일시 적자는 준비현금으로 충당할 수 있으므로 단독 탈락 조건이 아님",
        blocking=False, breach=point_date(first) if first else None,
        amount=-first["monthly_surplus"] if first else 0)

    buying = scenario.get("purchase_year") is not None
    if buying:
        limit = scenario.get("approved_limit")
        approval = scenario.get("approval_status")
        proof = scenario.get("approval_evidence_ref")
        if approval != "evidence_verified" or limit is None or not proof:
            add("LOAN_APPROVAL", "실제 대출 승인", "UNKNOWN",
                "승인액·확인 증빙이 없음. 계산상 대출은 은행 승인액이 아님")
        else:
            gap = float(result["loan"])-float(limit)
            add("LOAN_APPROVAL", "실제 대출 승인", "FAIL" if gap > EPSILON else "PASS",
                "확인된 승인한도와 계산 대출액 비교", amount=max(0, gap), evidence=[proof])
    else:
        add("LOAN_APPROVAL", "실제 대출 승인", "NOT_EVALUATED", "주택 취득 없는 비교안")

    agreed = case.get("repayment_constraint", {})
    ceiling = agreed.get("max_monthly_payment")
    ratio = agreed.get("max_payment_ratio")
    supported_debts = {"mortgage", "rent_interest"}
    debts = agreed.get("included_debts", ["mortgage"])
    incomes = agreed.get("income_components", ["husband", "wife"])
    if ((ceiling is None and ratio is None) or not agreed.get("agreement_ref")
            or not set(debts) <= supported_debts
            or not set(incomes) <= {"husband", "wife", "cash_support"}):
        add("REPAYMENT_LIMIT", "고객 합의 상환부담", "UNKNOWN",
            "합의한 한도·분자·분모·근거가 없거나 지원하지 않는 부채. 규제 DSR와 별개")
    else:
        first_breach = None
        unknown_income = False
        for row in result["rows"]:
            if agreed.get("effective_from") and row["month"] < agreed["effective_from"][:7]:
                continue
            if agreed.get("effective_to") and row["month"] > agreed["effective_to"][:7]:
                continue
            owned = buying and row["month"] >= scenario["close_date"][:7]
            pay = sum(row["mortgage"] if key == "mortgage" else
                      (0 if owned else float(case["budget"]["rent_interest"])) for key in debts)
            income = sum(float(row[key]) for key in incomes)
            if ratio is not None and income <= 0:
                unknown_income = True
                continue
            if ((ceiling is not None and pay > float(ceiling)+EPSILON)
                    or (ratio is not None and pay/income > float(ratio)+EPSILON)):
                first_breach = row
                break
        add("REPAYMENT_LIMIT", "고객 합의 상환부담",
            "FAIL" if first_breach else "UNKNOWN" if unknown_income else "PASS",
            "합의한 부채·정기소득 범위의 월한도/비율 검사. 규제 DSR 아님",
            breach=point_date(first_breach) if first_breach else None,
            unit="비율·만원", evidence=[agreed["agreement_ref"]])

    # A historical policy snapshot is deliberately not a current-law approval.
    confirmation = case.get("confirmations", {})
    current = confirmation.get("policy", {})
    add("POLICY_VALIDITY", "적용일 기준 제도 확인",
        "PASS" if current.get("status") == "evidence_verified" and current.get("evidence_ref")
        else "UNKNOWN", "과거 설정 재현과 실행일의 제도·지원 적격성은 별도 확인",
        evidence=[current["evidence_ref"]] if current.get("evidence_ref") else [])
    if buying:
        required = ("lease", "parent_transfer", "property")
        missing = [key for key in required if confirmation.get(key, {}).get("status") != "evidence_verified"
                   or not confirmation.get(key, {}).get("evidence_ref")]
        add("EXECUTION_PREREQUISITES", "매물·임대차·송금 확인",
            "UNKNOWN" if missing else "PASS",
            "추가 확인: " + ", ".join(missing) if missing else "등록된 증빙 확인 상태 충족")
    else:
        add("EXECUTION_PREREQUISITES", "매물·임대차·송금 확인", "NOT_EVALUATED", "전세 유지 비교안")
    add("RETIREMENT_SUFFICIENCY", "노후자금 충분성", "NOT_EVALUATED",
        "연금 예상액·수급일·목표생활비·장기 인출경로 미확정", blocking=False)
    if scenario.get("mode") == "working_plan":
        add("LIFE_STAGE_BUDGET", "연령별 장기 예산 완결성", "UNKNOWN",
            "명시한 생애주기 일정만 계산함. 모든 지원·교육·돌봄·수선이 완비됐다는 증빙은 별도 필요")
    return checks


def summarize(checks):
    blocking = [r for r in checks if r["blocking"]]
    if any(r["status"] == "FAIL" for r in blocking):
        return "REJECTED"
    if any(r["status"] in ("UNKNOWN", "NOT_EVALUATED") for r in blocking):
        return "REVIEW_REQUIRED"
    # A numeric report never chooses or executes a transaction on its own.
    return "READY_FOR_HUMAN_REVIEW"
