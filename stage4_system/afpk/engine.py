"""Deterministic cash-flow engine for the AFPK virtual-household case.

Amounts are in the input's declared unit (the distributed case uses 만원).
Historical replay retains the original monthly assumptions; the complete
timeline, rather than just month ends, is used for liquidity extrema.
"""
from __future__ import annotations

from calendar import monthrange
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from .finance import acquisition_costs, pmt


ZERO = Decimal("0")


def D(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("금액과 비율은 유한한 숫자여야 합니다.")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("금액과 비율은 유한한 숫자여야 합니다.") from exc
    if not result.is_finite():
        raise ValueError("금액과 비율은 유한한 숫자여야 합니다.")
    return result


def month_number(month: str) -> int:
    parsed = date.fromisoformat(month + "-01")
    return parsed.year * 12 + parsed.month - 1


def month_label(number: int) -> str:
    return f"{number // 12:04d}-{number % 12 + 1:02d}"


def add_months(month: str, count: int) -> str:
    return month_label(month_number(month) + count)


def month_end(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{month}-{monthrange(y, m)[1]:02d}"


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json(item) for item in value]
    return value


def reconcile_events(records: list[dict], as_of_date: str) -> tuple[list[dict], list[str]]:
    """Return effective supplementary transactions without double counting.

    Confirmed actuals reduce the corresponding planned transaction even when
    the actual is already included in the opening balance. Unverified actuals
    do not change either the balance or the plan. Original records are never
    modified. Reconciliation of structural built-in housing transactions is
    intentionally rejected: update the scenario's dates/terms for those.
    """
    cutoff = date.fromisoformat(as_of_date)
    events = deepcopy(records or [])
    warnings: list[str] = []
    by_id: dict[str, dict] = {}
    allowed_types = {
        "income", "expense", "retirement", "settlement_payment", "stock_sale",
        "rental_return", "loan_draw", "contract", "closing",
    }
    for item in events:
        event_id = str(item.get("event_id", "")).strip()
        if not event_id or event_id in by_id:
            raise ValueError(f"빈 사건 ID 또는 중복 사건 ID: {event_id!r}")
        item["event_id"] = event_id
        by_id[event_id] = item
        date.fromisoformat(item["date"])
        item["amount"] = D(item["amount"])
        if item["amount"] < 0:
            raise ValueError(f"사건 금액은 0 이상이어야 합니다: {event_id}")
        if item.get("type") not in allowed_types:
            raise ValueError(f"지원하지 않는 사건 유형: {item.get('type')}")
        item.setdefault("record_kind", "planned")
        if item["record_kind"] not in {"planned", "actual"}:
            raise ValueError(f"계획/실제 구분 오류: {event_id}")
        item["sequence"] = int(item.get("sequence", 50))

    executed: dict[str, Decimal] = {}
    actuals = []
    for item in events:
        if item["record_kind"] != "actual":
            continue
        if item.get("verification_status") != "evidence_verified":
            warnings.append(f"미확인 실제 사건을 반영하지 않음: {item['event_id']}")
            continue
        target = item.get("planned_event_id")
        if target:
            if target not in by_id or by_id[target]["record_kind"] != "planned":
                raise ValueError(f"원계획 사건을 찾을 수 없음: {target}")
            if by_id[target]["type"] != item["type"]:
                raise ValueError(f"계획/실제 사건 유형이 다름: {target}")
            executed[target] = executed.get(target, ZERO) + item["amount"]
        if date.fromisoformat(item["date"]) > cutoff:
            actuals.append(item)
        else:
            warnings.append(f"기초잔액에 포함된 실제 사건을 재가산하지 않음: {item['event_id']}")

    effective = actuals
    for item in events:
        if item["record_kind"] != "planned":
            continue
        remainder = max(ZERO, item["amount"] - executed.get(item["event_id"], ZERO))
        if remainder and date.fromisoformat(item["date"]) > cutoff:
            item["amount"] = remainder
            effective.append(item)
        elif remainder:
            warnings.append(f"기준일 이전의 미집행 계획은 자동 이월하지 않음: {item['event_id']}")
    effective.sort(key=lambda row: (row["date"], row["sequence"], row["event_id"]))
    return effective, warnings


def simulate(case: dict, scenario: dict, policy: dict, events: list[dict] | None = None) -> dict:
    """Simulate one input snapshot without mutating inputs or writing files."""
    with localcontext() as context:
        context.prec = 36
        return _json(_simulate(deepcopy(case), deepcopy(scenario), deepcopy(policy), events))


def _simulate(case: dict, scenario: dict, policy: dict, events: list[dict] | None) -> dict:
    initial = case["initial"]
    income = case["income"]
    budget = case["budget"]
    dates = case["dates"]
    assumptions = case["assumptions"]
    overrides = scenario.get("overrides") or {}
    mode = scenario.get("mode", "historical_replay")
    if mode not in {"historical_replay", "working_plan"}:
        raise ValueError("지원하지 않는 계산 모드입니다.")
    if case.get("amount_unit") != "만원" or case.get("currency") != "KRW":
        raise ValueError("계산 엔진은 KRW·만원 입력만 지원합니다. 입력 단위를 변환하십시오.")

    start = case["start_month"]
    end_month = scenario.get("analysis_end", scenario.get("comparison_end", "2031-06"))
    if month_number(end_month) < month_number(start):
        raise ValueError("분석 종료월이 시작월보다 빠릅니다.")
    base_month = case["price_base_month"]
    inflation = D(assumptions.get("inflation", 0))
    if inflation <= -1:
        raise ValueError("물가 가정은 -100%보다 커야 합니다.")

    def F(month: str) -> Decimal:
        exponent = D(month_number(month) - month_number(base_month)) / 12
        return (1 + inflation) ** exponent

    purchase_year = scenario.get("purchase_year")
    buying = purchase_year is not None
    close_date = scenario.get("close_date") if buying else None
    contract_date = scenario.get("contract_date") if buying else None
    if buying:
        close_date = close_date or f"{purchase_year}-06-15"
        contract_date = contract_date or f"{purchase_year}-03-15"
        date.fromisoformat(close_date)
        date.fromisoformat(contract_date)
        if contract_date >= close_date:
            raise ValueError("계약일은 잔금일보다 앞서야 합니다.")
        if contract_date <= case["as_of_date"]:
            raise ValueError("이미 실행된 주택계약은 새 가정 거래로 소급 계산할 수 없습니다.")
    close_month = close_date[:7] if buying else None
    contract_month = contract_date[:7] if buying else None
    sale_month = add_months(contract_month, -1) if buying else None
    price = D(scenario.get("price", 0)) if buying else ZERO
    loan = D(scenario.get("loan", 0)) if buying else ZERO
    rate = D(scenario.get("rate", "0.05"))
    term = int(scenario.get("term_months", 360))
    if price < 0 or loan < 0 or (buying and price <= 0):
        raise ValueError("주택가격·대출원금 입력이 올바르지 않습니다.")
    payment = D(pmt(loan, rate, term)) if buying else ZERO
    cost_result = acquisition_costs(price, policy) if buying else {
        "status": "PASS", "total": ZERO, "components": {}, "limitations": []}
    if cost_result.get("total") is None:
        raise ValueError("취득비용을 계산할 수 없습니다: " + "; ".join(cost_result.get("limitations", [])))
    closing_cost = D(cost_result["total"])
    limitations = list(cost_result.get("limitations", []))
    limitations.extend([
        "가상 고객 설정과 분석 가정에 따른 계산이며 은행 승인·실제 송금·임대차 합의를 확인한 결과가 아닙니다.",
        "월별 반복 소득·지출은 월말 합산 근사입니다. 실제 급여·청구일 확인 전 월중 지급가능성을 확정하지 않습니다.",
        "고정구조 연장에는 실제 연령별 교육·돌봄·지원종료·수선·세금 변화가 자동 포함되지 않습니다.",
        "월 은퇴저축 유지 여부와 장기 노후자금 충분성은 별도입니다.",
    ])
    if mode == "working_plan":
        limitations.append("working_plan도 명시된 일정·확인자료만 반영합니다. 비어 있는 미래 자료를 추정해 확정하지 않습니다.")

    delay = int(overrides.get("delay_months", 0))
    deposit_delay = int(overrides.get("deposit_delay_months", 0))
    if delay < 0 or deposit_delay < 0:
        raise ValueError("지연 개월 수는 0 이상이어야 합니다.")
    care_multiplier = D(overrides.get("care_multiplier", 1))
    stock_loss = D(overrides.get("stock_loss", 0))
    if care_multiplier < 0 or not ZERO <= stock_loss <= 1:
        raise ValueError("돌봄 배수·주식 손실률이 유효 범위를 벗어났습니다.")
    renew_extra = D(overrides.get("renew_extra", 0))
    if renew_extra < 0:
        raise ValueError("추가 보증금은 0 이상이어야 합니다.")
    support_amount = overrides.get("parent_support_amount")
    support_amount = D(assumptions.get("parent_support", 0) if support_amount is None else support_amount)
    support_month = overrides.get("parent_support_month") or (add_months(close_month, -1) if buying else None)
    if buying and overrides.get("parents_delay_months_after_close") is not None:
        support_month = add_months(close_month, int(overrides["parents_delay_months_after_close"]))
    leave_end = add_months(dates["leave_end"], delay)
    care_start = overrides.get("care_start")
    care_early_end = add_months(dates["nursery_start"], -1)
    birth_end = max((item["month"] for item in case.get("birth_expenses", [])), default=dates["birth_month"])

    birth_gross: dict[str, Decimal] = {}
    for item in case.get("birth_expenses", []):
        month = item["month"]
        birth_gross[month] = birth_gross.get(month, ZERO) + D(item["amount"]) * F(month)
    voucher_use: dict[str, Decimal] = {}
    for voucher in case.get("vouchers", []):
        remaining = D(voucher["amount"])
        for month in sorted(voucher.get("eligible_months", [])):
            available_cost = max(ZERO, birth_gross.get(month, ZERO) - voucher_use.get(month, ZERO))
            if voucher.get("eligible_base_amount") is not None:
                # Prenatal assistance cannot fund a nursery deposit or baby
                # equipment that happens to be purchased in the same month.
                eligible_cap = D(voucher["eligible_base_amount"]) * F(month)
                available_cost = min(available_cost, max(ZERO, eligible_cap - voucher_use.get(month, ZERO)))
            use = min(remaining, available_cost)
            voucher_use[month] = voucher_use.get(month, ZERO) + use
            remaining -= use
            if not remaining:
                break
        if remaining:
            limitations.append(f"미사용 바우처 {voucher.get('id', '')}: {remaining}만 원. 현금으로 가산하지 않음.")

    supplementary, event_warnings = reconcile_events(events or [], case["as_of_date"])
    limitations.extend(event_warnings)
    for item in supplementary:
        if item["date"][:7] < start or item["date"][:7] > end_month:
            limitations.append(f"분석기간 밖 보조 사건을 장부에 반영하지 않음: {item['event_id']}")

    cash = D(initial["cash"])
    shares = D(initial["stock"])
    pension = D(initial["pension"])
    rental_equity = D(initial["rental_deposit"]) - D(initial["rental_debt"])
    debt = ZERO
    reserve = D(budget["emergency_initial"])
    settlement = ZERO
    extra_deposit = ZERO
    prepaid = ZERO
    property_value = ZERO
    rows: list[dict] = []
    primary_events: list[dict] = []
    timeline: list[dict] = []
    effective_records: list[dict] = []
    opening_month = case["as_of_date"][:7]
    opening_future = sum((amount - voucher_use.get(m, ZERO)
                          for m, amount in birth_gross.items() if m > opening_month), ZERO)
    opening_birth_buffer = (D(budget["birth_buffer"]) * F(opening_month)
                            if opening_month <= birth_end else ZERO)
    opening_earmark = opening_future + opening_birth_buffer
    timeline.append({
        "event_id": "opening_balance", "date": case["as_of_date"], "month": opening_month,
        "sequence": -1, "event": "기초잔액 스냅샷", "point_type": "opening",
        "cash": cash, "cash_after": cash, "reserve": reserve,
        "future_birth_cash": opening_future, "birth_buffer": opening_birth_buffer,
        "settlement_balance": settlement, "trade_buffer": ZERO,
        "earmark": opening_earmark, "free": cash - reserve - opening_earmark,
    })
    rent_interest = D(budget["rent_interest"])
    projected_end = month_number(end_month)
    if projected_end - month_number(start) > 1200:
        raise ValueError("분석기간은 최대 1,200개월입니다.")

    for month_idx in range(month_number(start), projected_end + 1):
        month = month_label(month_idx)
        opening = cash
        transaction = ZERO
        receipt = ZERO
        custom_operating = ZERO
        custom_retirement = ZERO
        owned = bool(buying and month >= close_month)
        adult = D(budget["adult_before"] if month < dates["birth_month"] else budget["adult_after"])
        child = ZERO if month < dates["birth_month"] else D(budget["child"])
        prenatal = D(budget["prenatal_insurance"]) if budget["prenatal_start"] <= month < dates["birth_month"] else ZERO
        care = (D(budget["care_early"]) if dates["leave_start"] <= month <= care_early_end else
                D(budget["care_late"]) if month >= dates["nursery_start"] else ZERO)
        if care_start is None or month >= care_start:
            care *= care_multiplier
        nursery = D(budget["nursery"]) if month >= dates["nursery_start"] else ZERO
        husband = D(income["husband"])
        leave = dates["leave_start"] <= month <= leave_end
        if leave:
            leave_n = month_idx - month_number(dates["leave_start"]) + 1
            tiers = income["leave_tiers"]
            wife = D(tiers[0] if leave_n <= 3 else tiers[1] if leave_n <= 6 else tiers[2] if leave_n <= 12 else 0)
        else:
            wife = D(income["wife"])
        cash_support = ZERO
        for scheduled in case.get("support_schedule", []):
            if scheduled["start"] <= month and (not scheduled.get("end") or month <= scheduled["end"]):
                cash_support += D(scheduled["amount"])
        for stage in case.get("life_stage_schedule", []):
            if stage["start"] <= month and (not stage.get("end") or month <= stage["end"]):
                adult = D(stage.get("adult", adult))
                child = D(stage.get("child", child))
                care = D(stage.get("care", care))
                nursery = D(stage.get("nursery", nursery))
                husband = D(stage.get("husband", husband))
                wife = D(stage.get("wife", wife))
                cash_support = D(stage.get("cash_support", cash_support))
        living = (adult - rent_interest + child + prenatal + care + nursery +
                  (D(budget["owned_maintenance"]) if owned else ZERO)) * F(month)
        living += ZERO if owned else rent_interest
        if owned and deposit_delay and month < add_months(close_month, deposit_delay):
            living += rent_interest
        installment_n = month_idx - month_number(close_month) + 1 if buying else 0
        mortgage = payment if owned and installment_n <= term else ZERO
        target = D(budget["emergency_later"] if month >= dates["nursery_start"] else budget["emergency_initial"]) * F(month)
        reserve = max(reserve, target, 6 * (living + mortgage) if owned else ZERO)

        def protected(at_end: bool = False) -> dict:
            future = sum((amount - voucher_use.get(m, ZERO) for m, amount in birth_gross.items()
                          if m > month or (not at_end and m == month)), ZERO)
            buffer = D(budget["birth_buffer"]) * F(month) if month < birth_end or (month == birth_end and not at_end) else ZERO
            trade_buffer = D(budget["trade_buffer"]) if owned else ZERO
            earmark = future + buffer + settlement + trade_buffer
            return {"reserve": reserve, "future_birth_cash": future, "birth_buffer": buffer,
                    "settlement_balance": settlement, "trade_buffer": trade_buffer,
                    "earmark": earmark, "free": cash - reserve - earmark}

        tasks = []

        def queue(event_id: str, event_date: str, sequence: int, event_type: str,
                  amount: Decimal, label: str, **extra: Any) -> None:
            tasks.append({"event_id": event_id, "date": event_date, "sequence": sequence,
                          "type": event_type, "amount": amount, "event": label,
                          "record_kind": "planned", "verification_status": "source_matched", **extra})

        if buying and month == sale_month:
            queue("builtin_stock_sale", month_end(month), 10, "builtin_stock_sale", shares * (1 - stock_loss), "주식 매각")
        if buying and month == support_month:
            queue("builtin_parent_support", month_end(month), 20, "income_asset", support_amount, "부모 지원금")
        if buying and month == contract_month:
            queue("builtin_housing_contract", contract_date, 20, "builtin_contract", price * D("0.1"), "계약금", primary=True)
        if buying and purchase_year > 2027 and month == "2028-06" and renew_extra:
            queue("builtin_deposit_renewal", "2028-06-01", 20, "builtin_renewal", renew_extra, "전세보증금 증액")
        if buying and month == close_month:
            queue("builtin_housing_closing", close_date, 30, "builtin_closing",
                  price * D("0.9") + closing_cost, "잔금과 부대비용 전액", primary=True)
        if buying and deposit_delay and month == add_months(close_month, deposit_delay):
            queue("builtin_rental_return", month_end(month), 20, "builtin_rental_return", rental_equity, "지연 보증금 순반환")
        for item in supplementary:
            if item["date"][:7] == month:
                if item["event_id"].startswith("builtin_"):
                    raise ValueError("보조 사건은 builtin_ 예약 ID를 사용할 수 없습니다.")
                tasks.append({**item, "event": item.get("reason") or item["type"], "supplementary": True})
        tasks.sort(key=lambda item: (item["date"], item["sequence"], item["event_id"]))

        for task in tasks:
            before = cash
            amount = D(task["amount"])
            kind = task["type"]
            inflow = ZERO
            if kind == "builtin_stock_sale":
                cash += amount
                receipt += amount
                shares = ZERO
            elif kind == "income_asset":
                cash += amount
                receipt += amount
            elif kind == "builtin_contract":
                cash -= amount
                transaction -= amount
                if mode == "working_plan":
                    prepaid += amount
            elif kind == "builtin_renewal":
                cash -= amount
                transaction -= amount
                extra_deposit += amount
                rental_equity += amount
            elif kind == "builtin_closing":
                returned = rental_equity if not deposit_delay else ZERO
                inflow = returned + loan
                cash += inflow - amount
                transaction += inflow - amount
                debt += loan
                property_value = price
                prepaid = ZERO
                if not deposit_delay:
                    rental_equity = ZERO
            elif kind == "builtin_rental_return":
                cash += rental_equity
                transaction += rental_equity
                amount = rental_equity
                rental_equity = ZERO
            elif kind == "income":
                cash += amount
                custom_operating += amount
            elif kind == "expense":
                cash -= amount
                custom_operating -= amount
            elif kind == "retirement":
                cash -= amount
                pension += amount
                custom_operating -= amount
                custom_retirement += amount
            elif kind == "settlement_payment":
                if amount > settlement:
                    raise ValueError(f"정산 유보잔액보다 큰 유보금 집행: {task['event_id']}")
                cash -= amount
                settlement -= amount
                custom_operating -= amount
            elif kind == "stock_sale":
                if amount > shares:
                    raise ValueError(f"보유 주식 장부금액보다 큰 보조 매각: {task['event_id']}")
                shares -= amount
                cash += amount
                receipt += amount
            elif kind == "rental_return":
                if amount > rental_equity:
                    raise ValueError(f"전세 순지분보다 큰 반환: {task['event_id']}")
                rental_equity -= amount
                cash += amount
                transaction += amount
            elif kind == "loan_draw":
                raise ValueError("보조 대출 실행은 상환조건이 없어 지원하지 않습니다. 시나리오 대출조건을 수정하십시오.")
            elif kind in {"contract", "closing"}:
                raise ValueError("주택 계약·잔금은 시나리오의 금액·날짜로 입력하십시오. 보조 사건에 중복 입력하지 마십시오.")
            else:
                raise ValueError(f"지원하지 않는 사건: {kind}")
            record = {"event_id": task["event_id"], "date": task["date"], "month": month,
                      "sequence": task["sequence"], "event": task["event"], "type": kind,
                      "record_kind": task["record_kind"], "verification_status": task.get("verification_status"),
                      "planned_event_id": task.get("planned_event_id"), "source_id": task.get("source_id"),
                      "cash_before": before, "amount": amount, "inflow": inflow,
                      "cash_after": cash, "cash": cash, "point_type": "event", **protected()}
            timeline.append(record)
            effective_records.append(record)
            if task.get("primary"):
                primary_events.append(record)

        contribution = D(income["leave_contribution"]) if leave else ZERO
        retention = D(income["settlement_retention"]) if leave else ZERO
        birth = birth_gross.get(month, ZERO)
        voucher = voucher_use.get(month, ZERO)
        retirement = D(budget["retirement"])
        extra_expense = ZERO
        for item in overrides.get("extra_expenses", []):
            first = item.get("start", item.get("month"))
            last = item.get("end") or first
            if first and first <= month <= last:
                extra_expense += D(item["amount"]) * (F(month) if item.get("inflate", False) else 1)
        total_income = husband + wife + cash_support
        if owned and mortgage:
            mortgage = min(mortgage, debt * (1 + rate / 12))
        net = total_income - living - contribution - retirement - (birth - voucher) - mortgage - extra_expense
        cash += net
        pension += retirement
        settlement += retention
        if owned and debt > 0:
            debt = max(ZERO, debt * (1 + rate / 12) - mortgage)
        ending_protection = protected(True)
        net_worth = cash + shares + pension + property_value + rental_equity + prepaid - debt
        full_net = net + custom_operating
        conservation_delta = cash - (opening + receipt + transaction + full_net)
        if abs(conservation_delta) > D("0.000000001"):
            raise ArithmeticError(f"현금 보존식 불일치: {month}: {conservation_delta}")
        row = {"month": month, "opening_cash": opening, "husband": husband, "wife": wife,
               "cash_support": cash_support, "income": total_income,
               "living": living, "birth_gross": birth, "voucher": voucher,
               "birth_cash": birth - voucher, "contribution": contribution,
               "settlement_retained": retention, "retirement": retirement + custom_retirement,
               "mortgage": mortgage, "extra_expense": extra_expense,
               "custom_operating_flow": custom_operating, "monthly_surplus": full_net,
               "asset_receipts": receipt, "transaction_flow": transaction,
               "cash": cash, **ending_protection, "mortgage_balance": debt,
               "pension": pension, "stock": shares, "rental_equity": rental_equity,
               "property_value": property_value, "prepaid_property": prepaid,
               "net_worth": net_worth, "conservation_delta": conservation_delta}
        rows.append(row)
        timeline.append({"date": month_end(month), "month": month, "sequence": 100000,
                         "event_id": f"monthend_{month}", "event": "월말 반복 수입·지출 합계",
                         "point_type": "monthend", "cash": cash, "cash_after": cash,
                         "free": row["free"], "reserve": reserve, "earmark": row["earmark"]})

    timeline.sort(key=lambda item: (item["date"], item["sequence"], item["event_id"]))
    minimum_cash = min(timeline, key=lambda item: item["cash"])
    minimum_free = min(timeline, key=lambda item: item["free"])
    monthend_cash = min(rows, key=lambda item: item["cash"])
    monthend_free = min(rows, key=lambda item: item["free"])
    first_cash = next((point for point in timeline if point["cash"] < -D("0.0000001")), None)
    first_free = next((point for point in timeline if point["free"] < -D("0.0000001")), None)
    post_rows = [row for row in rows if not buying or row["month"] >= close_month]
    comparison = next((row for row in rows if row["month"] == scenario.get("comparison_end", "2031-06")), None)
    first_monthly_deficit = next((row for row in rows if row["monthly_surplus"] < -D("0.0000001")), None)
    post_first_free = next((row for row in post_rows if row["free"] < -D("0.0000001")), None)
    if buying and any(point["cash"] < 0 or point["free"] < 0 for point in primary_events):
        limitations.append("일부 거래일 제약을 위반합니다. 그 이후 장부는 거래가 가상으로 진행된 반사실적 계산입니다.")
    if mode == "historical_replay":
        limitations.append("historical_replay 순자산은 원모델과 동일하게 계약금 선급자산을 취득 전 별도 계상하지 않습니다.")
    return {
        "scenario_id": scenario.get("id", "scenario"), "scenario_name": scenario.get("name", scenario.get("id", "scenario")),
        "mode": mode, "year": purchase_year, "loan": loan, "price": price,
        "payment": payment, "rate": rate, "term_months": term,
        "start_month": start, "analysis_end": end_month,
        "comparison_end": scenario.get("comparison_end", "2031-06"),
        "contract_date": contract_date, "close_date": close_date,
        "closing_cost": closing_cost, "cost_result": cost_result,
        "rows": rows, "monthly_rows": rows, "events": primary_events,
        "event_rows": effective_records, "timeline": timeline,
        "min_cash": minimum_cash, "min_free": minimum_free, "end": rows[-1],
        "limitations": list(dict.fromkeys(limitations)),
        "metrics": {"monthend_min_cash": monthend_cash, "monthend_min_free": monthend_free,
                    "first_cash_breach": first_cash, "first_protected_breach": first_free,
                    "first_monthly_deficit": first_monthly_deficit,
                    "post_purchase_first_monthend_protected_breach": post_first_free,
                    "comparison_row": comparison,
                    "birth_total": sum((D(item["amount"]) for item in case.get("birth_expenses", [])), ZERO),
                    "birth_inflated_total": sum((row["birth_gross"] for row in rows), ZERO),
                    "voucher_total": sum((row["voucher"] for row in rows), ZERO),
                    "cash_support_total": sum((row["cash_support"] for row in rows), ZERO),
                    "leave_contribution_total": sum((row["contribution"] for row in rows), ZERO),
                    "settlement_retained_total": sum((row["settlement_retained"] for row in rows), ZERO),
                    "all_events_evaluated": True,
                    "recurring_flow_date_precision": "month_end_approximation",
                    "cost_status": cost_result.get("status", "UNKNOWN")},
    }
