"""작업공간 원본에서 합본2 재현 프로필을 준비한다. 일반 실행에는 필요 없다."""
from pathlib import Path
import shutil
import json
import hashlib

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
for name in ('afpk', 'inputs', 'source', 'tests'):
    (OUT / name).mkdir(parents=True, exist_ok=True)
manifest = {}
for name in ('__init__.py', 'config.py', 'finance.py', 'engine.py', 'storage.py', 'constraints.py'):
    origin = ROOT / 'stage4_system' / 'afpk' / name
    manifest[str(origin.relative_to(ROOT))] = hashlib.sha256(origin.read_bytes()).hexdigest()
    shutil.copy2(origin, OUT / 'afpk' / name)
shutil.copy2(ROOT / '.codex-work' / 'combined2' / 'source.txt', OUT / 'source' / '합본2_원문스냅샷.txt')
for name in ('case.json', 'policy_rules.json', 'events.csv', 'ai_usage.json'):
    shutil.copy2(ROOT / 'stage4_system' / 'inputs' / name, OUT / 'inputs' / name)
(OUT / 'source' / '복사원본_해시.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

engine = OUT / 'afpk' / 'engine.py'
text = engine.read_text(encoding='utf-8')
text = text.replace('D(income["settlement_retention"]) if leave else ZERO',
                    'D(income.get("settlement_retention", 0)) if leave else ZERO')
old = '''        target = D(budget["emergency_later"] if month >= dates["nursery_start"] else budget["emergency_initial"]) * F(month)
        reserve = max(reserve, target, 6 * (living + mortgage) if owned else ZERO)'''
new = '''        # 합본2: 고정 하한 3100/3400 대신 매월 모델 지출의 6개월분.
        # 은퇴저축과 집중 출산비는 제외하며 이전 목표보다 내리지 않는다.
        reserve_extra_expense = ZERO
        for extra in overrides.get("extra_expenses", []):
            first = extra.get("start", extra.get("month"))
            last = extra.get("end") or first
            if extra.get("include_in_reserve", False) and first and first <= month <= last:
                reserve_extra_expense += D(extra["amount"]) * (F(month) if extra.get("inflate", False) else 1)
        reserve = max(reserve, D(6) * (living + mortgage + reserve_extra_expense))'''
assert old in text, '원본 엔진의 비상목표 규칙이 변경되어 패치를 중단합니다.'
text = text.replace(old, new)
row_marker = '"custom_operating_flow": custom_operating, "monthly_surplus": full_net,'
assert row_marker in text
text = text.replace(row_marker, '"reserve_extra_expense": reserve_extra_expense, ' + row_marker)
engine.write_text(text, encoding='utf-8')

case = json.loads((OUT / 'inputs' / 'case.json').read_text(encoding='utf-8'))
case['case_id'] = 'kim-lee-combined2-450-2026'
case['income'].pop('settlement_retention', None)
config = OUT / 'afpk' / 'config.py'
config.write_text(config.read_text(encoding='utf-8').replace(
    '("husband", "wife", "leave_contribution", "settlement_retention")',
    '("husband", "wife", "leave_contribution")'), encoding='utf-8')
case['budget']['adult_before'] = 450
case['budget']['emergency_initial'] = 2700
case['budget']['emergency_later'] = 2700  # 호환 필드이며 복사 엔진의 동적 규칙에서 사용하지 않음
case['assumptions']['reserve_rule'] = 'nondecreasing_six_month_living_plus_mortgage'
case['sources'].append({
    'source_id': 'C2', 'title': '1~5단계 합본2',
    'path_or_url': 'https://docs.google.com/document/d/1FFDyGXzR25NgBZ-fxijBPt8g2lSlLKEExJjPv9n1_hY/edit?tab=t.rlomp3j1ky20',
    'locator': '§2.3·4.1~5.4', 'checked_at': '2026-11-13', 'effective_date': None})
case['sources'].append({
    'source_id':'SCHOOL_TEST','title':'취학 순증 민감도 가정',
    'path_or_url':'취학후_예산확인표.json','locator':'2035.03~2036.06 순증5/20/50·명목·비상목표포함',
    'checked_at':'2026-11-13','effective_date':None})
case['provenance']['budget'] = {
    'source_id': 'C2', 'value_kind': 'fictional_case_setting', 'verification_status': 'source_matched',
    'checked_at': '2026-11-13', 'actual_evidence': False}
case['provenance']['assumptions'] = {
    'source_id': 'C2', 'value_kind': 'model_assumption', 'verification_status': 'source_matched',
    'checked_at': '2026-11-13', 'actual_evidence': False}
case['provenance']['school_sensitivity'] = {
    'source_id':'SCHOOL_TEST','value_kind':'model_assumption','verification_status':'unreviewed',
    'checked_at':'2026-11-13','actual_evidence':False}
case['support_schedule'][-1]['end'] = '2036-06'
case['support_schedule'][-1]['limitation'] = '합본2 종료월까지의 사례 가정. 실제 제도·수급 요건 확인은 별도.'
case['limitations'] = [
    '가상 사례450/300/초기2700 기준. 기존480/270/3100 결과와 혼용하지 않음.',
    '기본 재현은 취학 후에도 기존 영유아 비용을 연장한 고정구조 민감도.',
    '별도 취학시험은 확정 비용이 아닌 시험 가정이며 실제 예산은 UNKNOWN.']
(OUT / 'inputs' / 'case.json').write_text(json.dumps(case, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
policy = json.loads((OUT / 'inputs' / 'policy_rules.json').read_text(encoding='utf-8'))
policy['policy_version'] = 'combined2-450-snapshot-2026-11-13-v1'
policy['rules']['reserve_rule'] = 'nondecreasing_six_month_living_plus_mortgage'
(OUT / 'inputs' / 'policy_rules.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(OUT)
