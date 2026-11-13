"""Portable CLI/export integration tests using temporary output directories."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent
sys.path.insert(0, str(PACKAGE_ROOT))

from afpk.cli import calculate, stress_scenario
from afpk.config import load_inputs
from afpk.storage import digest


def file_hashes():
    paths = list((PACKAGE_ROOT / "inputs").glob("*"))
    for name in ("verify_plan.py", "feedback_audit.py", "1107-규리_원본설정표.md", "4단계_피드백반영_수정본문.md"):
        path = REPO_ROOT / "hw" / name
        if path.exists():
            paths.append(path)
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class CLIExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="afpk-cli-test-")
        cls.workdir = Path(cls.temporary.name) / "unrelated_working_directory"
        cls.workdir.mkdir()
        cls.output = Path(cls.temporary.name) / "calculated_output"
        cls.before_hashes = file_hashes()
        cls.environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        cls.process = subprocess.run(
            [sys.executable, str(PACKAGE_ROOT / "run.py"), "run", "--scenario", "base_2027",
             "--skip-stress", "--output", str(cls.output)],
            cwd=cls.workdir, env=cls.environment, text=True, encoding="utf-8",
            capture_output=True, timeout=30,
        )
        if cls.process.returncode:
            cls.temporary.cleanup()
            raise AssertionError(f"CLI run failed: {cls.process.returncode}\n{cls.process.stdout}\n{cls.process.stderr}")
        cls.response = json.loads(cls.process.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_run_from_unrelated_directory_creates_complete_output_package(self):
        expected = {
            "run_metadata.json", "inputs_snapshot.json", "results.json", "stress_results.json",
            "scenario_comparison.csv", "stress_results.csv", "monthly_cashflow.csv",
            "event_liquidity.csv", "transaction_summary.csv", "protected_funds.csv",
            "validation_results.json", "ai_usage_record.json", "baseline_plan.json",
            "report_stage4.md", "report.html",
        }
        self.assertTrue(expected <= {path.name for path in self.output.iterdir()})
        self.assertTrue(all((self.output / name).stat().st_size > 0 for name in expected))
        self.assertEqual(self.response["status"], "complete")
        self.assertEqual(self.response["scenarios"], 1)
        self.assertEqual(self.response["stress_cases"], 0)
        self.assertEqual(Path(self.response["report"]), self.output / "report.html")
        self.assertEqual(json.loads((self.output / "stress_results.json").read_text(encoding="utf-8")), [])

    def test_exported_totals_and_embedded_html_data_match_computed_result(self):
        results = json.loads((self.output / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(len(results), 1)
        result = results[0]
        comparison = read_csv(self.output / "scenario_comparison.csv")
        self.assertEqual(len(comparison), 1)
        row = comparison[0]
        self.assertEqual(row["scenario_id"], "base_2027")
        self.assertAlmostEqual(float(row["payment"]), 226.4796745326, places=6)
        self.assertAlmostEqual(float(row["contract_free"]), -552.3184391971, places=6)
        self.assertEqual(row["output_hash"], result["output_hash"])
        contract = next(event for event in result["events"] if "계약금" in event["event"])
        close = next(event for event in result["events"] if "잔금" in event["event"])
        self.assertAlmostEqual(float(row["contract_free"]), contract["free"], places=7)
        self.assertAlmostEqual(float(row["closing_free"]), close["free"], places=7)
        monthly = read_csv(self.output / "monthly_cashflow.csv")
        self.assertEqual(len(monthly), 55)
        self.assertAlmostEqual(float(monthly[-1]["cash"]), result["end"]["cash"], places=7)
        self.assertAlmostEqual(sum(float(r["cash_support"]) for r in monthly), 1690, places=7)
        html = (self.output / "report.html").read_text(encoding="utf-8")
        embedded = re.search(r'<script\s+id="data"\s+type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(embedded)
        payload = json.loads(embedded.group(1))
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["summary"]["output_hash"], result["output_hash"])
        self.assertAlmostEqual(payload[0]["summary"]["contract_free"], contract["free"], places=7)
        self.assertEqual(payload[0]["rows"], result["rows"])
        self.assertEqual(payload[0]["checks"], result["constraint_results"])
        self.assertNotIn("__DATA__", html)

    def test_baseline_is_unsigned_draft_with_housing_execution_disabled(self):
        baseline = json.loads((self.output / "baseline_plan.json").read_text(encoding="utf-8"))
        self.assertIs(baseline["draft"], True)
        self.assertIs(baseline["housing_execution_allowed"], False)
        self.assertEqual(baseline["housing_status"], "REVIEW_REQUIRED")
        self.assertIsNone(baseline["selected_housing_scenario_id"])
        self.assertIsNone(baseline["decision"])
        self.assertEqual(baseline["actual_records"], [])
        self.assertTrue(baseline["preparation_actions"])
        results = json.loads((self.output / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(baseline["planned_monthly_rows"], results[0]["rows"])

    def test_input_and_original_reference_files_remain_unchanged(self):
        self.assertEqual(file_hashes(), self.before_hashes)

    def test_unknown_scenario_has_structured_error_and_no_partial_output(self):
        output = Path(self.temporary.name) / "must_not_exist"
        process = subprocess.run(
            [sys.executable, str(PACKAGE_ROOT / "run.py"), "run", "--scenario", "missing_case",
             "--skip-stress", "--output", str(output)],
            cwd=self.workdir, env=self.environment, text=True, encoding="utf-8",
            capture_output=True, timeout=30,
        )
        self.assertEqual(process.returncode, 2)
        error = json.loads(process.stderr)
        self.assertEqual(error["status"], "ERROR")
        self.assertIn("missing_case", error["message"])
        self.assertFalse(output.exists())

    def test_cli_search_incomplete_is_not_a_no_solution_or_success_exit(self):
        process = subprocess.run(
            [sys.executable, str(PACKAGE_ROOT / "run.py"), "find-loan", "--scenario", "base_2031",
             "--lower", "0", "--upper", "75000", "--step", "1", "--max-evaluations", "1"],
            cwd=self.workdir, env=self.environment, text=True, encoding="utf-8",
            capture_output=True, timeout=30,
        )
        self.assertEqual(process.returncode, 3, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["status"], "SEARCH_INCONCLUSIVE")
        self.assertEqual(result["evaluations"], 1)


class ProvenanceAndStressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_inputs(PACKAGE_ROOT / "inputs")

    def test_calculated_result_hash_is_deterministic_and_recomputable(self):
        scenario = next(row for row in self.bundle["scenarios"] if row["id"] == "base_2030")
        before = copy.deepcopy((self.bundle, scenario))
        first = calculate(self.bundle, scenario)
        second = calculate(self.bundle, scenario)
        self.assertEqual(first["output_hash"], second["output_hash"])
        self.assertEqual(first["input_hash"], second["input_hash"])
        self.assertEqual(first, second)
        self.assertEqual(first["output_hash"], digest({key: value for key, value in first.items() if key != "output_hash"}))
        self.assertEqual((self.bundle, scenario), before)

    def test_parent_delay_template_resolves_from_closing_month_without_mutation(self):
        base = next(row for row in self.bundle["scenarios"] if row["id"] == "base_2030")
        template = next(row for row in self.bundle["stress_templates"] if row["id"] == "parent_delay")
        before = copy.deepcopy((base, template))
        trial = stress_scenario(base, template)
        self.assertEqual(trial["overrides"]["parent_support_month"], "2030-09")
        self.assertEqual(trial["loan"], base["loan"])
        self.assertEqual(trial["stress_parent_id"], "base_2030")
        self.assertEqual((base, template), before)
        result = calculate(self.bundle, trial)
        may = next(row for row in result["rows"] if row["month"] == "2030-05")
        september = next(row for row in result["rows"] if row["month"] == "2030-09")
        self.assertEqual(may["asset_receipts"], 0)
        self.assertEqual(september["asset_receipts"], 10000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
