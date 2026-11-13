"""합본2 표시값·독립산식·동적비상목표·취학 민감도의 의미 있는 검사."""
from pathlib import Path
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from 계산모델 import scenario,compound,run,closing,contract,post_minimum,school_sensitivity,legacy_loan_boundary,load_case
from afpk.finance import pmt,acquisition_costs


class Combined2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results=json.loads((ROOT/'outputs'/'전체계산결과.json').read_text(encoding='utf-8'))

    def rounded(self,actual,display):
        self.assertLessEqual(abs(actual-display),.0500001)

    def test_three_periods_source_table(self):
        for year,loan,pay,cf,surplus,breach in ((2027,41414,222.3,-58.2,-48.1,'2031-07'),(2030,33286,178.7,7815.3,-4.5,'2031-07'),(2031,31304,168.0,9716.7,6.1,'2031-10')):
            with self.subTest(year=year):
                r=self.results[f'base_{year}'];self.assertEqual(r['loan'],loan)
                self.rounded(r['payment'],pay);self.rounded(contract(r)['free'],cf)
                self.rounded(r['metrics']['comparison_row']['monthly_surplus'],surplus)
                self.assertEqual(self.results[f'post_{year}']['metrics']['post_purchase_first_monthend_protected_breach']['month'],breach)

    def test_price_loan_source_table(self):
        for price,loan,basic,stress,monthly in ((63000,21700,3577.3,-621.,-45.7),(60000,19000,4149.,1067.3,-27.7),(58000,19000,6179.8,3098.1,-27.7),(56000,19000,8210.6,5128.9,-27.7),(56000,14500,3855.6,941.1,2.2)):
            with self.subTest(price=price,loan=loan):
                sid=f'price_{price}_loan_{loan}';self.rounded(closing(self.results[sid])['free'],basic)
                self.rounded(post_minimum(self.results[sid+'__compound'])['free'],stress)
                self.rounded(self.results[sid+'__compound']['end']['monthly_surplus'],monthly)

    def test_preferred_single_stresses_match_source(self):
        rows=[('price_56000_loan_14500',77.8,8037.6,3855.6,35.4),('preferred__leave',77.8,6168.6,1986.6,35.4),('preferred__care',77.8,7682.8,3421.9,20.9),('preferred__rate',96.5,8037.6,3743.8,16.7),('preferred__parent_delay',77.8,-1962.4,-6144.4,35.4),('preferred__deposit_1',77.8,-11962.4,-16324.4,35.4),('preferred__deposit_3',77.8,-11962.4,-16324.4,35.4),('preferred__renew',77.8,8037.6,3855.6,35.4),('preferred__stock',77.8,7537.6,3355.6,35.4),('price_56000_loan_14500__compound',96.5,5313.8,941.1,2.2)]
        for sid,pay,cash,free,surplus in rows:
            with self.subTest(sid=sid):
                r=self.results[sid];self.rounded(r['payment'],pay);self.rounded(closing(r)['cash_after'],cash)
                self.rounded(post_minimum(r)['free'],free);self.rounded(r['end']['monthly_surplus'],surplus)

    def test_independent_discounted_payment_and_cost_sum(self):
        monthly=Decimal('.05')/12
        discount=sum((1+monthly)**(-n) for n in range(1,361))
        self.assertLess(abs(pmt(14500,.05)-Decimal(14500)/discount),Decimal('1e-20'))
        policy=json.loads((ROOT/'inputs'/'policy_rules.json').read_text(encoding='utf-8'))
        self.assertEqual(acquisition_costs(56000,policy)['total'],Decimal(560)+56+Decimal('246.4')+900)

    def test_cash_protected_assets_and_monthly_conservation(self):
        r=self.results['price_56000_loan_14500']
        for row in r['rows']:
            self.assertAlmostEqual(row['cash'],row['opening_cash']+row['asset_receipts']+row['transaction_flow']+row['monthly_surplus'],places=7)
            self.assertAlmostEqual(row['free'],row['cash']-row['reserve']-row['earmark'],places=7)
        self.assertEqual(r['end']['pension'],13000)
        self.assertEqual(r['metrics']['comparison_row']['pension'],7000)
        self.rounded(sum(x['birth_cash'] for x in r['rows']),1116.5)

    def test_dynamic_reserve_includes_rental_period_and_never_decreases(self):
        for sid in ('price_56000_loan_14500','price_56000_loan_14500__compound','price_56000_loan_14500__compound__school_net_plus_50'):
            previous=2700
            for row in self.results[sid]['rows']:
                target=max(previous,6*(row['living']+row['mortgage']+row['reserve_extra_expense']))
                self.assertAlmostEqual(row['reserve'],target,places=7)
                previous=row['reserve']
        first=self.results['price_56000_loan_14500']['rows'][0]
        self.assertLess(first['reserve'],3100)

    def test_school_necessary_extra_affects_cash_and_reserve(self):
        base=self.results['price_56000_loan_14500__compound']
        extra=self.results['price_56000_loan_14500__compound__school_net_plus_5']
        self.assertAlmostEqual(base['end']['cash']-extra['end']['cash'],16*5,places=7)
        self.assertAlmostEqual(extra['end']['reserve']-base['end']['reserve'],6*5,places=7)
        self.assertAlmostEqual(base['end']['monthly_surplus']-extra['end']['monthly_surplus'],5,places=7)
        self.rounded(extra['end']['monthly_surplus'],-2.8)
        self.assertEqual(next(r['month'] for r in extra['rows'] if r['month']>='2035-03' and r['monthly_surplus']<0),'2036-04')

    def test_school_larger_sensitivity_and_unconfirmed_budget(self):
        for extra,ending in ((20,-17.8),(50,-47.8)):
            r=self.results[f'price_56000_loan_14500__compound__school_net_plus_{extra}']
            self.rounded(r['end']['monthly_surplus'],ending)
            self.assertEqual(next(x['month'] for x in r['rows'] if x['month']>='2035-03' and x['monthly_surplus']<0),'2035-03')
        form=json.loads((ROOT/'inputs'/'취학후_예산확인표.json').read_text(encoding='utf-8'))
        self.assertEqual(form['status'],'UNKNOWN');self.assertIsNone(form['school_fee_nominal'])

    def test_inputs_not_mutated_and_numeric_results_reproducible(self):
        case=load_case();s=compound(scenario('test'));before=deepcopy((case,s))
        a,b=run(s,case),run(s,case)
        self.assertEqual((case,s),before);self.assertEqual(a,b)

    def test_legacy_loan_boundaries_proved_and_one_unit_below_fails(self):
        data=json.loads((ROOT/'outputs'/'검증결과.json').read_text(encoding='utf-8'))
        self.assertEqual([r['loan'] for r in data['loan_boundaries']],[41414,33286,31304])
        for row in data['loan_boundaries']:
            self.assertGreater(row['monotonic_slope_lower'],0)
            self.assertLess(row['one_less_margin'],0);self.assertGreaterEqual(row['boundary_margin'],0)

    def test_retention_removal_releases_allocation_without_creating_income(self):
        case=load_case()
        self.assertNotIn('settlement_retention',case['income'])
        legacy=deepcopy(case);legacy['income']['settlement_retention']=5
        for s in (scenario('retention_base'),compound(scenario('retention_compound'))):
            revised,old=run(s,case),run(s,legacy)
            for new_row,old_row in zip(revised['rows'],old['rows']):
                self.assertEqual(new_row['settlement_balance'],0)
                self.assertEqual(new_row['settlement_retained'],0)
                for key in ('cash','monthly_surplus','net_worth','reserve'):
                    self.assertEqual(new_row[key],old_row[key])
                self.assertAlmostEqual(new_row['free']-old_row['free'],old_row['settlement_balance'],places=7)
        for result in self.results.values():
            self.assertTrue(all(row['settlement_balance']==0 for row in result['rows']))

    def test_display_rounding_is_separate_from_raw_cash_and_won_schedule(self):
        import csv
        import importlib
        report=importlib.import_module('전체재계산')
        self.assertEqual(report.fmt('3855.564589606161'),'3,856')
        self.assertEqual(report.fmt('-48.148805232'),'-48')
        self.assertEqual(report.won('77.83913533675971'),778391)
        path=ROOT/'outputs'/'원단위_원리금상환표.csv'
        with path.open(encoding='utf-8-sig',newline='') as stream:
            row=next(x for x in csv.DictReader(stream) if x['scenario_id']=='price_56000_loan_14500')
        actual=self.results['price_56000_loan_14500']
        self.assertEqual(int(row['payment_won']),report.won(actual['payment']))
        self.assertNotEqual(closing(actual)['cash_after'],round(closing(actual)['cash_after']))

    def test_original_files_unchanged_when_workspace_available(self):
        manifest=json.loads((ROOT/'source'/'복사원본_해시.json').read_text(encoding='utf-8'))
        for rel,expected in manifest.items():
            origin=ROOT.parent/rel
            if origin.exists():self.assertEqual(hashlib.sha256(origin.read_bytes()).hexdigest(),expected)


if __name__=='__main__':unittest.main()
