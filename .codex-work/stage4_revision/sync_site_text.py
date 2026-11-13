from pathlib import Path

site = Path(__file__).resolve().parents[2] / 'stage6_monitoring' / 'site'
app = site / 'dist/app.js'
text = app.read_text(encoding='utf-8')
for old, new in {
    'money(m.endingNet,1)': 'money(m.endingNet)',
    'money(m.minFree,1)': 'money(m.minFree)',
    'money(m.monthlyPayment,1)': 'money(m.monthlyPayment)',
    'money(m.therapyFutureTotal,1)': 'money(m.therapyFutureTotal)',
    'num(a.amount,1)': 'num(a.amount)',
    'num(r.cash,1)': 'num(r.cash)',
    'num(r.free,1)': 'num(r.free)',
    'num(r.protected,1)': 'num(r.protected)',
    '${signed(diff)}': '${signed(diff,2)}',
    'const imported=S.importJSON(content);': 'const imported=S.withCalculationSource(S.importJSON(content),E.meta);',
    "BASELINE_REGISTERED:'점검 기준 등록'": "CALCULATION_SOURCE_UPDATED:'계산 기준 갱신',BASELINE_REGISTERED:'점검 기준 등록'",
    '가상 사례 · 합본2 450 기준 · 금액 단위: 만 원': '가상 사례 · 합본2 450 기준 · 고정 정산유보 제외 · 결과: 정수 만 원',
    '기존 계산에 확인한 변화만 더해 보는 매입 전 시연입니다.': '결과는 반올림 전 금액으로 계산하며, 항목을 반올림한 합과 총계가 다를 수 있습니다. 기존 계산에 확인한 변화만 더해 보는 매입 전 시연입니다.',
}.items():
    assert old in text, old
    text = text.replace(old, new)
app.write_text(text, encoding='utf-8')
index = site / 'dist/index.html'
text = index.read_text(encoding='utf-8')
for name in ['reference-data.js', 'engine.js', 'store.js', 'app.js']:
    text = text.replace(f'src="{name}"', f'src="{name}?v=20261113-no-retention-2"')
index.write_text(text, encoding='utf-8')
print('Updated display, import provenance, source note, and asset versions.')
