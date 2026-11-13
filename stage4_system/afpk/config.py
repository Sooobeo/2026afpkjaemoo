"""Input loading, validation, and stable serialization for the stage-4 tool."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def D(value: Any) -> Decimal:
    """Read a finite decimal without importing a binary float approximation."""
    if isinstance(value, bool) or value is None:
        raise ValueError("금액은 유한한 숫자여야 합니다.")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("금액은 유한한 숫자여야 합니다.") from exc
    if not result.is_finite():
        raise ValueError("NaN·Infinity는 허용하지 않습니다.")
    return result


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal cannot be serialized")
        return float(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=_reject_constant)
    except (OSError, ValueError) as exc:
        raise ValueError(f"입력 파일을 읽을 수 없습니다: {path}: {exc}") from exc


def load_inputs(input_dir: str | Path) -> dict:
    """Load a complete input bundle; never modify input files."""
    folder = Path(input_dir).resolve()
    scenario_document = _read_json(folder / "scenarios.json")
    if isinstance(scenario_document, list):
        scenarios, stress_templates = scenario_document, []
    elif isinstance(scenario_document, dict):
        scenarios = scenario_document.get("scenarios", [])
        stress_templates = scenario_document.get("stress_templates", [])
    else:
        raise ValueError("scenarios.json은 객체 또는 배열이어야 합니다.")
    event_path = folder / "events.csv"
    try:
        with event_path.open(encoding="utf-8-sig", newline="") as stream:
            events = list(csv.DictReader(stream))
    except OSError as exc:
        raise ValueError(f"사건 입력을 읽을 수 없습니다: {event_path}") from exc
    for event in events:
        if event.get("sequence", "") != "":
            try:
                event["sequence"] = int(event["sequence"])
            except (TypeError, ValueError):
                pass
        if event.get("amount", "") != "":
            try:
                event["amount"] = float(D(event["amount"]))
            except ValueError:
                pass
        for key in ("planned_event_id", "source_id", "reason"):
            if event.get(key) == "":
                event[key] = None
    return {
        "case": _read_json(folder / "case.json"),
        "policy": _read_json(folder / "policy_rules.json"),
        "scenarios": scenarios,
        "stress_templates": stress_templates,
        "events": events,
        "ai_usage": _read_json(folder / "ai_usage.json"),
        "input_dir": str(folder),
    }


def validate_inputs(bundle: dict) -> list[dict]:
    """Return actionable errors and uncertainty warnings, without changing input."""
    issues: list[dict] = []

    def issue(severity: str, code: str, message: str, path: str) -> None:
        issues.append(dict(severity=severity, code=code, message=message, path=path))

    def number(value: Any, path: str, minimum: Any = 0, maximum: Any = None) -> Decimal | None:
        try:
            value = D(value)
            if minimum is not None and value < D(minimum):
                raise ValueError(f"최솟값은 {minimum}입니다.")
            if maximum is not None and value > D(maximum):
                raise ValueError(f"최댓값은 {maximum}입니다.")
            return value
        except ValueError as exc:
            issue("ERROR", "INVALID_NUMBER", str(exc), path)
            return None

    def month(value: Any, path: str, optional: bool = False) -> str | None:
        if optional and value is None:
            return None
        try:
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
                raise ValueError
            date.fromisoformat(value + "-01")
            return value
        except (ValueError, TypeError):
            issue("ERROR", "INVALID_MONTH", "월은 YYYY-MM 형식의 실제 월이어야 합니다.", path)
            return None

    def day(value: Any, path: str, optional: bool = False) -> str | None:
        if optional and value is None:
            return None
        try:
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError
            date.fromisoformat(value)
            return value
        except (ValueError, TypeError):
            issue("ERROR", "INVALID_DATE", "날짜는 YYYY-MM-DD 형식의 실제 날짜여야 합니다.", path)
            return None

    if not isinstance(bundle, dict):
        return [dict(severity="ERROR", code="INVALID_BUNDLE", message="입력 묶음이 객체가 아닙니다.", path="")]
    case, policy = bundle.get("case"), bundle.get("policy")
    if not isinstance(case, dict) or not isinstance(policy, dict):
        return [dict(severity="ERROR", code="MISSING_INPUT", message="case와 policy 객체가 필요합니다.", path="")]
    if not isinstance(policy.get("policy_version"), str) or not policy.get("policy_version"):
        issue("ERROR", "MISSING_POLICY_VERSION", "정책 스냅샷 버전이 필요합니다.", "policy.policy_version")
    for field in ("case_id", "schema_version", "as_of_date", "start_month", "price_base_month"):
        if not case.get(field):
            issue("ERROR", "MISSING_FIELD", "필수 입력이 없습니다.", f"case.{field}")
    if case.get("currency") != "KRW" or case.get("amount_unit") != "만원":
        issue("ERROR", "UNSUPPORTED_UNIT", "이 버전은 KRW·만원 단위만 지원합니다. 단위를 변환한 뒤 입력하세요.", "case.amount_unit")
    as_of = day(case.get("as_of_date"), "case.as_of_date")
    start = month(case.get("start_month"), "case.start_month")
    price_base = month(case.get("price_base_month"), "case.price_base_month")
    if as_of and start and start <= as_of[:7]:
        issue("ERROR", "SNAPSHOT_OVERLAP", "첫 계산월은 기초잔액 기준월 이후여야 합니다.", "case.start_month")
    if price_base and start and price_base > start:
        issue("ERROR", "PRICE_BASE_AFTER_START", "가격 기준월이 첫 계산월보다 늦습니다.", "case.price_base_month")

    required_numbers = {
        "initial": ("cash", "stock", "pension", "rental_deposit", "rental_debt"),
        "income": ("husband", "wife", "leave_contribution", "settlement_retention"),
        "budget": ("adult_before", "adult_after", "child", "prenatal_insurance", "care_early", "care_late", "nursery", "rent_interest", "owned_maintenance", "retirement", "emergency_initial", "emergency_later", "birth_buffer", "trade_buffer"),
        "assumptions": ("inflation", "parent_support", "retirement_return"),
    }
    for section, fields in required_numbers.items():
        values = case.get(section)
        if not isinstance(values, dict):
            issue("ERROR", "MISSING_SECTION", "필수 입력 객체가 없습니다.", f"case.{section}")
            continue
        for field in fields:
            minimum = -0.99 if section == "assumptions" and field in ("inflation", "retirement_return") else 0
            number(values.get(field), f"case.{section}.{field}", minimum)
    assumptions = case.get("assumptions", {})
    if isinstance(assumptions, dict):
        for field in ("retirement_return", "stock_return", "house_price_growth"):
            if field not in assumptions:
                continue
            value = number(assumptions[field], f"case.assumptions.{field}", -0.99)
            if value is not None and value != 0:
                issue("ERROR", "UNSUPPORTED_RETURN", "현재 엔진은 투자수익·주택가격상승 0 모델입니다. 미구현 수익률을 조용히 적용하지 않습니다.", f"case.assumptions.{field}")
    def section(name: str) -> dict:
        value = case.get(name, {})
        return value if isinstance(value, dict) else {}

    tiers = section("income").get("leave_tiers")
    if not isinstance(tiers, list) or len(tiers) != 3:
        issue("ERROR", "LEAVE_TIERS", "휴직수당 1~3/4~6/7~12개월의 세 구간이 필요합니다.", "case.income.leave_tiers")
    else:
        for i, value in enumerate(tiers):
            number(value, f"case.income.leave_tiers[{i}]")
    initial = section("initial")
    try:
        if D(initial.get("rental_debt")) > D(initial.get("rental_deposit")):
            issue("ERROR", "NEGATIVE_RENTAL_EQUITY", "전세대출이 전세보증금을 초과합니다.", "case.initial")
    except ValueError:
        pass

    dates = section("dates")
    validated_dates = {}
    for key in ("birth_month", "maternity_start", "maternity_end", "leave_start", "leave_end", "nursery_start", "return_month"):
        validated_dates[key] = month(dates.get(key), "case.dates." + key)
    ordered_pairs = (("maternity_start", "maternity_end"), ("maternity_end", "leave_start"), ("leave_start", "leave_end"), ("leave_end", "return_month"))
    for earlier, later in ordered_pairs:
        a, b = validated_dates[earlier], validated_dates[later]
        if a and b and (a > b or (earlier in ("maternity_end", "leave_end") and a == b)):
            issue("ERROR", "DATE_ORDER", f"{earlier}와 {later}의 선후관계가 잘못됐습니다.", "case.dates")
    month(section("budget").get("prenatal_start"), "case.budget.prenatal_start")

    sources = case.get("sources", [])
    if not isinstance(sources, list):
        issue("ERROR", "INVALID_SOURCES", "출처는 배열이어야 합니다.", "case.sources")
        sources = []
    source_ids = [source.get("source_id") for source in sources if isinstance(source, dict) and isinstance(source.get("source_id"), str)]
    if len(set(source_ids)) != len(source_ids):
        issue("ERROR", "DUPLICATE_SOURCE", "출처 ID가 중복됩니다.", "case.sources")
    provenance = section("provenance")
    for key, evidence in provenance.items():
        if not isinstance(evidence, dict):
            issue("ERROR", "INVALID_PROVENANCE", "출처 메타데이터가 객체가 아닙니다.", f"case.provenance.{key}")
            continue
        if evidence.get("source_id") not in source_ids:
            issue("ERROR", "MISSING_SOURCE", "등록되지 않은 출처입니다.", f"case.provenance.{key}.source_id")
        if evidence.get("value_kind") not in {"fictional_case_setting", "model_assumption", "policy_rule", "observed_actual"}:
            issue("ERROR", "INVALID_VALUE_KIND", "값의 성격을 지정하세요.", f"case.provenance.{key}.value_kind")
        if evidence.get("verification_status") not in {"unreviewed", "source_matched", "evidence_verified"}:
            issue("ERROR", "INVALID_VERIFICATION_STATUS", "원문·증빙 확인 상태를 지정하세요.", f"case.provenance.{key}.verification_status")
        if evidence.get("value_kind") == "fictional_case_setting" and evidence.get("verification_status") == "evidence_verified":
            issue("ERROR", "FICTION_AS_ACTUAL", "가상 설정을 실제 증빙 확인값으로 표시할 수 없습니다.", f"case.provenance.{key}")

    for group in ("birth_expenses", "support_schedule", "life_stage_schedule"):
        records = case.get(group, [])
        if not isinstance(records, list):
            issue("ERROR", "INVALID_SCHEDULE", "일정은 배열이어야 합니다.", f"case.{group}")
            continue
        for i, record in enumerate(records):
            path = f"case.{group}[{i}]"
            if not isinstance(record, dict):
                issue("ERROR", "INVALID_RECORD", "일정 항목이 객체가 아닙니다.", path)
                continue
            if group == "birth_expenses":
                month(record.get("month"), path + ".month")
                number(record.get("amount"), path + ".amount")
            else:
                a = month(record.get("start"), path + ".start")
                b = month(record.get("end"), path + ".end", optional=True)
                if a and b and a > b:
                    issue("ERROR", "DATE_ORDER", "일정 종료월이 시작월보다 빠릅니다.", path)
                for field, value in record.items():
                    if field in ("amount", "adult", "child", "care", "nursery", "cash_support", "husband", "wife"):
                        number(value, path + "." + field)
    for group in ("support_schedule", "life_stage_schedule"):
        records = case.get(group, [])
        if not isinstance(records, list):
            continue
        for i, left in enumerate(records):
            if not isinstance(left, dict) or not isinstance(left.get("start"), str):
                continue
            for j, right in enumerate(records[i + 1:], i + 1):
                if not isinstance(right, dict) or not isinstance(right.get("start"), str):
                    continue
                left_end, right_end = left.get("end") or "9999-12", right.get("end") or "9999-12"
                if not isinstance(left_end, str) or not isinstance(right_end, str):
                    continue
                if max(left["start"], right["start"]) <= min(left_end, right_end):
                    if group == "support_schedule" or set(left).intersection(right).intersection({"adult", "child", "care", "nursery", "cash_support", "husband", "wife"}):
                        issue("ERROR", "OVERLAPPING_SCHEDULE", "같은 값에 적용되는 일정 구간이 겹칩니다.", f"case.{group}[{i},{j}]")

    voucher_ids = []
    vouchers = case.get("vouchers", [])
    if not isinstance(vouchers, list):
        issue("ERROR", "INVALID_VOUCHERS", "바우처는 배열이어야 합니다.", "case.vouchers")
        vouchers = []
    for i, voucher in enumerate(vouchers):
        path = f"case.vouchers[{i}]"
        if not isinstance(voucher, dict):
            issue("ERROR", "INVALID_VOUCHER", "바우처가 객체가 아닙니다.", path)
            continue
        if not isinstance(voucher.get("id"), str) or not voucher.get("id"):
            issue("ERROR", "INVALID_VOUCHER_ID", "바우처 ID가 필요합니다.", path)
        else:
            voucher_ids.append(voucher.get("id"))
        number(voucher.get("amount"), path + ".amount")
        if voucher.get("eligible_base_amount") is not None:
            number(voucher["eligible_base_amount"], path + ".eligible_base_amount")
        months = voucher.get("eligible_months", [])
        if not isinstance(months, list) or not months:
            issue("ERROR", "VOUCHER_MONTHS", "적격 지급월 목록이 필요합니다.", path)
        else:
            for j, value in enumerate(months):
                month(value, f"{path}.eligible_months[{j}]")
    if len(voucher_ids) != len(set(voucher_ids)):
        issue("ERROR", "DUPLICATE_VOUCHER", "바우처 ID가 중복됩니다.", "case.vouchers")

    repayment = case.get("repayment_constraint", {})
    if not isinstance(repayment, dict):
        issue("ERROR", "INVALID_REPAYMENT_RULE", "상환부담 규칙 객체가 필요합니다.", "case.repayment_constraint")
    else:
        for field in ("included_debts", "income_components"):
            values = repayment.get(field)
            if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values):
                issue("ERROR", "INVALID_REPAYMENT_COMPONENTS", "상환부담 분자·분모 항목은 비어 있지 않은 문자열 배열이어야 합니다.", f"case.repayment_constraint.{field}")
        for field in ("max_monthly_payment", "max_payment_ratio"):
            if repayment.get(field) is not None:
                number(repayment[field], f"case.repayment_constraint.{field}", 0, 1 if field.endswith("ratio") else None)
        if repayment.get("max_monthly_payment") is None and repayment.get("max_payment_ratio") is None:
            issue("WARNING", "REPAYMENT_LIMIT_UNKNOWN", "고객 합의 상환한도가 없어 해당 규칙은 UNKNOWN입니다.", "case.repayment_constraint")

    scenarios = bundle.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        issue("ERROR", "EMPTY_SCENARIOS", "계산할 대안 배열이 필요합니다.", "scenarios")
        scenarios = []
    seen_scenarios = set()
    for i, scenario in enumerate(scenarios):
        path = f"scenarios[{i}]"
        if not isinstance(scenario, dict):
            issue("ERROR", "INVALID_SCENARIO", "대안이 객체가 아닙니다.", path)
            continue
        sid = scenario.get("id")
        if not isinstance(sid, str) or not sid or sid in seen_scenarios:
            issue("ERROR", "DUPLICATE_SCENARIO", "대안 ID가 비어 있거나 중복됩니다.", path + ".id")
        else:
            seen_scenarios.add(sid)
        if scenario.get("mode") not in ("historical_replay", "working_plan"):
            issue("ERROR", "INVALID_MODE", "historical_replay 또는 working_plan이 필요합니다.", path + ".mode")
        end = month(scenario.get("analysis_end"), path + ".analysis_end")
        compare = month(scenario.get("comparison_end"), path + ".comparison_end")
        if start and end and end < start:
            issue("ERROR", "DATE_ORDER", "분석 종료월이 첫 계산월보다 빠릅니다.", path)
        if compare and end and compare > end:
            issue("ERROR", "COMPARISON_OUTSIDE_PERIOD", "공통 비교월이 분석기간 밖입니다.", path)
        for field in ("price", "loan", "rate"):
            if field == "loan" and scenario.get(field) is None:
                issue("ERROR", "LOAN_REQUIRED", "실행용 대안의 대출액을 입력하거나 탐색 후 지정하세요.", path + ".loan")
            else:
                number(scenario.get(field), path + "." + field, 0, 1 if field == "rate" else None)
        term = scenario.get("term_months", 360)
        if isinstance(term, bool) or not isinstance(term, int) or term <= 0:
            issue("ERROR", "INVALID_TERM", "상환기간은 양의 정수 개월이어야 합니다.", path + ".term_months")
        if scenario.get("purchase_year") is not None:
            from .finance import acquisition_costs
            try:
                if D(scenario.get("price")) <= 0:
                    issue("ERROR", "INVALID_PURCHASE_PRICE", "매입안의 가격은 0보다 커야 합니다.", path + ".price")
                else:
                    costs = acquisition_costs(scenario["price"], policy)
                    if costs["status"] == "UNKNOWN":
                        issue("ERROR", "COST_SCOPE_UNKNOWN", "세금·중개보수 적용범위가 미확정이라 비용 총액을 계산할 수 없습니다.", path + ".price")
            except (ValueError, TypeError, KeyError) as exc:
                issue("ERROR", "INVALID_COST_INPUT", str(exc), path + ".price")
            contract = day(scenario.get("contract_date"), path + ".contract_date")
            close = day(scenario.get("close_date"), path + ".close_date")
            if contract and close and contract >= close:
                issue("ERROR", "DATE_ORDER", "계약일은 잔금일보다 빨라야 합니다.", path)
            if close and end and close[:7] > end:
                issue("ERROR", "PURCHASE_OUTSIDE_PERIOD", "매입일이 분석기간 밖입니다.", path)
            if close and scenario.get("purchase_year") != int(close[:4]):
                issue("ERROR", "YEAR_MISMATCH", "매입연도와 잔금일 연도가 다릅니다.", path)
            if scenario.get("approved_limit") is None or scenario.get("approval_status") != "evidence_verified" or not scenario.get("approval_evidence_ref"):
                issue("WARNING", "LOAN_APPROVAL_UNKNOWN", "실제 대출 승인·한도는 확인되지 않았습니다.", path)
            if scenario.get("approved_limit") is not None:
                number(scenario["approved_limit"], path + ".approved_limit")
        else:
            for field in ("price", "loan"):
                try:
                    if D(scenario.get(field)) != 0:
                        issue("ERROR", "RENT_SCENARIO_VALUE", "전세 유지안의 매매가·주담대는 0이어야 합니다.", path)
                except ValueError:
                    pass
        overrides = scenario.get("overrides", {})
        if not isinstance(overrides, dict):
            issue("ERROR", "INVALID_OVERRIDES", "변경분은 객체여야 합니다.", path + ".overrides")
        else:
            for field in ("delay_months", "deposit_delay_months", "renew_extra", "care_multiplier"):
                if field in overrides:
                    number(overrides[field], path + ".overrides." + field)
            for field in ("delay_months", "deposit_delay_months"):
                if field in overrides and (isinstance(overrides[field], bool) or not isinstance(overrides[field], int)):
                    issue("ERROR", "INVALID_MONTH_COUNT", "지연 개월 수는 0 이상의 정수여야 합니다.", path + ".overrides." + field)
            if "stock_loss" in overrides:
                number(overrides["stock_loss"], path + ".overrides.stock_loss", 0, 1)
            for field in ("care_start", "parent_support_month"):
                if overrides.get(field) is not None:
                    month(overrides[field], path + ".overrides." + field)
            if overrides.get("parent_support_amount") is not None:
                number(overrides["parent_support_amount"], path + ".overrides.parent_support_amount")
            extra_expenses = overrides.get("extra_expenses", [])
            if not isinstance(extra_expenses, list):
                issue("ERROR", "INVALID_EXPENSES", "추가 지출은 배열이어야 합니다.", path + ".overrides.extra_expenses")
                extra_expenses = []
            for j, expense in enumerate(extra_expenses):
                epath = f"{path}.overrides.extra_expenses[{j}]"
                if not isinstance(expense, dict):
                    issue("ERROR", "INVALID_EXPENSE", "추가 지출은 객체여야 합니다.", epath)
                    continue
                a = month(expense.get("start"), epath + ".start")
                b = month(expense.get("end"), epath + ".end")
                if a and b and a > b:
                    issue("ERROR", "DATE_ORDER", "추가지출 종료월이 시작월보다 빠릅니다.", epath)
                number(expense.get("amount"), epath + ".amount")
        if scenario.get("mode") == "working_plan":
            if not policy.get("verified_for_execution", False):
                issue("WARNING", "POLICY_UNVERIFIED", "실행용 현행 제도 확인이 완료되지 않았습니다.", path)
            if not case.get("life_stage_schedule"):
                issue("WARNING", "LONG_TERM_BUDGET_UNKNOWN", "생애주기별 실제 장기예산이 아직 없습니다.", path)

    events = bundle.get("events", [])
    if not isinstance(events, list):
        issue("ERROR", "INVALID_EVENTS", "사건은 배열이어야 합니다.", "events")
        events = []
    seen_event_ids, planned = set(), {}
    supported_types = {"income", "expense", "retirement", "settlement_payment", "stock_sale", "rental_return"}
    for i, event in enumerate(events):
        path = f"events[{i}]"
        if not isinstance(event, dict):
            issue("ERROR", "INVALID_EVENT", "사건이 객체가 아닙니다.", path)
            continue
        eid = event.get("event_id")
        if not isinstance(eid, str) or not eid or eid in seen_event_ids:
            issue("ERROR", "DUPLICATE_EVENT", "사건 ID가 비어 있거나 중복됩니다.", path)
        else:
            seen_event_ids.add(eid)
        when = day(event.get("date"), path + ".date")
        number(event.get("amount"), path + ".amount")
        if not isinstance(event.get("sequence"), int) or isinstance(event.get("sequence"), bool):
            issue("ERROR", "INVALID_SEQUENCE", "당일 처리 순서는 정수여야 합니다.", path)
        if event.get("type") not in supported_types:
            issue("ERROR", "UNSUPPORTED_EVENT_TYPE", "지원하지 않는 사건 유형입니다. 주담대 실행·계약·잔금은 대안의 구조 입력에서 변경하세요.", path)
        if event.get("record_kind") not in ("planned", "actual"):
            issue("ERROR", "INVALID_RECORD_KIND", "planned 또는 actual을 지정하세요.", path)
        if event.get("record_kind") == "planned" and isinstance(eid, str):
            planned[eid] = event
        if event.get("record_kind") == "actual" and event.get("verification_status") != "evidence_verified":
            issue("WARNING", "ACTUAL_UNVERIFIED", "증빙 미확인 실제 기록은 계산 반영하지 않습니다.", path)
        if as_of and when and when <= as_of:
            issue("WARNING", "BEFORE_SNAPSHOT", "기초잔액 기준일 이전 사건은 현금에 재가산하지 않습니다.", path)
    applied_by_plan: dict[str, Decimal] = {}
    for i, event in enumerate(events):
        if not isinstance(event, dict) or event.get("record_kind") != "actual":
            continue
        target = event.get("planned_event_id")
        if target and (not isinstance(target, str) or target not in planned):
            issue("ERROR", "MISSING_PLANNED_EVENT", "연결한 계획 사건이 없습니다. 자동 사건 교체 대신 별도 명시 사건을 입력하세요.", f"events[{i}]")
        elif target and event.get("type") != planned[target].get("type"):
            issue("ERROR", "EVENT_TYPE_MISMATCH", "실제와 연결 계획의 유형이 다릅니다.", f"events[{i}]")
        if isinstance(target, str) and target and event.get("verification_status") == "evidence_verified":
            try:
                applied_by_plan[target] = applied_by_plan.get(target, Decimal(0)) + D(event.get("amount"))
            except ValueError:
                pass
    for target, paid in applied_by_plan.items():
        if target in planned:
            try:
                if paid > D(planned[target].get("amount")):
                    issue("WARNING", "ACTUAL_EXCEEDS_PLAN", "실제 집행액이 계획액을 초과했습니다. 차액도 실제 현금흐름에 반영됩니다.", "events." + target)
            except ValueError:
                pass
    stress_templates = bundle.get("stress_templates", [])
    if not isinstance(stress_templates, list):
        issue("ERROR", "INVALID_STRESS_TEMPLATES", "스트레스 템플릿은 배열이어야 합니다.", "stress_templates")
        stress_templates = []
    template_ids = set()
    for i, template in enumerate(stress_templates):
        path = f"stress_templates[{i}]"
        if not isinstance(template, dict):
            issue("ERROR", "INVALID_STRESS_TEMPLATE", "템플릿은 객체여야 합니다.", path)
            continue
        tid = template.get("id")
        if not isinstance(tid, str) or not tid or tid in template_ids:
            issue("ERROR", "DUPLICATE_STRESS_TEMPLATE", "템플릿 ID가 비어 있거나 중복됩니다.", path)
        else:
            template_ids.add(tid)
        for key in ("overrides", "scenario_overrides"):
            if key in template and not isinstance(template[key], dict):
                issue("ERROR", "INVALID_STRESS_OVERRIDES", "변경분은 객체여야 합니다.", path + "." + key)
        delay = template.get("parent_support_after_close_months")
        if delay is not None and (isinstance(delay, bool) or not isinstance(delay, int) or delay < 0):
            issue("ERROR", "INVALID_MONTH_COUNT", "상대 지원 지연은 0 이상의 정수 개월이어야 합니다.", path)
    if not policy.get("verified_for_execution", False):
        issue("WARNING", "HISTORICAL_POLICY_SNAPSHOT", "제도는 사례 재현용 스냅샷이며 실제 실행 승인이 아닙니다.", "policy")
    return issues
