"""1107-규리 월별 조건부 시뮬레이션. 단위 만원, 표준 라이브러리만 사용."""
import csv, json, math
from pathlib import Path

OUT = Path(__file__).resolve().parent
def idx(y,m): return (y-2026)*12+m-11
def label(t):
    n=2026*12+10+t
    return f'{n//12:04d}-{n%12+1:02d}'
END=idx(2031,6)
F=lambda t:1.02**(t/12)
BIRTH={}
def put(y,m,v): BIRTH[idx(y,m)]=BIRTH.get(idx(y,m),0)+v
for m in (4,5,6): put(2027,m,50/3)
for t in range(idx(2027,8),idx(2028,3)+1): BIRTH[t]=BIRTH.get(t,0)+150/8
put(2027,12,50)
put(2028,2,125); put(2028,3,200)
put(2028,4,550); put(2028,5,255)
assert abs(sum(BIRTH.values())-1380)<1e-8
VOUCH={}; remaining=100
for t in range(idx(2027,8),idx(2028,3)+1):
    use=min(remaining,150/8*F(t)); VOUCH[t]=use; remaining-=use
VOUCH[idx(2028,4)]=200
def pmt(loan,rate):
    r=rate/12
    return loan*r/(1-(1+r)**-360)

def costs(price):
    assert 60000<=price<=90000
    tax_rate=(price/10000*2/3-3)/100
    return price*tax_rate*1.1+price*.0044+900

def simulate(year,loan,rate=.05,delay=False,care=1,parents=False,deposit=0,renew=False,stock=.0,price=75000,end=END):
    close=idx(year,6); contract=close-3; sale=contract-1
    cash=8000.; shares=2500.; pension=1500.; debt=0.; settlement=0.; reserve=3100.; rows=[]; events=[]
    payment=pmt(loan,rate); extra_dep=0
    for t in range(1,end+1):
        opening=cash; transaction=0.; receipt=0.
        if t==sale: receipt+=2500*(1-stock); shares=0
        if t==close-1 and not parents: receipt+=10000
        if t==close+3 and parents: receipt+=10000
        cash+=receipt
        adult=480 if t<idx(2028,4) else 405
        child=0 if t<idx(2028,4) else 80
        prenatal=8 if idx(2027,12)<=t<=idx(2028,3) else 0
        childcare=(20 if idx(2028,7)<=t<=idx(2029,5) else 60 if t>=idx(2029,6) else 0)*care
        nursery=10 if t>=idx(2029,6) else 0
        owned=t>=close
        living=(adult-30+child+prenatal+childcare+nursery+(10 if owned else 0))*F(t)+(0 if owned else 30)
        if deposit and close<=t<close+deposit: living+=30
        # 비상현금은 하향하지 않으며 자가의 원리금까지 포함한다.
        target=(3400 if t>=idx(2029,6) else 3100)*F(t)
        reserve=max(reserve,target,6*(living+payment) if owned else 0)
        future_birth=sum(v*F(k)-VOUCH.get(k,0) for k,v in BIRTH.items() if k>=t)
        birth_buffer=120*F(t) if t<=idx(2028,5) else 0
        earmark=future_birth+birth_buffer+settlement+(200 if owned else 0)
        if t==contract:
            down=price*.1
            events.append(dict(date=f'{year}-03-15',event='계약금',cash_before=cash,amount=down,cash_after=cash-down,reserve=reserve,future_birth_cash=future_birth,birth_buffer=birth_buffer,settlement_balance=settlement,trade_buffer=0,earmark=earmark,free=cash-down-reserve-earmark))
            cash-=down; transaction-=down
        if renew and year>2027 and t==idx(2028,6):
            cash-=1500; transaction-=1500; extra_dep=1500
        if t==close:
            returned=20000+extra_dep if deposit==0 else 0
            due=price*.9+costs(price)
            cash+=returned+loan-due
            transaction+=returned+loan-due; debt=loan
            events.append(dict(date=f'{year}-06-15',event='잔금과 부대비용 전액',cash_before=cash-(returned+loan-due),amount=due,cash_after=cash,reserve=reserve,future_birth_cash=future_birth,birth_buffer=birth_buffer,settlement_balance=settlement,trade_buffer=200,earmark=earmark,free=cash-reserve-earmark))
        if deposit and t==close+deposit:
            cash+=20000+extra_dep; transaction+=20000+extra_dep
        leave=idx(2028,7)<=t<=idx(2029,6)+(6 if delay else 0)
        if leave:
            n=t-idx(2028,7)+1
            wife=250 if n<=3 else 200 if n<=6 else 160 if n<=12 else 0
        else: wife=280
        support=110 if idx(2028,4)<=t<=idx(2029,3) else 60 if idx(2029,4)<=t<=idx(2029,5) else 10 if t>=idx(2029,6) else 0
        contribution=31.5 if leave else 0
        retention=5 if leave else 0
        gross_birth=BIRTH.get(t,0)*F(t); voucher=VOUCH.get(t,0)
        mortgage=payment if owned else 0
        income=570+wife+support
        net=income-living-contribution-100-(gross_birth-voucher)-mortgage
        cash+=net; pension+=100; settlement+=retention
        if owned: debt=debt*(1+rate/12)-payment
        # 이미 쓴 출산비를 다시 차감하지 않는다. 정산 유보 5는 비용이 아니다.
        future=sum(v*F(k)-VOUCH.get(k,0) for k,v in BIRTH.items() if k>t)
        earmark=future+(120*F(t) if t<idx(2028,5) else 0)+settlement+(200 if owned else 0)
        free=cash-reserve-earmark
        property_value=price if owned else 0
        rental_equity=(20000+extra_dep if not owned or (deposit and t<close+deposit) else 0)
        nw=cash+shares+pension+property_value+rental_equity-debt
        assert abs(cash-(opening+receipt+transaction+net))<1e-6
        rows.append(dict(month=label(t),opening_cash=opening,husband=570,wife=wife,cash_support=support,income=income,living=living,birth_gross=gross_birth,voucher=voucher,birth_cash=gross_birth-voucher,contribution=contribution,settlement_retained=retention,retirement=100,mortgage=mortgage,monthly_surplus=net,asset_receipts=receipt,transaction_flow=transaction,cash=cash,reserve=reserve,future_birth_cash=future,birth_buffer=(120*F(t) if t<idx(2028,5) else 0),settlement_balance=settlement,trade_buffer=(200 if owned else 0),earmark=earmark,free=free,mortgage_balance=debt,pension=pension,net_worth=nw))
    return dict(year=year,loan=loan,payment=payment,rows=rows,events=events,min_cash=min(rows,key=lambda r:r['cash']),min_free=min(rows,key=lambda r:r['free']),end=rows[-1])

def solve(year,**kw):
    lo,hi=0.,75000.
    for _ in range(70):
        mid=(lo+hi)/2; s=simulate(year,mid,**kw)
        # 계약금은 별도 판단한다. 미래 대출을 3월에 사용할 수 없다.
        close=f'{year}-06'
        margin=min([r['free'] for r in s['rows'] if r['month']>=close]+[s['events'][1]['free']])
        if margin>=0: hi=mid
        else: lo=mid
    return simulate(year,math.ceil(hi),**kw)

def write_csv(name,rows):
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def compact(s):
    return {k:s[k] for k in ('year','loan','payment','events','min_cash','min_free','end')}

if __name__=='__main__':
    base={y:solve(y) for y in (2027,2030,2031)}
    stress=[]
    cases={'복직6개월지연':dict(delay=True),'돌봄20%상승':dict(care=1.2),'금리7%':dict(rate=.07),'부모지원지연':dict(parents=True),'보증금30일지연':dict(deposit=1),'보증금90일지연':dict(deposit=3),'갱신1500추가':dict(renew=True),'주식20%하락':dict(stock=.2),'복직지연+7%':dict(delay=True,rate=.07),'복합스트레스':dict(delay=True,rate=.07,care=1.2,parents=True,deposit=3,renew=True,stock=.2)}
    for y,s in base.items():
        write_csv(f'월별현금흐름_{y}.csv',s['rows']); write_csv(f'거래일검증_{y}.csv',s['events'])
        for name,kw in cases.items():
            z=simulate(y,s['loan'],**kw)
            stress.append(dict(year=y,case=name,payment=z['payment'],min_cash=z['min_cash']['cash'],min_cash_month=z['min_cash']['month'],min_free=z['min_free']['free'],min_free_month=z['min_free']['month'],contract_free=z['events'][0]['free'],closing_cash=z['events'][1]['cash_after'],closing_free=z['events'][1]['free'],end_networth=z['end']['net_worth']))
    write_csv('스트레스테스트.csv',stress)
    (OUT/'계산결과.json').write_text(json.dumps({str(y):compact(s) for y,s in base.items()},ensure_ascii=False,indent=2))
    # 월 상환액, 지원금, 연금, 현금 보존 검산.
    assert abs(pmt(10000,.05)-53.6821623)<1e-5
    for y,s in base.items():
        assert abs(s['end']['pension']-(1500+END*100))<1e-7
        assert abs(sum(r['voucher'] for r in s['rows'])-300)<1e-7
        assert sum(r['cash_support'] for r in s['rows'])==1690
        assert sum(r['contribution'] for r in s['rows'])==378
        assert s['events'][0]['cash_before']<30000
    candidates=[]
    for y in (2030,2031):
        for price in (68000,70000):
            s=solve(y,price=price)
            z=simulate(y,s['loan'],price=price,delay=True,rate=.07)
            candidates.append(dict(year=y,price=price,closing_cost=costs(price),loan=s['loan'],payment=s['payment'],closing_free=s['events'][1]['free'],end_surplus=s['end']['monthly_surplus'],stress_min_free=min(z['min_free']['free'],z['events'][1]['free'])))
    write_csv('가격조정대안.csv',candidates)
    recommendation=simulate(2031,21700,price=63000)
    recommendation_stress=simulate(2031,21700,price=63000,delay=True,rate=.07,care=1.2,stock=.2,renew=True)
    write_csv('권고안_2031_6억3천_월별.csv',recommendation['rows'])
    write_csv('권고안_복합스트레스_월별.csv',recommendation_stress['rows'])
    (OUT/'권고안결과.json').write_text(json.dumps({'base':compact(recommendation),'stress':compact(recommendation_stress)},ensure_ascii=False,indent=2))
    assert abs(base[2030]['end']['cash']-simulate(2030,base[2030]['loan'],delay=True)['end']['cash']-1869)<1e-6
    assert abs(base[2030]['end']['cash']-simulate(2030,base[2030]['loan'],stock=.2)['end']['cash']-500)<1e-6
    assert recommendation_stress['events'][0]['free']>0
    assert recommendation_stress['events'][1]['free']>0
    assert recommendation_stress['min_free']['free']>0
    (OUT/'검증기록.txt').write_text('PASS: 집중지출 원금합계 1380 / 바우처 총사용 300 / 현금지원 합계 1690 / 기본 휴직기여금 378 / 연금잔액 7000 / 각 월 현금보존식 / 독립 월상환액 / 복직지연 현금감소 1869 / 주식하락 현금감소 500 / 권고안 비거래 복합스트레스 보호현금 유지\n단위 만원. 2026.12~2031.6 55개월. 날짜별 거래는 3월15일·6월15일 별도 평가. 대출승인 및 실제 증빙 검증은 미완료.\n',encoding='utf-8')
    print(json.dumps({str(y):{'loan':s['loan'],'payment':s['payment'],'contract':s['events'][0],'closing':s['events'][1],'min_free':(s['min_free']['month'],s['min_free']['free']),'end':s['end']} for y,s in base.items()},ensure_ascii=False,indent=2))
