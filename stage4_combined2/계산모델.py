"""합본2의 450/300/2700 입력과 동적 비상목표를 사용하는 재현 API.

원본 폴더나 네트워크에 의존하지 않는다. 금액 단위는 만 원이며 실제 금융거래를 실행하지 않는다.
"""
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path

from afpk.engine import simulate
from afpk.finance import pmt, acquisition_costs
from afpk.constraints import evaluate
from afpk.storage import clean, digest

ROOT = Path(__file__).resolve().parent


def load_case():
    return json.loads((ROOT / 'inputs' / 'case.json').read_text(encoding='utf-8'))


def load_policy():
    return json.loads((ROOT / 'inputs' / 'policy_rules.json').read_text(encoding='utf-8'))


def scenario(sid, year=2031, price=56000, loan=14500, *, end='2036-06', rate=.05, overrides=None):
    return dict(id=sid, name=sid, purchase_year=year, price=price, loan=loan,
                rate=rate, term_months=360, mode='historical_replay',
                contract_date=f'{year}-03-15' if year else None,
                close_date=f'{year}-06-15' if year else None,
                analysis_end=end, comparison_end='2031-06',
                approved_limit=None, approval_status='UNKNOWN',
                source_id='C2', overrides=deepcopy(overrides or {}))


def compound(s):
    s = deepcopy(s)
    s['id'] += '__compound'
    s['name'] += ' / 복합'
    s['rate'] = .07
    s['overrides'].update(delay_months=6, care_multiplier=1.2, stock_loss=.2, renew_extra=1500)
    return s


def run(s, case=None, policy=None):
    case = deepcopy(case if case is not None else load_case())
    policy = deepcopy(policy if policy is not None else load_policy())
    r = simulate(case, s, policy, [])
    r['scenario'] = deepcopy(s)
    r['constraint_results'] = evaluate(case, s, r, policy)
    r['input_hash'] = digest(dict(case=case, policy=policy, scenario=s))
    r['output_hash'] = digest(r)
    return r


def post_minimum(r):
    """현금에서 비상·미집행 출산·거래 예비자금을 남긴 차액의 매입 후 최저값."""
    close = r['close_date']
    rows = [dict(date=row['month']+'-말', free=row['free'])
            for row in r['rows'] if row['month'] >= close[:7]]
    rows += [dict(date=e['date'], free=e['free']) for e in r['events'] if e['date'] == close]
    return min(rows, key=lambda p: p['free'])


def closing(r):
    return next(e for e in r['events'] if e['event_id'].endswith('housing_closing'))


def contract(r):
    return next(e for e in r['events'] if e['event_id'].endswith('housing_contract'))


def legacy_loan_boundary(year, *, upper=75000):
    """본문의 2031.6 잔금/월말 역산 재현. 은행 승인·계약 단계는 별도다.

    이 고정 금리·지출 모델에서 필요자금을 남긴 현금 차액의 기울기는
    1-(납입횟수+6)*PMT(1) 이상이다. 양의 하한을 확인한 범위만 이분탐색한다.
    계약 전 자금은 역산에서 제외한다.
    """
    lo, hi = Decimal(0), Decimal(upper)
    cache = {}
    payments=(2031-year)*12+1
    slope_lower=Decimal(1)-Decimal(payments+6)*pmt(1,.05,360)
    if slope_lower<=0:
        raise ValueError('이 분석구간에서는 필요자금을 남긴 현금 차액의 단조 증가를 입증하지 못했습니다.')
    def margin(loan):
        key=str(loan)
        if key not in cache:
            r=run(scenario(f'boundary_{year}',year,75000,float(loan),end='2031-06'))
            cache[key]=post_minimum(r)['free']
        return Decimal(str(cache[key]))
    if margin(lo)>=0:
        return dict(year=year,loan=0,one_less_margin=None,boundary_margin=float(margin(lo)),
                    monotonic_slope_lower=float(slope_lower),scope='대출0 수치 통과. 계약/은행 승인은 별도')
    if margin(hi)<0:
        raise ValueError('명시한 역산 상한에서도 비상·목적자금을 모두 남길 수 없습니다.')
    for _ in range(55):
        mid=(lo+hi)/2
        if margin(mid)>=0: hi=mid
        else: lo=mid
    amount=int(hi.to_integral_value(rounding=ROUND_CEILING))
    return dict(year=year,loan=amount,one_less_margin=float(margin(Decimal(amount-1))),
                boundary_margin=float(margin(Decimal(amount))),
                monotonic_slope_lower=float(slope_lower),
                scope='2031.6까지 잔금·매입 후 월말의 비상·목적자금 전액 유지; 계약/은행 승인은 별도')


def school_sensitivity(base, extra, *, include_in_reserve=True):
    s=deepcopy(base)
    s['id'] += f'__school_net_plus_{extra}'
    s['name'] += f' / 취학 후 순증 +{extra}'
    s['overrides'].setdefault('extra_expenses',[]).append(dict(
        start='2035-03',end='2036-06',amount=extra,inflate=False,
        include_in_reserve=include_in_reserve,
        source_id='SCHOOL_TEST',value_kind='model_assumption',verification_status='unreviewed',
        note='기존 예산 대비 취학 후 순증의 민감도 가정. 실제 교육·돌봄 견적 아님'))
    return s
