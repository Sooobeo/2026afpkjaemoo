"""2026.11.9 검토의견 반영: 원모델 재현과 매입 후 5년 고정구조 민감도."""
import json
from pathlib import Path
import verify_plan as v
P=Path(__file__).resolve().parent
def fmt(x): return f'{x:,.2f}'
def table(h,rows):
    return '\n| '+' | '.join(h)+' |\n|'+'|'.join(['---']*len(h))+'|\n'+''.join('| '+' | '.join(map(str,r))+' |\n' for r in rows)+'\n'
def first(rows,key):
    r=next((r for r in rows if r[key]<-1e-7),None)
    return None if r is None else dict(month=r['month'],value=r[key])
base={y:v.solve(y) for y in (2027,2030,2031)}
cases=[('2027_7.5억',2027,42189,75000,{}),('2030_7.5억',2030,33895,75000,{}),('2031_7.5억',2031,31869,75000,{}),('2031_6.3억_기본',2031,21700,63000,{}),('2031_6.3억_7%돌봄상승',2031,21700,63000,dict(rate=.07,care=1.2)),('2031_6.3억_비거래복합',2031,21700,63000,dict(delay=True,rate=.07,care=1.2,stock=.2,renew=True))]
summary=[]; detail={}
for name,y,loan,price,kw in cases:
    s=v.simulate(y,loan,price=price,end=v.idx(y+5,6),**kw)
    post=[r for r in s['rows'] if r['month']>=f'{y}-06']
    z=dict(case=name,start=f'{y}-06',end=s['end']['month'],first_monthly_deficit=first(post,'monthly_surplus'),first_monthend_protected_breach=first(post,'free'),first_monthend_cash_breach=first(post,'cash'),ending_surplus=s['end']['monthly_surplus'],ending_free=s['end']['free'],june2033_surplus=next((r['monthly_surplus'] for r in post if r['month']=='2033-06'),None))
    summary.append(z); detail[name]=s
    v.write_csv(f'보완검증_{name}_매입후5년.csv',s['rows'])
    v.write_csv(f'보완검증_{name}_거래일.csv',s['events'])
(P/'보완검증_연장결과.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
audit=[]
for y,s in base.items():
    for loan in (s['loan']-1,s['loan']):
        z=v.simulate(y,loan)
        post=[r for r in z['rows'] if r['month']>=f'{y}-06']
        candidates=[(r['month']+' 말',r['free']) for r in post]+[(z['events'][1]['date'],z['events'][1]['free'])]
        bind=min(candidates,key=lambda x:x[1])
        audit.append(dict(year=y,loan=loan,minimum_protected_margin=bind[1],binding_date=bind[0],contract_margin=z['events'][0]['free']))
v.write_csv('보완검증_대출역산경계.csv',audit)
text='''# 4단계 보완 검증 부록

검증일: 2026.11.9. 단위 만 원. 기존 파일의 계산을 재현하고, 검토의견에 따라 매입 후 5년의 고정구조 민감도를 추가했다. 로컬의 원설정표와 계산 코드, 사용자가 전달한 검토문을 기준으로 했다. 연결된 Google Docs 본문은 접근하지 못했으므로 문서의 추가 수정 여부까지 대조한 것은 아니다.

## 1. 원모델의 범위와 보완 가정

- 초기 현금 8,000·주식 2,500·연금 1,500을 2026.11 말 잔액으로 간주하고 12월부터 계산한다. 전세 순지분 20,000과 미입금 증여를 계약금에 쓰지 않는다.
- 2028.4~5는 성인 405+아이 80을 적용했다. 식비·청소비 감액은 **0**으로 두었다. 이는 실제 집행내역이 없어서 둔 보완 가정이며 설정표가 확정한 조정액이 아니다.
- 주식 매각월은 각 계약 전월인 2027.2/2030.2/2031.2이며 월말까지 결제 완료한 것으로 가정한다. 양도세·수수료 미확정분은 0으로 둔 기준값이다.
- 계약일 3.15에는 2월 말 잔액만 사용한다. 잔금일 6.15에는 5월 말 잔액과 당일 순보증금·승인대출을 사용한다. 대출 첫 상환은 취득월 6월에 월납입 전액을 차감한다. 실제 급여일·상환일과 다를 수 있다.
- 주담대 원리금과 명목 전세이자 30은 물가상승 대상이 아니다. 생활·돌봄·출산비 및 자가 유지비 10은 연 2%로 환산한다.
- 부대비용은 전액 잔금일 지출, 거래 여유 200은 미사용 현금 보유로 처리했다. 실제 선지급 비용은 거래일 장부에 추가해야 한다.

## 2. 보호자금 구성과 역산

월말 보호여유 = 총현금 − 비상현금 − 미집행 출산비의 순현금부담 − 출산 여유현금 − 정산 유보 − 거래 여유현금.

비상현금은 물가환산한 3,100(2029.5까지) 또는 3,400(2029.6부터), 자가 취득 후 6×(생활·돌봄비+주담대 월 원리금), 과거 비상목표 중 최댓값이다. 은퇴저축은 이 6개월분 기준에서 제외한다. **대출원금을 바꿀 때마다 월 원리금과 비상현금 목표도 다시 계산한다.**

미집행 출산비는 이후 실제 지급할 예정비용에서 사용할 바우처를 뺀 금액이다. 출산 여유 120은 물가를 적용해 2028.5 집행 종료 전까지 보호하고 그 뒤 해제하는 보완 가정이다. 정산 유보는 휴직 1개월마다 5씩 누적하고 실제 청구가 확인되지 않아 종료까지 보유한다. 기본 60, 6개월 지연 시 90이다. 거래 여유 200은 자가 취득일부터 보유한다. 각각의 월말 잔액을 CSV의 future_birth_cash / birth_buffer / settlement_balance / trade_buffer 열로 분리했다.

필요 대출 L은 단순 매매대금 차액이 아니라, 원모델의 2031.6까지 **잔금일과 취득 후 모든 월말 보호여유가 0 이상인 최소 L**이다. 계약금 제약은 대출 역산에서 별도 평가한다. 0~75,000 범위에서 이분 탐색 후 1만 원 단위 올림했다. 이 금액은 장기 적정 대출이나 은행 승인액이 아니다.

역산 경계는 대출을 1만 원 줄였을 때 제약을 통과하는지 비교했다.
'''
text+=table(['구입연도','대출액','최저 보호여유','제약 발생일','계약일 보호여유'],[[r['year'],fmt(r['loan']),fmt(r['minimum_protected_margin']),r['binding_date'],fmt(r['contract_margin'])] for r in audit])
text+='''2027년은 위 역산을 통과해도 계약일 보호여유가 음수이므로 전체 실행가능안을 구성하지 못한다. 2030·2031도 짧은 원분석 구간의 경계 금액이므로 장기 상환 안정성을 의미하지 않는다.

## 3. 계약·잔금일과 보호현금 구성
'''
for name in ('2031_6.3억_기본','2031_6.3억_비거래복합'):
    s=detail[name]; text+=f'\n### {name}\n'
    text+=table(['사건','지급 전 현금','계약금/잔금+비용','지급 후 현금','비상현금','남은출산비','출산여유','정산유보','거래여유','보호여유'],[[e['date']]+[fmt(e[k]) for k in ['cash_before','amount','cash_after','reserve','future_birth_cash','birth_buffer','settlement_balance','trade_buffer','free']] for e in s['events']])
text+='''잔금일 지급 전 현금은 당일 순보증금·대출 유입 전이다. 전체 자금식은 `지급전 현금+전세 순반환액+주담대−잔금−부대비용=지급후 현금`이다. 비거래 복합상황에서는 갱신 증액분 1,500도 반환되므로 순반환액은 21,500이다. 지원금 지연이나 보증금 지연을 함께 통과한 결과가 아니다.

## 4. 6.3억 부대비용

일반세율·중과 없음·전용 85㎡ 이하·감면 전 조건이다. 취득세 756+지방교육세 75.6+중개보수 및 부가세 277.2+등기·이사·최소수리 예산 900=**2,008.8**. 7.5억용 2,880을 그대로 적용하지 않았다. 900은 거래월 잠정 명목예산으로 유지하고 추가 물가환산은 하지 않았다. 향후 견적 변경 시 재계산한다. 거래 여유 200은 이 비용에 포함하지 않는다.

부모 지원 10,000은 양가가 각각 자기 자녀에게 5,000을 증여하고 각 수증자가 최근 10년 직계존속 공제를 사용하지 않았다는 원설정 전제다. 실제 과거 증여 확인 전 세금 0이 확정된 것은 아니다. 출산가구 취득세 감면은 세 안 모두 기본 계산에서 제외했다. 날짜상 검토 대상이라는 원설정과 실제 적용·환급 확정은 구분하고, 법령과 거주·주택수·신청 요건 및 지방교육세를 거래 전 확인한다.

## 5. 매입 후 5년 고정구조 민감도

2031.6은 원모델의 공통 순자산 비교시점으로 유지한다. 별도 연장 장부는 각 취득월부터 5년 뒤 6월까지 계산했다. 원대출액을 고정했으며 연장기간에 맞춰 필요 대출을 재역산하지 않았다. 2027년은 계약금 문제가 해소되었다는 가상 진행이다.

**연장구간은 예측이 아니다.** 명목급여·현금지원 10·양육/어린이집/돌봄 구성·연금 납입 100을 그대로 두고 생활비에 연 2% 물가를 적용한 기계적 민감도다. 아동의 성장, 취학, 돌봄시간, 지원 대상 연령·정책, 승급·임금상승, 실제 세금·수선은 반영하지 않았다. 지원 10의 유지도 수급확정이 아닌 고정구조 가정이다. 따라서 실제 향후 지출계획으로 대체해야 한다.
'''
def shown(z): return '기간 내 없음' if z is None else z['month']+' ('+fmt(z['value'])+')'
text+=table(['대안','연장 종료','첫 월적자','첫 월말 보호기준 위반','종료월 월수지'],[[z['case'],z['end'],shown(z['first_monthly_deficit']),shown(z['first_monthend_protected_breach']),fmt(z['ending_surplus'])] for z in summary])
text+='''2031년 6.3억 안에서 금리 7%·돌봄비 20% 상승을 유지하면 2033.6 월수지는 약 −7.54다. 복직 지연·주식 하락·보증금 증액까지 함께 적용한 복합상황에서는 2031.6 잔금일 보호여유 30.54를 재현했지만, 2033.7 월말 보호기준을 처음 위반한다. 이는 실제 현금이 0 미만이라는 뜻과 다르다. 같은 기간 총현금 음수 여부는 JSON에 별도 기록했다.

결론: 6.3억·대출 21,700을 **최종 권고안에서 추가 검토 대안으로 변경**한다. 단기 계산 통과를 장기 안정성으로 표현하지 않는다. 주택 조건과 추가 준비현금을 먼저 조정하고 실제 연령별 양육·교육비, 인정소득·대출승인, 수선·세금 견적을 확보해 재검증한다. 임금상승이나 추가대출을 자동으로 넣어 부족액을 해소하지 않는다. 월 100 은퇴저축 유지 여부만 확인하며 노후 충분성은 별도 장기 분석 대상이다.

## 6. 재현 방법

`python3 verify_plan.py`로 원모델 장부를 갱신한 후 `python3 feedback_audit.py`로 이 부록과 연장 장부를 생성한다. 기존 55개월 장부에는 보호자금 세부 열을 추가했다. 거래일 CSV는 보호자금 항목별 잔액을 포함한다. 연장 JSON은 최초 월적자·보호기준 위반·총현금 부족을 분리한다. 원모델의 1만 원 단위 대출 경계 통과와 잔액 보존식 등을 재검산했다. 수치 재현과 원가정의 현실 적합성·실제 증빙 확인은 구분한다.
'''
(P/'4단계_보완검증_계산부록.md').write_text(text,encoding='utf-8')
assert abs(v.costs(63000)-2008.8)<1e-7
z=detail['2031_6.3억_비거래복합']
assert abs(z['events'][1]['free']-30.542698275844486)<1e-6
assert abs(next(r['monthly_surplus'] for r in z['rows'] if r['month']=='2033-06')+7.538612434324648)<1e-6
print(json.dumps(summary,ensure_ascii=False,indent=2))
