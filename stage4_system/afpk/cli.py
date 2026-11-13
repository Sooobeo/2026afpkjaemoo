"""Command line entry points for calculation, validation and loan search."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from . import __version__
from .config import load_inputs, validate_inputs
from .constraints import evaluate, summarize
from .engine import add_months, simulate
from .report import write_outputs
from .search import find_loan
from .storage import canonical, code_digest, digest, write_json

ROOT = Path(__file__).resolve().parents[1]


def _common(parser):
    parser.add_argument("--input-dir", type=Path, default=ROOT / "inputs", help="입력 파일 폴더")


def parser():
    main = argparse.ArgumentParser(description="AFPK 4단계 계산·대안 비교 (단위: 만 원)")
    sub = main.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="대안·스트레스 계산 및 HTML/MD/CSV/JSON 생성")
    _common(run)
    run.add_argument("--output", type=Path, default=ROOT / "outputs" / "latest")
    run.add_argument("--scenario", action="append", help="시나리오 ID (반복 지정 가능, 생략 시 전체)")
    run.add_argument("--skip-stress", action="store_true", help="추가 스트레스 계산 생략")
    validate = sub.add_parser("validate", help="입력 오류·가정·미확인 항목 검사")
    _common(validate)
    search = sub.add_parser("find-loan", help="명시한 유한 격자에서 수치 통과 대출 탐색")
    _common(search)
    search.add_argument("--scenario", required=True)
    search.add_argument("--lower", type=float, default=0)
    search.add_argument("--upper", type=float, default=75000)
    search.add_argument("--step", type=float, default=100)
    search.add_argument("--max-evaluations", type=int, default=1000)
    search.add_argument("--output", type=Path, help="탐색 결과 JSON 경로")
    return main


def _snapshot(bundle):
    return {key: value for key, value in bundle.items() if key != "input_dir"}


def calculate(bundle, scenario):
    result = simulate(bundle["case"], scenario, bundle["policy"], bundle["events"])
    result["scenario"] = deepcopy(scenario)
    result["constraint_results"] = evaluate(bundle["case"], scenario, result, bundle["policy"])
    result["decision_status"] = summarize(result["constraint_results"])
    result["input_hash"] = digest({"case": bundle["case"], "policy": bundle["policy"],
                                   "events": bundle["events"], "scenario": scenario})
    result["code_version"] = __version__
    result["policy_version"] = bundle["policy"].get("policy_version", bundle["policy"].get("version", "unspecified"))
    result["output_hash"] = digest(result)
    return result


def stress_scenario(base, template):
    trial = deepcopy(base)
    trial["id"] = base["id"] + "__" + template["id"]
    trial["name"] = base["name"] + " / " + template["name"]
    trial.update(deepcopy(template.get("scenario_overrides", {})))
    overrides = deepcopy(trial.get("overrides", {}))
    changes = deepcopy(template.get("overrides", {}))
    shift = changes.pop("parent_support_after_close_months", None)
    # Accept the declarative helper on either template level.
    if shift is None:
        shift = template.get("parent_support_after_close_months")
    if shift is not None:
        changes["parent_support_month"] = add_months(trial["close_date"][:7], int(shift))
    overrides.update(changes)
    trial["overrides"] = overrides
    trial["stress_parent_id"] = base["id"]
    trial["stress_template_id"] = template["id"]
    return trial


def run(args, bundle, validation):
    selected = args.scenario or [s["id"] for s in bundle["scenarios"]]
    mapping = {s["id"]: s for s in bundle["scenarios"]}
    unknown = set(selected)-mapping.keys()
    if unknown:
        raise ValueError("알 수 없는 시나리오 ID: " + ", ".join(sorted(unknown)))
    scenarios = [mapping[sid] for sid in dict.fromkeys(selected)]
    if not scenarios:
        raise ValueError("계산할 시나리오가 없습니다.")
    results = [calculate(bundle, scenario) for scenario in scenarios]
    stresses = []
    if not args.skip_stress:
        for scenario in scenarios:
            if scenario.get("purchase_year") is None:
                continue
            # Do not stack a named preset stress on another named preset.
            neutral = {"delay_months": 0, "care_multiplier": 1, "stock_loss": 0,
                       "renew_extra": 0, "deposit_delay_months": 0,
                       "parent_support_month": None, "parent_support_amount": None,
                       "extra_expenses": [], "care_start": None}
            if any(scenario.get("overrides", {}).get(key) not in (None, value)
                   for key, value in neutral.items()):
                continue
            for template in bundle["stress_templates"]:
                trial = stress_scenario(scenario, template)
                if trial["loan"] != scenario["loan"]:
                    raise ValueError("스트레스 템플릿은 기본 대출원금을 바꿀 수 없습니다.")
                trial_errors = [v for v in validate_inputs({**bundle, "scenarios": [trial]})
                                if v["severity"] == "ERROR"]
                if trial_errors:
                    raise ValueError("스트레스 입력 오류: " + canonical(trial_errors))
                stresses.append(calculate(bundle, trial))
    metadata = {"status": "complete", "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
                "input_hash": digest(_snapshot(bundle)), "code_version": __version__,
                "code_hash": code_digest(),
                "policy_version": bundle["policy"].get("policy_version", bundle["policy"].get("version", "unspecified")),
                "scenarios": len(results), "stress_cases": len(stresses),
                "result_hash": digest({"results": results, "stress_results": stresses}),
                "numeric_policy": "Decimal 정밀도 36 계산, 만원 단위; 출력 숫자는 float, 중간 금액 반올림 없음",
                "law_status": "제공된 과거 설정과 가정. 실행일의 현행 법령·승인 별도 확인"}
    write_outputs(args.output, bundle, results, stresses, validation, metadata)
    return {"status": "complete", "output": str(args.output.resolve()),
            "report": str((args.output / "report.html").resolve()),
            "scenarios": len(results), "stress_cases": len(stresses),
            "input_warnings": sum(v["severity"] == "WARNING" for v in validation),
            "result_hash": metadata["result_hash"]}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["run"]
    elif argv[0].startswith("--") and argv[0] not in {"--help", "-h"}:
        argv.insert(0, "run")
    args = parser().parse_args(argv)
    try:
        bundle = load_inputs(args.input_dir)
        validation = validate_inputs(bundle)
        errors = [v for v in validation if v["severity"] == "ERROR"]
        if args.command == "validate":
            print(json.dumps({"status": "INVALID" if errors else "VALID", "issues": validation},
                             ensure_ascii=False, indent=2))
            return 2 if errors else 0
        if errors:
            print(json.dumps({"status": "INVALID", "issues": errors}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
        if args.command == "find-loan":
            scenario = next((s for s in bundle["scenarios"] if s["id"] == args.scenario), None)
            if scenario is None:
                raise ValueError("알 수 없는 시나리오: " + args.scenario)
            result = find_loan(bundle["case"], scenario, bundle["policy"], bundle["events"],
                               args.lower, args.upper, args.step, args.max_evaluations)
            result.update({"scenario_id": scenario["id"], "mode": scenario["mode"],
                           "analysis_end": scenario["analysis_end"],
                           "input_hash": digest(_snapshot(bundle)), "code_version": __version__,
                           "code_hash": code_digest()})
            if args.output:
                write_json(args.output, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "FOUND" else 3
        print(json.dumps(run(args, bundle, validation), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ArithmeticError) as exc:
        print(json.dumps({"status": "ERROR", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
