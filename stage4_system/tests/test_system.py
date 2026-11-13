"""Independent arithmetic, legacy regression, ledger and risk acceptance tests.

Run from stage4_system with: python -m unittest discover -s tests -v
No test writes the original hw data or runs feedback_audit.py.
"""
from __future__ import annotations

import copy
from decimal import Decimal, localcontext
from pathlib import Path
import runpy
import sys
import unittest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
sys.path.insert(0, str(PACKAGE_ROOT))

from afpk.config import load_inputs, validate_inputs
from afpk.finance import acquisition_costs, pmt
from afpk.engine import simulate
from afpk.constraints import evaluate
from afpk.search import find_loan


def make_scenario(year=2031, loan=21700, price=63000, end="2031-06", **overrides):
    return {
        "id": "test_scenario",
        "name": "검사용 가상 시나리오",
        "purchase_year": year,
        "price": price,
        "loan": loan,
        "rate": 0.05,
        "term_months": 360,
        "mode": "historical_replay",
        "contract_date": f"{year}-03-15" if year else None,
        "close_date": f"{year}-06-15" if year else None,
        "analysis_end": end,
        "comparison_end": "2031-06",
        "overrides": overrides,
    }


def custom_event(identifier, date, kind, amount, record_kind="planned", parent="", verified="source_matched"):
    return {
        "event_id": identifier,
        "date": date,
        "sequence": 10,
        "type": kind,
        "amount": amount,
        "record_kind": record_kind,
        "planned_event_id": parent,
        "verification_status": verified,
        "source_id": "test-fixture",
        "reason": "독립 인수검사용 가상 사건",
    }


class FixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_inputs(PACKAGE_ROOT / "inputs")
        cls.case = cls.bundle["case"]
        cls.policy = cls.bundle["policy"]

    def run_case(self, scenario=None, events=None, case=None):
        return simulate(
            copy.deepcopy(case if case is not None else self.case),
            copy.deepcopy(scenario if scenario is not None else make_scenario()),
            copy.deepcopy(self.policy),
            events=copy.deepcopy(events or []),
        )


class FinanceArithmeticTests(FixtureTest):
    def test_payment_against_discounted_cashflow_sum(self):
        # Independent method: the principal equals all discounted equal payments.
        with localcontext() as context:
            context.prec = 45
            principal = Decimal("10000")
            rate = Decimal("0.05") / 12
            annuity = sum((1 + rate) ** -month for month in range(1, 361))
            expected = principal / annuity
            actual = Decimal(str(pmt(principal, Decimal("0.05"), 360)))
            self.assertLess(abs(actual - expected), Decimal("0.000000001"))
            self.assertAlmostEqual(float(actual), 53.6821623, places=7)

    def test_zero_rate_and_zero_principal(self):
        self.assertEqual(Decimal(str(pmt(36000, 0, 360))), Decimal("100"))
        self.assertEqual(Decimal(str(pmt(0, 0.05, 360))), Decimal("0"))

    def test_invalid_payment_inputs_are_rejected(self):
        for principal, rate, term in [(-1, 0.05, 360), (100, -0.01, 360), (100, 0.05, 0)]:
            with self.subTest(principal=principal, rate=rate, term=term):
                with self.assertRaises(ValueError):
                    pmt(principal, rate, term)

    def test_price_band_costs_against_independent_expected_values(self):
        # Acquisition + education + brokerage/VAT + 900 fixed budget.
        expected = {56000: 1762.4, 58000: 1793.2, 60000: 1824.0, 63000: 2008.8, 75000: 2880.0}
        for price, total in expected.items():
            with self.subTest(price=price):
                result = acquisition_costs(price, copy.deepcopy(self.policy))
                self.assertEqual(result["status"], "PASS")
                self.assertAlmostEqual(float(result["total"]), total, places=7)

    def test_costs_do_not_mutate_policy(self):
        policy = copy.deepcopy(self.policy)
        before = copy.deepcopy(policy)
        acquisition_costs(63000, policy)
        self.assertEqual(policy, before)

    def test_unknown_tax_scope_is_not_silently_zero_cost(self):
        policy = copy.deepcopy(self.policy)
        policy["acquisition"]["area_le85"] = None
        result = acquisition_costs(63000, policy)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIsNone(result["total"])


class LegacyRegressionTests(FixtureTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        reference_path = REPO_ROOT / "hw" / "verify_plan.py"
        if not reference_path.exists():
            raise unittest.SkipTest("Optional original hw reference is absent in standalone copy")
        cls.reference = runpy.run_path(str(reference_path), run_name="read_only_reference")

    def compare_legacy(self, year, loan, price=75000, end="2031-06", **kwargs):
        ref = self.reference
        y, m = map(int, end.split("-"))
        old = ref["simulate"](year, loan, price=price, end=ref["idx"](y, m), **kwargs)
        overrides = {
            "delay_months": 6 if kwargs.get("delay") else 0,
            "care_multiplier": kwargs.get("care", 1),
            "stock_loss": kwargs.get("stock", 0),
            "renew_extra": 1500 if kwargs.get("renew") else 0,
            "deposit_delay_months": kwargs.get("deposit", 0),
        }
        if kwargs.get("parents"):
            overrides["parent_support_month"] = f"{year}-09"
        scenario = make_scenario(year, loan, price, end, **overrides)
        scenario["rate"] = kwargs.get("rate", 0.05)
        new = self.run_case(scenario)
        self.assertEqual(len(new["rows"]), len(old["rows"]))
        for old_row, new_row in zip(old["rows"], new["rows"]):
            self.assertEqual(old_row["month"], new_row["month"])
            for key, value in old_row.items():
                if isinstance(value, (int, float)):
                    self.assertIn(key, new_row, f"Missing ledger column {key}")
                    self.assertAlmostEqual(float(new_row[key]), value, delta=1e-6,
                                           msg=f"{scenario['id']} {year} {old_row['month']} {key}")
        for old_event in old["events"]:
            matches = [event for event in new["events"]
                       if event["date"] == old_event["date"] and event["event"] == old_event["event"]]
            self.assertEqual(len(matches), 1, old_event)
            for key, value in old_event.items():
                if isinstance(value, (int, float)):
                    self.assertAlmostEqual(float(matches[0][key]), value, delta=1e-6,
                                           msg=f"{old_event['date']} {key}")
        return new

    def test_three_original_purchase_cases_all_ledger_columns(self):
        for year, loan in [(2027, 42189), (2030, 33895), (2031, 31869)]:
            with self.subTest(year=year):
                self.compare_legacy(year, loan)

    def test_six_extended_cases_all_ledger_columns(self):
        cases = [
            (2027, 42189, 75000, "2032-06", {}),
            (2030, 33895, 75000, "2035-06", {}),
            (2031, 31869, 75000, "2036-06", {}),
            (2031, 21700, 63000, "2036-06", {}),
            (2031, 21700, 63000, "2036-06", {"rate": 0.07, "care": 1.2}),
            (2031, 21700, 63000, "2036-06", {"rate": 0.07, "care": 1.2, "delay": True, "stock": 0.2, "renew": True}),
        ]
        for year, loan, price, end, kwargs in cases:
            with self.subTest(year=year, price=price, kwargs=kwargs):
                self.compare_legacy(year, loan, price, end, **kwargs)

    def test_delayed_support_and_deposit_match_explicit_legacy_timing(self):
        self.compare_legacy(2030, 33895, parents=True, deposit=3)


class LedgerAcceptanceTests(FixtureTest):
    def test_birth_support_leave_and_retirement_totals(self):
        result = self.run_case()
        rows = result["rows"]
        self.assertEqual(len(rows), 55)
        self.assertAlmostEqual(sum(float(row["voucher"]) for row in rows), 300, places=7)
        self.assertAlmostEqual(sum(float(row["cash_support"]) for row in rows), 1690, places=7)
        self.assertAlmostEqual(sum(float(row["contribution"]) for row in rows), 378, places=7)
        self.assertAlmostEqual(sum(float(row["settlement_retained"]) for row in rows), 60, places=7)
        self.assertAlmostEqual(float(result["end"]["pension"]), 7000, places=7)
        self.assertAlmostEqual(sum(float(row["birth_gross"]) for row in rows), 1416.529133, places=5)
        june = next(row for row in rows if row["month"] == "2029-06")
        self.assertAlmostEqual(float(june["monthly_surplus"]), 25.9438541, places=6)
        self.assertAlmostEqual(float(june["monthly_surplus"])-float(june["settlement_retained"]), 20.9438541, places=6)

    def test_cash_and_protected_fund_conservation(self):
        result = self.run_case()
        for row in result["rows"]:
            self.assertAlmostEqual(float(row["cash"]),
                float(row["opening_cash"])+float(row["monthly_surplus"])+float(row["asset_receipts"])+float(row["transaction_flow"]),
                delta=1e-6, msg=row["month"])
            self.assertAlmostEqual(float(row["free"]),
                float(row["cash"])-float(row["reserve"])-float(row["earmark"]), delta=1e-6)

    def test_intramonth_extrema_include_contract_event(self):
        result = self.run_case(make_scenario(2027, 42189, 75000))
        month_end_min = min(float(row["free"]) for row in result["rows"])
        self.assertAlmostEqual(float(result["min_free"]["free"]), -552.3184391971, delta=1e-6)
        self.assertLess(float(result["min_free"]["free"]), month_end_min)
        self.assertEqual(result["min_free"]["date"], "2027-03-15")

    def test_long_term_counterexample_remains_visible(self):
        scenario = make_scenario(end="2036-06", delay_months=6, care_multiplier=1.2, stock_loss=0.2, renew_extra=1500)
        scenario["rate"] = 0.07
        result = self.run_case(scenario)
        closing = next(event for event in result["events"] if event["date"] == "2031-06-15")
        self.assertAlmostEqual(float(closing["free"]), 30.5426982758, delta=1e-6)
        first = next(row for row in result["rows"] if row["month"] >= "2031-06" and float(row["free"]) < -1e-7)
        self.assertEqual(first["month"], "2033-07")
        self.assertTrue(all(float(row["cash"]) > 0 for row in result["rows"]))

    def test_leave_and_stock_stresses_have_separate_explainable_effects(self):
        baseline = self.run_case(make_scenario(2030, 33895, 75000))
        delayed = self.run_case(make_scenario(2030, 33895, 75000, delay_months=6))
        stock = self.run_case(make_scenario(2030, 33895, 75000, stock_loss=0.2))
        self.assertAlmostEqual(float(baseline["end"]["cash"])-float(delayed["end"]["cash"]), 1869, places=6)
        self.assertAlmostEqual(float(baseline["end"]["cash"])-float(stock["end"]["cash"]), 500, places=6)
        self.assertAlmostEqual(float(delayed["end"]["settlement_balance"]), 90, places=6)

    def test_inputs_are_not_mutated_and_outputs_are_deterministic(self):
        case = copy.deepcopy(self.case)
        scenario = make_scenario()
        policy = copy.deepcopy(self.policy)
        before = copy.deepcopy((case, scenario, policy))
        first = simulate(case, scenario, policy, events=[])
        second = simulate(case, scenario, policy, events=[])
        self.assertEqual((case, scenario, policy), before)
        self.assertEqual(first, second)


class EventAndRiskTests(FixtureTest):
    def rent_scenario(self):
        return make_scenario(None, 0, 0, "2027-01")

    def test_planned_and_confirmed_partial_actual_are_not_double_counted(self):
        baseline = self.run_case(self.rent_scenario())
        events = [custom_event("plan", "2026-12-20", "expense", 100),
                  custom_event("actual", "2026-12-10", "expense", 40, "actual", "plan", "evidence_verified")]
        result = self.run_case(self.rent_scenario(), events)
        self.assertAlmostEqual(float(baseline["end"]["cash"])-float(result["end"]["cash"]), 100, places=6)

    def test_pre_snapshot_actual_reduces_future_plan_without_readding_cash(self):
        baseline = self.run_case(self.rent_scenario())
        events = [custom_event("plan", "2026-12-20", "expense", 100),
                  custom_event("actual", "2026-11-15", "expense", 40, "actual", "plan", "evidence_verified")]
        result = self.run_case(self.rent_scenario(), events)
        self.assertAlmostEqual(float(baseline["end"]["cash"])-float(result["end"]["cash"]), 60, places=6)

    def test_unverified_actual_does_not_silently_change_forecast(self):
        baseline = self.run_case(self.rent_scenario())
        event = custom_event("unreviewed", "2026-12-10", "expense", 400, "actual", verified="unreviewed")
        result = self.run_case(self.rent_scenario(), [event])
        self.assertAlmostEqual(float(baseline["end"]["cash"]), float(result["end"]["cash"]), places=6)
        self.assertTrue(result["limitations"])

    def test_positive_month_end_does_not_hide_earlier_payment_failure(self):
        scenario = self.rent_scenario()
        events = [custom_event("out", "2026-12-01", "expense", 9000),
                  custom_event("in", "2026-12-31", "income", 9000)]
        result = self.run_case(scenario, events)
        self.assertGreater(float(result["end"]["cash"]), 0)
        self.assertLess(float(result["min_cash"]["cash"]), 0)
        self.assertEqual(result["min_cash"]["date"], "2026-12-01")

    def test_cash_protection_approval_and_retirement_sufficiency_are_separate(self):
        scenario = make_scenario(2027, 42189, 75000)
        result = self.run_case(scenario)
        rules = {row["rule_id"]: row for row in evaluate(self.case, scenario, result, self.policy)}
        self.assertEqual(rules["CASH_NONNEGATIVE"]["status"], "PASS")
        self.assertEqual(rules["PROTECTED_FUNDS"]["status"], "FAIL")
        self.assertEqual(rules["LOAN_APPROVAL"]["status"], "UNKNOWN")
        self.assertEqual(rules["REPAYMENT_LIMIT"]["status"], "UNKNOWN")
        self.assertEqual(rules["RETIREMENT_SUFFICIENCY"]["status"], "NOT_EVALUATED")

    def test_verified_loan_limit_and_customer_payment_limit_are_enforced(self):
        scenario = make_scenario()
        scenario.update(approved_limit=21200, approval_status="evidence_verified",
                        approval_evidence_ref="test-only-mock-approval")
        case = copy.deepcopy(self.case)
        case["repayment_constraint"].update(max_monthly_payment=100,
                                            agreement_ref="test-only-mock-agreement")
        result = self.run_case(scenario, case=case)
        rules = {row["rule_id"]: row for row in evaluate(case, scenario, result, self.policy)}
        self.assertEqual(rules["LOAN_APPROVAL"]["status"], "FAIL")
        self.assertAlmostEqual(rules["LOAN_APPROVAL"]["amount"], 500, places=6)
        self.assertEqual(rules["REPAYMENT_LIMIT"]["status"], "FAIL")

    def test_monthly_aggregate_is_not_misclassified_as_dated_transaction(self):
        case = copy.deepcopy(self.case)
        case["initial"]["cash"] = 10
        case["budget"]["adult_before"] = 20000
        scenario = self.rent_scenario()
        result = self.run_case(scenario, case=case)
        rules = {row["rule_id"]: row for row in evaluate(case, scenario, result, self.policy)}
        self.assertEqual(rules["CASH_NONNEGATIVE"]["status"], "FAIL")
        self.assertNotEqual(rules["TRANSACTION_LIQUIDITY"]["status"], "FAIL")

    def test_opening_protection_failure_is_not_hidden_by_later_salary(self):
        case = copy.deepcopy(self.case)
        case["initial"]["cash"] = 0
        case["income"]["husband"] = 20000
        scenario = self.rent_scenario()
        result = self.run_case(scenario, case=case)
        self.assertTrue(all(float(row["cash"]) > 0 for row in result["rows"]))
        self.assertAlmostEqual(float(result["min_cash"]["cash"]), 0, places=7)
        self.assertLess(float(result["min_free"]["free"]), 0)
        self.assertEqual(result["min_free"]["date"], case["as_of_date"])
        rules = {row["rule_id"]: row for row in evaluate(case, scenario, result, self.policy)}
        self.assertEqual(rules["CASH_NONNEGATIVE"]["status"], "PASS")
        self.assertEqual(rules["PROTECTED_FUNDS"]["status"], "FAIL")
        self.assertEqual(rules["PROTECTED_FUNDS"]["first_breach_at"], case["as_of_date"])
        self.assertNotEqual(rules["TRANSACTION_LIQUIDITY"]["status"], "FAIL")


class InputValidationTests(FixtureTest):
    def assert_invalid(self, bundle):
        issues = validate_inputs(bundle)
        self.assertTrue(any(issue["severity"] == "ERROR" for issue in issues), issues)

    def test_default_bundle_has_no_input_errors(self):
        self.assertFalse([issue for issue in validate_inputs(copy.deepcopy(self.bundle)) if issue["severity"] == "ERROR"])

    def test_wrong_unit_nonfinite_negative_and_chronology_are_rejected(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["case"]["amount_unit"] = "원"
        self.assert_invalid(bundle)
        bundle = copy.deepcopy(self.bundle)
        bundle["case"]["initial"]["cash"] = float("nan")
        self.assert_invalid(bundle)
        bundle = copy.deepcopy(self.bundle)
        bundle["case"]["initial"]["cash"] = -1
        self.assert_invalid(bundle)
        bundle = copy.deepcopy(self.bundle)
        bundle["case"]["dates"]["leave_end"] = "2028-01"
        self.assert_invalid(bundle)

    def test_duplicate_event_ids_are_rejected(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["events"] = [custom_event("same", "2026-12-01", "expense", 10),
                            custom_event("same", "2026-12-02", "expense", 20)]
        self.assert_invalid(bundle)

    def test_malformed_repayment_components_do_not_reach_calculation(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["case"]["repayment_constraint"]["included_debts"] = None
        self.assert_invalid(bundle)
        bundle = copy.deepcopy(self.bundle)
        bundle["case"]["repayment_constraint"]["income_components"] = "husband"
        self.assert_invalid(bundle)

    def test_evidenced_loan_approval_uses_same_vocabulary_as_rules(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["scenarios"] = [make_scenario()]
        bundle["scenarios"][0].update(approved_limit=30000,
            approval_status="evidence_verified", approval_evidence_ref="test-only-mock-approval")
        issues = validate_inputs(bundle)
        self.assertFalse([issue for issue in issues if issue["code"] == "LOAN_APPROVAL_UNKNOWN"], issues)


class SearchAcceptanceTests(FixtureTest):
    def test_fully_funded_case_returns_smallest_grid_candidate(self):
        case = copy.deepcopy(self.case)
        case["initial"]["cash"] = 100000
        result = find_loan(case, make_scenario(), self.policy, lower=0, upper=20, step=10, max_evaluations=10)
        self.assertEqual(result["status"], "FOUND")
        self.assertAlmostEqual(float(result["loan"]), 0, places=6)

    def test_early_contract_failure_is_not_fixed_by_future_loan(self):
        result = find_loan(copy.deepcopy(self.case), make_scenario(2027, 42189, 75000), self.policy,
                           lower=0, upper=75000, step=5000, max_evaluations=30)
        self.assertEqual(result["status"], "CONTRACT_BLOCKED")

    def test_search_budget_exhaustion_is_not_mislabeled_as_no_solution(self):
        result = find_loan(copy.deepcopy(self.case), make_scenario(), self.policy,
                           lower=0, upper=75000, step=1, max_evaluations=1)
        self.assertEqual(result["status"], "SEARCH_INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
