"""합본2 원수치와 취학 순증 민감도를 재현하고 장부·검증기록을 생성한다."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import sys

from 계산모델 import (ROOT, load_case, load_policy, scenario, compound, run,
                    closing, contract, post_minimum, legacy_loan_boundary, school_sensitivity)
from afpk.config import validate_inputs
from afpk.storage import write_json, write_csv, digest
from afpk.finance import acquisition_costs


def table(headers, rows):
    return '| '+' | '.join(headers)+' |\n|'+'|'.join(['---']*len(headers))+'|\n'+''.join(
        '| '+' | '.join(str(x) for x in row)+' |\n' for row in rows)


def fmt(value):
    """보고서만 만 원 단위 반올림. 계산·원자료에는 적용하지 않는다."""
    return f'{Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP):,}'


def won(value):
    return int((Decimal(str(value))*10000).quantize(Decimal(1),rounding=ROUND_HALF_UP))


def build_scenarios(boundaries=None):
    cases=[]
    boundaries=boundaries or [legacy_loan_boundary(year) for year in (2027,2030,2031)]
    for boundary in boundaries:
        year,loan=boundary['year'],boundary['loan']
        s=scenario(f'base_{year}',year,75000,loan,end='2031-06'); s['name']=f'{year}년 7.5억·원기간'
        cases.append(s)
        z=deepcopy(s);z['id']=f'post_{year}';z['name']=f'{year}년 7.5억·매입 후5년';z['analysis_end']=f'{year+5}-06'; cases.append(z)
    for price,loan in ((63000,21700),(60000,19000),(58000,19000),(56000,19000),(56000,14500)):
        sid=f'price_{price}_loan_{loan}';s=scenario(sid,price=price,loan=loan);s['name']=f'{price/10000:g}억·대출{loan/10000:g}억'
        cases.extend((s,compound(s)))
    preferred=next(s for s in cases if s['id']=='price_56000_loan_14500')
    stress=[
        ('leave',{'delay_months':6},None),('care',{'care_multiplier':1.2},None),
        ('rate',{},.07),('parent_delay',{'parent_support_month':'2031-09'},None),
        ('deposit_1',{'deposit_delay_months':1},None),('deposit_3',{'deposit_delay_months':3},None),
        ('renew',{'renew_extra':1500},None),('stock',{'stock_loss':.2},None),
        ('leave_rate',{'delay_months':6},.07)]
    for name,overrides,rate in stress:
        s=deepcopy(preferred);s['id']='preferred__'+name;s['name']='우선안 '+name;s['overrides'].update(overrides)
        if rate is not None:s['rate']=rate
        cases.append(s)
    combo=compound(preferred)
    for amount in (5,20,50):
        cases.append(school_sensitivity(combo,amount,include_in_reserve=True))
    rent=scenario('rent_only',year=None,price=0,loan=0,end='2031-06');rent['name']='임차 유지 대표월';cases.append(rent)
    return cases


def main():
    output=ROOT/'outputs';output.mkdir(exist_ok=True)
    case,policy=load_case(),load_policy()
    boundary=[legacy_loan_boundary(year) for year in (2027,2030,2031)]
    scenarios=build_scenarios(boundary)
    write_json(ROOT/'inputs'/'scenarios.json',dict(schema_version='1.0',scenarios=scenarios,stress_templates=[]))
    bundle=dict(case=case,policy=policy,scenarios=scenarios,events=[],stress_templates=[],ai_usage={})
    validation=validate_inputs(bundle)
    errors=[x for x in validation if x['severity']=='ERROR']
    if errors:raise ValueError(errors)
    results={s['id']:run(s,case,policy) for s in scenarios}
    write_json(output/'전체계산결과.json',results)
    comparisons=[]
    for sid,r in results.items():
        write_csv(output/f'{sid}_월별.csv',r['rows'])
        write_csv(output/f'{sid}_거래일.csv',r['events'])
        write_csv(output/f'{sid}_등록사건.csv',r['event_rows'])
        if r['year'] is None:continue
        c=closing(r); k=contract(r);p=post_minimum(r)
        comparisons.append(dict(scenario_id=sid,name=r['scenario_name'],price=r['price'],loan=r['loan'],rate=r['rate'],analysis_end=r['analysis_end'],
            payment=r['payment'],contract_cash=k['cash_after'],contract_free=k['free'],closing_cash=c['cash_after'],closing_free=c['free'],
            post_min_free=p['free'],post_min_at=p['date'],ending_surplus=r['end']['monthly_surplus'],
            post_first_monthend_breach=(r['metrics']['post_purchase_first_monthend_protected_breach'] or {}).get('month'),
            school_extra_nominal=r['scenario'].get('overrides',{}).get('extra_expenses',[]),
            customer_approved=False))
    write_csv(output/'대안_스트레스_요약.csv',comparisons)
    preferred=results['price_56000_loan_14500'];combined=results['price_56000_loan_14500__compound']
    key_metrics={
        'birth_cash':sum(r['birth_cash'] for r in preferred['rows']),
        'base_closing_cash':closing(preferred)['cash_after'],
        'compound_post_min_free':post_minimum(combined)['free'],
        'compound_ending_surplus':combined['end']['monthly_surplus'],
        'base_common_networth':preferred['metrics']['comparison_row']['net_worth'],
        'compound_common_networth':combined['metrics']['comparison_row']['net_worth'],
        'pension_2031_06':preferred['metrics']['comparison_row']['pension'],
        'pension_2036_06':preferred['end']['pension'],
    }
    expected={'birth_cash':1117,'base_closing_cash':8038,'compound_post_min_free':941,
              'compound_ending_surplus':2,'base_common_networth':56651,
              'compound_common_networth':53890,'pension_2031_06':7000,'pension_2036_06':13000}
    check=[dict(metric=k,source_display=v,calculated=key_metrics[k],difference=key_metrics[k]-v,
                tolerance=.5000001,status='PASS' if abs(key_metrics[k]-v)<=.5000001 else 'FAIL') for k,v in expected.items()]
    write_csv(output/'대출역산_경계.csv',boundary)
    write_json(output/'검증결과.json',dict(input_checks=validation,source_display_checks=check,loan_boundaries=boundary,
        source_boundary_expected=[41414,33286,31304],
        source_revision='Tab31 고정 정산유보 삭제·금액처리주의점 반영',
        numeric_source_status='PASS' if all(c['status']=='PASS' for c in check) and [b['loan'] for b in boundary]==[41414,33286,31304] else 'FAIL'))
    metadata=dict(created_at=datetime.now(timezone(timedelta(hours=9))).isoformat(),case_id=case['case_id'],
        input_hash=digest(bundle),result_hash=digest(results),scenarios=len(results),
        source_snapshot='source/Tab31_수정기준.md',
        original_source_snapshot='source/합본2_원문스냅샷.txt',
        reserve_rule='max(previous_reserve,6*(living+mortgage+necessary_recurring_extra))',
        amount_unit='만원',source_check='PASS' if all(c['status']=='PASS' for c in check) else 'FAIL')
    metadata['display_rule']='보고서: 만원 단위 반올림, 비율 소수1자리. 원단위 납부표 별도. JSON/CSV 계산원자료 무반올림.'
    metadata['fixed_settlement_retention']=False
    write_json(output/'실행정보.json',metadata)
    # 납부액 표시용 원 단위 자료. 계산 장부에는 이 표시값을 되먹이지 않는다.
    tax_rows=[];repayment_rows=[]
    for sid,r in results.items():
        if r['year'] is None:continue
        cost=acquisition_costs(r['price'],policy)
        tax_rows.append(dict(scenario_id=sid,price_won=won(r['price']),
            **{name+'_won':won(value) for name,value in cost['components'].items() if not name.endswith('_rate')},
            total_won=won(cost['total']),note='가상 사례 산식의 원 단위 표시; 실제 신고세액·견적 미확정'))
        previous=Decimal(str(r['loan']));rate=Decimal(str(r['rate']))/12
        for row in r['rows']:
            if row['month']<r['close_date'][:7]:continue
            payment=Decimal(str(row['mortgage']));interest=previous*rate
            principal=payment-interest if payment else Decimal(0)
            repayment_rows.append(dict(scenario_id=sid,month=row['month'],
                opening_principal_won=won(previous),payment_won=won(payment),
                interest_won=won(interest),principal_won=won(principal),
                closing_principal_won=won(row['mortgage_balance']),
                note='무반올림 모형의 원 단위 표시; 은행 확정 상환표 아님'))
            previous=Decimal(str(row['mortgage_balance']))
    write_csv(output/'원단위_취득비용.csv',tax_rows)
    write_csv(output/'원단위_원리금상환표.csv',repayment_rows)
    write_json(ROOT/'inputs'/'취학후_예산확인표.json',{
        'status':'UNKNOWN','expected_school_start':'2035-03','child_birth_month':'2028-04',
        'entry_rule_note':'일반적인 정상 취학을 전제한 시점. 실제 입학일·유예 등 확인 필요.',
        'known_pre_school_fee_base2026':10,
        'school_fee_nominal':None,'school_meal_increment_nominal':None,
        'care_hours':None,'care_price_quote':None,'education_materials_nominal':None,
        'nursery_fee_end':'2035-02',
        'replacement_rule':'실제 학교·급식·교육·돌봄 견적을 확인하면 어린이집10을 종료하고 항목별 예산으로 대체한다. 기존80·60에서 겹치는 비용도 제거한다.',
        'sensitivity_only':{'net_extra_monthly':[5,20,50],'start':'2035-03','end':'2036-06','nominal':True,'include_in_emergency_reserve':True},
        'note':'순증 금액은 실제 학령기 평균·최저비용이 아닌 취약성 시험 가정이다.'})
    school=[row for row in comparisons if '__school_net_plus_' in row['scenario_id']]
    sensitivity=[]
    for row in school:
        extra=row['school_extra_nominal'][0]['amount']
        r=results[row['scenario_id']]
        first_negative=next((v for v in r['rows'] if v['month']>='2035-03' and v['monthly_surplus']<0),None)
        sensitivity.append([extra,fmt(row['post_min_free']),row['post_min_at'],fmt(row['ending_surplus']),first_negative['month'] if first_negative else '기간내 없음'])
    md='''# Tab31 반영 4단계 계산부록

기준: 현재 생활비 450·준비여력 300·초기 비상현금 2,700. 표의 금액 단위는 만 원이며 정수로 반올림했다. 내부 계산과 JSON·CSV 원자료에는 중간 반올림을 적용하지 않는다. 비율은 소수 첫째 자리, 세금·원리금 납부 표시는 별도 원 단위 CSV로 제공한다.

월 5만 원의 정산 유보 가정을 삭제했다. 정산액을 미리 확정하거나 소득에 월 5만 원을 더하지 않는다. 실제 건강보험료·정산액은 금액과 납부일이 확인되면 별도 지출 사건으로 기록한다. 같은 가격·대출안의 총현금·월수지·순자산은 그대로이며, 별도 배분을 막았던 기본 60·복직 지연 90이 해제된다.

현금에서 생활·돌봄비와 주택 원리금의 6개월분, 아직 쓰지 않은 출산비의 현금부담과 출산 예비비, 주택 취득 뒤 거래 예비비 200을 차례로 남긴 뒤 추가 배분할 수 있는 금액을 계산한다. 비상목표는 이전 달보다 낮추지 않는다. 이하 각 표는 남겨 둘 금액과 차액을 직접 표시한다.

## 1. 5.6억·대출 1.45억의 잔금 지급 후 자금 배분

'''+table(['상황','잔금 후 총현금','생활·원리금 6개월분','미집행 출산·출산예비비','거래예비비','모두 남긴 뒤 추가 배분액'],[
        [name,fmt(closing(r)['cash_after']),fmt(closing(r)['reserve']),
         fmt(closing(r)['future_birth_cash']+closing(r)['birth_buffer']),fmt(closing(r)['trade_buffer']),fmt(closing(r)['free'])]
        for name,r in [('기본',preferred),('복합',combined)]])+'''

기본은 현금 8,038 중 비상현금 3,982와 거래예비비 200을 남기고 약 3,856을 추가 배분할 수 있다. 복합상황은 현금 5,314 중 비상현금 4,173과 거래예비비 200을 남기고 약 941을 추가 배분할 수 있다. 출산비 집행이 끝난 잔금 시점의 미집행 출산비·출산예비비는 0이다. 이 차액을 반드시 소비한다는 뜻은 아니다. 향후 수선·교육비 등 확정 전에는 현금으로 유지한다.

2029.6 은퇴저축 후 월수지는 약 26이다. 종전의 월 5 유보 차감을 없애도 총현금 증가액은 그대로다. 바우처는 사용 가능한 비용만 줄이며 현금소득으로 더하지 않는다. 연금 월 100 이체는 현금을 줄이고 연금자산을 늘린다.

## 2. 7.5억 주택 구입시점과 최소 대출 재계산

'''+table(['구입연도','재산정 대출','월 원리금','계약금 후 필요자금 제외 차액','2031.6 월수지','매입 후 연장기간 최초 필요자금 부족월'],[
        [b['year'],fmt(b['loan']),fmt(results[f"base_{b['year']}"]['payment']),
         fmt(contract(results[f"base_{b['year']}"])['free']),fmt(results[f"base_{b['year']}"]['end']['monthly_surplus']),
         (results[f"post_{b['year']}"]['metrics']['post_purchase_first_monthend_protected_breach'] or {}).get('month','없음')]
        for b in boundary])+'''

대출은 2031.6까지 잔금일과 취득 후 월말에 비상·목적자금을 모두 남길 수 있는 최소 1만 원 단위 금액이다. 각 경계에서 1만 원을 줄이면 조건을 위반한다. 계약금과 은행 승인은 별도다. 2027년은 계약금 지급 뒤 약 58이 부족하므로 이후 대출로 계약일 부족을 소급 해결하지 않는다. 세 안 모두 매입 후 5년 연장기간에 필요자금 부족이 발생한다.

## 3. 가격·대출 조합 비교

'''+table(['가격','대출','기본 잔금 후 비상·목적자금 제외액','복합 매입 후 동일 제외액의 최저값','복합 종료월수지'],[
        [fmt(price),fmt(loan),fmt(closing(results[f'price_{price}_loan_{loan}'])['free']),fmt(post_minimum(results[f'price_{price}_loan_{loan}__compound'])['free']),fmt(results[f'price_{price}_loan_{loan}__compound']['end']['monthly_surplus'])]
        for price,loan in ((63000,21700),(60000,19000),(58000,19000),(56000,19000),(56000,14500))])+'''
복합은 복직 6개월 지연, 신규금리 7.0%, 유료 보조·공백돌봄 20.0% 상승, 주식매각가 20.0% 하락, 갱신보증금 1,500 증액이다. 부모지원·보증금 반환은 예정대로 입금된다는 조건이다. 돌봄비 상승은 월 20/60에만 적용한다. 가격 인하로 대출 원리금을 줄이면 반복 월수지가 개선되지만, 현금 잔액과 반복 월수지를 함께 확인해야 한다.

## 4. 취학 후 비용이 늘면 어떻게 되나

2028.4 출생아의 정상 취학을2035.3으로 가정한다. 실제 취학 후 예산은 아직 미확정이다. 기존 어린이집·영유아 예산을 그대로 연장한 본문 재현과 다음 취약성 시험을 구분한다.

아래는 기존 복합예산 대비 필요한 반복비용의 **순증**을2035.3~2036.6에 매월5·20·50 추가한 시험이다. 명목금액이며 물가를 다시 곱하지 않았다. 현금유출뿐 아니라 비상현금6개월분에도 포함했다. 실제 학교·돌봄 견적이나 평균교육비라는 뜻이 아니다.

'''+table(['월 순증','매입 후 비상·목적자금 제외액의 최저값','최저 시점','2036.6 월수지','취학 후 첫 월적자'],sensitivity)+'''
복합의 2036.6 월수지는 약 +2이며 취학 후 비용이 월 5 늘면 약 -3으로 바뀐다. 실제 학교 필요경비·돌봄시간·교육비를 확보한 뒤 어린이집 10을 종료하고 겹치는 양육·돌봄 항목을 정리하여 다시 계산한다. 확인표는 inputs/취학후_예산확인표.json에 남겼다.

## 5. 납부액 표시와 확인 범위

`outputs/원단위_취득비용.csv`는 취득세·지방교육세·중개보수·부가세·기타 예산을 원 단위로 표시한다. `outputs/원단위_원리금상환표.csv`는 분석기간의 월별 원리금·이자·원금·잔여원금을 원 단위로 표시한다. 이는 가상 사례의 무반올림 산식 표시이며 실제 세금고지서·은행 확정 상환표가 아니다. 계산 원자료와 표시값을 분리한다.

단위 미만 반올림으로 인해 세부 항목의 합과 총계가 일치하지 않을 수 있음. 총계는 반올림 전 원자료의 합계로 산정했다. 비상·목적자금 제외액이 음수여도 총현금이 음수라는 뜻은 아니다.

`python 전체재계산.py`로 모든 장부를 재생성하고 `python -m unittest discover -s tests -v`로 검사한다. 기존 source/합본2_원문스냅샷.txt는 변경 전 기록이며 현재 입력은 Tab31 수정 요청을 반영했다. 코드의 free/earmark/reserve는 호환용 장부 필드로, 보고서에서는 각 금액과 산정 방식을 풀어 표시한다.

등록한 계약·잔금 사건과 월말 합계만 계산한다. 모든 실제 날짜의 급여·지출, 대출 승인, 법령·수급 적격성, 매물 적합성, 노후 충분성은 확인 전이다. 지연시험 이후의 수치는 거래가 가상 진행된 경우의 참고값이다. 5.6억/1.45억은 비교한 조합 중 우선 검토안이며 확정 매입가능액이 아니다.
'''
    (ROOT/'계산부록.md').write_text(md,encoding='utf-8')
    write_json(output/'재계산요약.json',dict(
        key_metrics=key_metrics,boundaries=boundary,comparisons=comparisons,
        preferred_closing=closing(preferred),compound_closing=closing(combined),
        rent_representative_rows=[row for row in results['rent_only']['rows'] if row['month'] in
            ('2026-12','2027-12','2028-07','2028-10','2029-01','2029-04','2029-06','2029-07')],
        original_purchase_results={str(year):dict(payment=results[f'base_{year}']['payment'],
            contract=contract(results[f'base_{year}']),closing=closing(results[f'base_{year}']),
            ending_surplus=results[f'base_{year}']['end']['monthly_surplus'],
            first_breach=(results[f'post_{year}']['metrics']['post_purchase_first_monthend_protected_breach'] or {}).get('month'))
            for year in (2027,2030,2031)},school=sensitivity))
    print(json.dumps(dict(status=metadata['source_check'],scenarios=len(results),key_metrics=key_metrics,school=sensitivity,boundaries=boundary),ensure_ascii=False,indent=2))
    if any(c['status']!='PASS' for c in check):return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
