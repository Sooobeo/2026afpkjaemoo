"""Readable outputs from one result object, including a portable HTML report."""
from __future__ import annotations

from html import escape
import json
from pathlib import Path

from .constraints import points
from .storage import write_csv, write_json

LABELS = {"PASS": "충족", "FAIL": "위반", "UNKNOWN": "확인 필요",
          "NOT_EVALUATED": "미평가", "REJECTED": "조정 필요",
          "REVIEW_REQUIRED": "추가 검토", "READY_FOR_HUMAN_REVIEW": "사람의 선택 대기"}


def num(value, digits=2):
    return "—" if value is None else f"{float(value):,.{digits}f}"


def comparison_row(result):
    scenario = result["scenario"]
    metrics = result["metrics"]
    common = metrics.get("comparison_row") or {}
    contract = next((e for e in result["events"] if e["event_id"].endswith("housing_contract")), {})
    close = next((e for e in result["events"] if e["event_id"].endswith("housing_closing")), {})
    first = metrics.get("first_protected_breach") or {}
    post = metrics.get("post_purchase_first_monthend_protected_breach") or {}
    return {"scenario_id": result["scenario_id"], "name": scenario["name"],
            "mode": result["mode"], "analysis_end": result["analysis_end"],
            "price": result.get("price"), "loan": result["loan"],
            "payment": result["payment"], "closing_cost": result.get("closing_cost"),
            "contract_free": contract.get("free"), "closing_free": close.get("free"),
            "min_cash": result["min_cash"]["cash"], "min_cash_date": result["min_cash"]["date"],
            "min_free": result["min_free"]["free"], "min_free_date": result["min_free"]["date"],
            "first_protected_breach": first.get("date"),
            "post_purchase_first_monthend_breach": post.get("month"),
            "common_month": scenario["comparison_end"],
            "common_net_worth": common.get("net_worth"),
            "common_monthly_surplus": common.get("monthly_surplus"),
            "ending_surplus": result["end"]["monthly_surplus"],
            "decision_status": result["decision_status"],
            "housing_execution_allowed": False,
            "input_hash": result["input_hash"], "output_hash": result["output_hash"]}


def markdown_report(bundle, results, stress_results, validation, metadata):
    case = bundle["case"]
    lines = ["# AFPK 4단계 재무설계안 계산 결과", "",
             f"사례: {case['case_id']} / 기준잔액일: {case['as_of_date']} / 단위: 만 원", "",
             "## 4.1 설계 원칙", "",
             "진료·회복·필수 돌봄과 비상현금을 우선 확보하고, 월 100만 원의 은퇴저축을 유지하며 주택 조건을 비교한다. "
             "현금 부족, 보호자금 위반, 월수지 적자는 별도로 표시한다.", "",
             "아래 결과는 입력한 가상 사례와 제도 스냅샷의 계산이다. 실제 대출·매물·송금·임대차·실행일의 제도 확인을 대신하지 않는다. "
             "장기 연장은 명목급여·비용 구성을 유지한 민감도이며, 노후자금 충분성은 미평가다.", "",
             "## 4.2 자금배분과 현금흐름", "",
             f"현재 정기 세후소득은 {num(float(case['income']['husband'])+float(case['income']['wife']))}, "
             f"생활비는 {num(case['budget']['adult_before'])}, 은퇴저축은 {num(case['budget']['retirement'])}다. "
             "정산 유보금은 보유 현금이며 별도 소비로 차감하지 않는다. 바우처는 현금입금이 아니다.", "",
             "월별 장부는 `monthly_cashflow.csv`, 개별 사건은 `event_liquidity.csv`, "
             "계약·잔금 요약은 `transaction_summary.csv`, 보호자금 구성은 `protected_funds.csv`에서 확인한다.", "",
             "## 4.3 대안 비교", "",
             "분석 종료월이 다른 안의 종료 순자산을 직접 순위 매기지 않는다. 공통시점 순자산은 별도 열에만 기록한다. "
             "기본안의 2031.6까지 결과와 취득 후 5년 결과를 각각 비교한다.", "",
             "| 대안 | 종료월 | 가격 | 대출 | 월 원리금 | 계약일 보호여유 | 최저 보호여유 | 최초 보호위반 | 판단 |",
             "|---|---|---:|---:|---:|---:|---:|---|---|"]
    for result in results:
        row = comparison_row(result)
        lines.append(f"| {row['name']} | {row['analysis_end']} | {num(row['price'],0)} | {num(row['loan'],0)} | "
                     f"{num(row['payment'])} | {num(row['contract_free'])} | {num(row['min_free'])} | "
                     f"{row['first_protected_breach'] or '기간 내 없음'} | {LABELS[row['decision_status']]} |")
    lines += ["", "6.3억 안은 단기 통과 여부와 무관하게 후속 장기·복합 검증을 함께 보아야 하는 추가 검토 대안이다. "
              "6억·5.8억·5.6억 후보는 이 실행의 입력·기간·충격으로 새로 계산한 값이며, Google Docs의 사고 시연 수치와 동일하다고 가정하지 않는다.", "",
              "## 4.4 스트레스와 제약", "",
              f"추가 스트레스 {len(stress_results)}개를 계산했다. 기본 대출원금은 고정하고 입력된 충격만 변경했다. "
              "부모 지원 지연과 보증금 반환 지연은 비거래 복합과 구분한다. 정확한 적용월과 변경분은 `stress_results.json`을 확인한다.", ""]
    for result in results:
        lines += [f"### {result['scenario']['name']}", "",
                  "| 점검 | 상태 | 최초 위반 | 부족액 | 근거/설명 |",
                  "|---|---|---|---:|---|"]
        for check in result["constraint_results"]:
            lines.append(f"| {check['label']} | {LABELS.get(check['status'],check['status'])} | "
                         f"{check['first_breach_at'] or '—'} | {num(check['amount'])} | {check['cause']} |")
        lines += ["", "계산 가정과 제한:", ""] + [f"- {x}" for x in result["limitations"]] + [""]
    lines += ["## 4.5 종합 평가와 다음 행동", "",
              "이 도구는 매입안을 자동 승인하지 않는다. `조정 필요`는 현금 또는 보호조건 위반, "
              "`추가 검토`는 수치 외 승인·제도·증빙 확인이 남은 상태다. 가격·시점 조정안을 비교한 뒤 참가자와 고객이 선택 이유·조건을 기록해야 한다.", "",
              "주택 계약과 별개로 비상현금 구분, 출산 준비, 은퇴저축을 준비행동으로 이어갈 수 있다. "
              "`baseline_plan.json`은 주택 매입이 승인되지 않은 기준계획 초안이며, 원래 계획과 실제 실행기록은 분리해 보존한다.", "",
              "## 입력과 검증 기록", "",
              f"- 입력 해시: `{metadata['input_hash']}`",
              f"- 코드 버전: `{metadata['code_version']}` / 코드 해시: `{metadata['code_hash']}`",
              f"- 정책 버전: `{metadata['policy_version']}`",
              f"- 입력 검사: 오류 {sum(v['severity']=='ERROR' for v in validation)}개, "
              f"확인사항 {sum(v['severity']=='WARNING' for v in validation)}개",
              "- 실사용 AI 기록은 `ai_usage_record.json`으로 보존한다. 빈 기록을 실제 사용 프롬프트로 채우지 않는다.", "",
              "## 출처", ""]
    sources = case.get("sources", [])
    if isinstance(sources, dict):
        sources = [{"id": k, **v} for k, v in sources.items()]
    for source in sources:
        title = source.get("title", source.get("id", source.get("source_id", "자료")))
        target = source.get("path_or_url", source.get("url", source.get("path", "")))
        lines.append(f"- {title}: {target} / {source.get('locator','')} / 확인일 {source.get('checked_at','미확정')}")
    return "\n".join(lines) + "\n"


def _html_report(results, stress_results, metadata):
    payload = []
    for result in results:
        payload.append({"summary": comparison_row(result), "rows": result["rows"],
                        "checks": result["constraint_results"], "events": result["events"],
                        "limitations": result["limitations"]})
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    encoded_labels = json.dumps(LABELS, ensure_ascii=False)
    return r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AFPK · 4단계 대안 비교</title><style>
:root{--ink:#14273d;--muted:#637388;--line:#dce4ee;--blue:#245bd6;--red:#b92b37;--green:#167457;--bg:#f3f6fa}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 'Malgun Gothic',system-ui,sans-serif}
header{background:#122941;color:white;padding:26px max(28px,calc((100vw - 1350px)/2));display:flex;justify-content:space-between;gap:30px;align-items:center}
header p{margin:2px 0;color:#b9cbdf;font-size:13px}h1{font-size:25px;margin:0;letter-spacing:-1px}.tag{border:1px solid #6681a2;border-radius:30px;padding:5px 14px;font-size:12px;white-space:nowrap}
main{max-width:1406px;margin:auto;padding:25px 28px 45px}.intro{margin:0 0 20px;color:var(--muted)}.bar{display:flex;justify-content:space-between;align-items:center;gap:18px;margin:20px 0}select{font:inherit;max-width:100%;background:white;border:1px solid #b9c9df;border-radius:7px;padding:10px 35px 10px 12px;color:var(--ink)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.metric,.panel{background:white;border:1px solid var(--line);border-radius:10px}.metric{padding:18px 20px}.metric small{color:var(--muted);font-size:13px}.metric b{display:block;font-size:27px;letter-spacing:-1px;margin:6px 0}.metric span{font-size:12px;color:var(--muted)}
.panels{display:grid;grid-template-columns:1.65fr 1fr;gap:18px;margin-top:18px}.panel{padding:20px;min-width:0}.panel h2{font-size:17px;margin:0 0 8px}.sub{color:var(--muted);font-size:12px;margin:0 0 14px}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:12px}th{font-weight:600;background:#f5f8fc;color:#4e6075}th,td{border-bottom:1px solid var(--line);padding:11px 10px;text-align:left;white-space:nowrap}td.n{text-align:right;font-variant-numeric:tabular-nums}tbody tr:hover{background:#f7faff}.badge{display:inline-block;border-radius:4px;padding:3px 7px;font-size:11px;background:#edf1f6;color:#536278}.FAIL,.REJECTED{background:#fff0f0;color:var(--red)}.PASS{background:#e8f6ef;color:var(--green)}.UNKNOWN,.REVIEW_REQUIRED{background:#fff4d9;color:#8b6510}
svg{display:block;width:100%;height:310px}svg text{font-size:11px;fill:#718097}.legend{display:flex;gap:22px;font-size:12px;color:var(--muted);margin:4px 0}.legend i{display:inline-block;width:18px;height:3px;margin-right:6px;vertical-align:middle}.notes{font-size:12px;color:var(--muted);padding-left:18px}.links{display:flex;gap:18px;flex-wrap:wrap;font-size:13px}a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}.footer{font-size:11px;color:var(--muted);margin-top:22px;word-break:break-all}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}.panels{grid-template-columns:1fr}header{padding:20px}main{padding:18px}.bar{align-items:flex-start;flex-direction:column}}
@media print{body{background:white}header{background:white;color:#14273d}.panel,.metric{break-inside:avoid}select{border:none}.links{display:none}}
</style></head><body><header><div><p>AFPK YOUNG PLANNER CHALLENGE 2026</p><h1>집을 살 수 있는 조건을 비교합니다</h1></div><div class="tag">4단계 · 가상 사례 계산</div></header>
<main><p class="intro">회복·돌봄, 비상현금, 은퇴저축을 지키며 시점과 가격을 비교합니다. 금액은 만 원이며, 수치 충족과 실제 거래 승인은 별개입니다.</p>
<div class="bar"><select id="scenario" aria-label="비교할 대안"></select><span class="sub" id="period"></span></div>
<div class="grid" id="metrics"></div><div class="panels"><section class="panel"><h2>현금과 남겨야 할 자금</h2><p class="sub">월말 경로입니다. 계약·잔금일의 부족은 오른쪽 지급일 표에서 별도로 확인합니다.</p><svg id="chart" viewBox="0 0 760 310" role="img" aria-label="현금과 보호자금의 월별 경로"></svg><div class="legend"><span><i style="background:#245bd6"></i>총현금</span><span><i style="background:#e19a35"></i>비상·목적자금</span></div></section>
<section class="panel"><h2>계약·잔금 지급일</h2><p class="sub">지급 후 현금에서 비상·목적자금을 뺀 금액이 보호여유입니다.</p><div class="scroll"><table><thead><tr><th>지급일</th><th>지급 후 현금</th><th>보호여유</th></tr></thead><tbody id="events"></tbody></table></div><p class="sub" style="margin-top:18px">월말 잔액이 양수여도 지급일에 부족할 수 있습니다. 미승인 차입은 자동 가산하지 않습니다.</p></section></div>
<section class="panel" style="margin-top:18px"><h2>대안별 핵심 결과</h2><p class="sub">같은 기간의 안끼리 비교하세요. 2031.6까지의 기본안과 매입 후 5년 연장안은 구분했습니다.</p><div class="scroll"><table><thead><tr><th>대안</th><th>종료</th><th>대출</th><th>월 원리금</th><th>최저 보호여유</th><th>첫 보호위반</th><th>판단</th></tr></thead><tbody id="comparison"></tbody></table></div></section>
<div class="panels"><section class="panel"><h2>조건별 확인</h2><div class="scroll"><table><thead><tr><th>조건</th><th>상태</th><th>첫 위반일</th><th>부족액</th></tr></thead><tbody id="checks"></tbody></table></div></section><section class="panel"><h2>이 결과의 적용 범위</h2><ul id="notes" class="notes"></ul><p class="sub">노후자금 충분성은 미평가입니다. 주택 계약은 고객 선택과 대출·제도·송금·임대차 확인 후 판단합니다.</p></section></div>
<section class="panel" style="margin-top:18px"><h2>장부와 근거 파일</h2><p class="sub">스트레스 계산 __STRESS_COUNT__개 · 같은 입력에서 표·보고서·기준계획을 생성했습니다.</p><div class="links"><a href="report_stage4.md">본문용 결과</a><a href="monthly_cashflow.csv">월별 장부 CSV</a><a href="event_liquidity.csv">사건별 장부 CSV</a><a href="scenario_comparison.csv">대안 비교 CSV</a><a href="stress_results.csv">스트레스 CSV</a><a href="validation_results.json">입력·판정 기록</a><a href="baseline_plan.json">기준계획 초안</a></div></section>
<p class="footer">입력 해시 __INPUT_HASH__<br>__VERSION__ · 인터넷 연결 없이 열 수 있는 로컬 보고서</p></main>
<script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent), labels=__LABELS__;
const esc=s=>String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const f=(v,d=1)=>v==null?'—':Number(v).toLocaleString('ko-KR',{minimumFractionDigits:d,maximumFractionDigits:d});
const badge=s=>`<span class="badge ${esc(s)}">${esc(labels[s]||s)}</span>`;
document.getElementById('scenario').innerHTML=data.map((d,i)=>`<option value="${i}">${esc(d.summary.name)}</option>`).join('');
document.getElementById('comparison').innerHTML=data.map(d=>{const s=d.summary;return `<tr><td>${esc(s.name)}</td><td>${esc(s.analysis_end)}</td><td class="n">${f(s.loan,0)}</td><td class="n">${f(s.payment)}</td><td class="n">${f(s.min_free)}</td><td>${esc(s.first_protected_breach||'기간 내 없음')}</td><td>${badge(s.decision_status)}</td></tr>`}).join('');
function draw(rows){const W=760,H=310,L=66,R=14,T=16,B=32, vals=rows.flatMap(r=>[r.cash,r.cash-r.free]);let min=Math.min(0,...vals),max=Math.max(...vals);if(max===min)max=min+1;const x=i=>L+i*(W-L-R)/Math.max(1,rows.length-1),y=v=>T+(max-v)*(H-T-B)/(max-min);let svg='';for(let i=0;i<=4;i++){let v=min+(max-min)*i/4;svg+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="#e5ebf3"/><text x="${L-10}" y="${y(v)+4}" text-anchor="end">${f(v,0)}</text>`}for(const [key,color]of[['cash','#245bd6'],['protected','#e19a35']]){svg+=`<polyline fill="none" stroke="${color}" stroke-width="2.5" points="${rows.map((r,i)=>`${x(i)},${y(key==='cash'?r.cash:r.cash-r.free)}`).join(' ')}"/>`}for(let k=0;k<5;k++){let i=Math.round((rows.length-1)*k/4);svg+=`<text x="${x(i)}" y="${H-8}" text-anchor="${k===0?'start':k===4?'end':'middle'}">${esc(rows[i].month)}</text>`}document.getElementById('chart').innerHTML=svg;}
function show(i){const d=data[i],s=d.summary;document.getElementById('period').textContent=`분석 종료 ${s.analysis_end} · 공통 비교 ${s.common_month} · 만 원`;
const cards=[['매입가격',f(s.price,0),'매매대금'],['월 원리금',f(s.payment),'은퇴저축은 별도'],['최저 보호여유',f(s.min_free),s.min_free_date],['종합 판단',labels[s.decision_status]||s.decision_status,'주택 계약은 자동 승인하지 않음']];document.getElementById('metrics').innerHTML=cards.map(([label,value,note])=>`<div class="metric"><small>${esc(label)}</small><b style="${label==='종합 판단'?'font-size:23px':''}">${esc(value)}</b><span>${esc(note)}</span></div>`).join('');
document.getElementById('events').innerHTML=d.events.length?d.events.map(e=>`<tr><td>${esc(e.date)}<br><small>${esc(e.event)}</small></td><td class="n">${f(e.cash_after)}</td><td class="n" style="color:${e.free<0?'#b92b37':'#167457'}">${f(e.free)}</td></tr>`).join(''):'<tr><td colspan="3">주택 취득 없는 비교안</td></tr>';
document.getElementById('checks').innerHTML=d.checks.map(c=>`<tr title="${esc(c.cause)}"><td>${esc(c.label)}</td><td>${badge(c.status)}</td><td>${esc(c.first_breach_at)}</td><td class="n">${f(c.amount)}</td></tr>`).join('');document.getElementById('notes').innerHTML=d.limitations.map(n=>`<li>${esc(n)}</li>`).join('');draw(d.rows);}
document.getElementById('scenario').addEventListener('change',e=>{const i=Number(e.target.value);show(i);history.replaceState(null,'','#'+encodeURIComponent(data[i].summary.scenario_id));});
const initial=Math.max(0,data.findIndex(d=>d.summary.scenario_id===decodeURIComponent(location.hash.slice(1))));document.getElementById('scenario').value=String(initial);show(initial);
</script></body></html>'''.replace("__DATA__", encoded).replace("__LABELS__", encoded_labels).replace(
        "__INPUT_HASH__", escape(metadata["input_hash"])).replace("__VERSION__", escape(metadata["code_version"])).replace(
        "__STRESS_COUNT__", str(len(stress_results)))


def write_outputs(output, bundle, results, stress_results, validation, metadata):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "run_metadata.json", metadata)
    write_json(output / "inputs_snapshot.json", {k: v for k, v in bundle.items() if k != "input_dir"})
    write_json(output / "results.json", results)
    write_json(output / "stress_results.json", stress_results)
    write_csv(output / "scenario_comparison.csv", [comparison_row(r) for r in results])
    write_csv(output / "stress_results.csv", [comparison_row(r) for r in stress_results])
    monthly, events, primary, protection = [], [], [], []
    for result in results:
        sid = result["scenario_id"]
        monthly.extend({"scenario_id": sid, **r} for r in result["rows"])
        events.extend({"scenario_id": sid, **r} for r in result.get("event_rows", result["events"]))
        primary.extend({"scenario_id": sid, **r} for r in result["events"])
        for row in result["rows"]:
            protection.append({"scenario_id": sid, **{k: row.get(k) for k in
                               ("month", "cash", "reserve", "future_birth_cash", "birth_buffer",
                                "settlement_balance", "trade_buffer", "earmark", "free")}})
    write_csv(output / "monthly_cashflow.csv", monthly)
    write_csv(output / "event_liquidity.csv", events)
    write_csv(output / "transaction_summary.csv", primary)
    write_csv(output / "protected_funds.csv", protection)
    write_json(output / "validation_results.json", {"input_checks": validation,
               "scenario_checks": [{"scenario_id": r["scenario_id"], "checks": r["constraint_results"]}
                                   for r in results]})
    write_json(output / "ai_usage_record.json", bundle.get("ai_usage", {}))
    # A baseline is an unsigned planning draft. No invented customer decision.
    basis = next((r for r in results if r["scenario"].get("purchase_year") is None), results[0])
    write_json(output / "baseline_plan.json", {
        "schema_version": "1.0", "case_id": bundle["case"]["case_id"],
        "plan_version": metadata["input_hash"][:12], "draft": True,
        "basis_scenario_id": basis["scenario_id"], "selected_housing_scenario_id": None,
        "housing_status": "REVIEW_REQUIRED", "housing_execution_allowed": False,
        "decision": None, "as_of_date": bundle["case"]["as_of_date"],
        "input_hash": metadata["input_hash"], "code_hash": metadata["code_hash"],
        "code_version": metadata["code_version"], "policy_version": metadata["policy_version"],
        "preparation_actions": ["비상현금과 출산 준비현금을 구분", "월 은퇴저축 유지",
                                "복직 후 실제 가계수지 확인", "계약 전 대출·매물·송금·임대차 확인"],
        "planned_monthly_rows": basis["rows"], "planned_events": basis["events"],
        "original_input": {"case": bundle["case"], "scenario": basis["scenario"]},
        "constraint_results": basis["constraint_results"], "limitations": basis["limitations"],
        "actual_records": [], "reason": "사람의 매입안 선택·승인 전 준비행동 기준계획 초안"})
    (output / "report_stage4.md").write_text(markdown_report(bundle, results, stress_results, validation, metadata), encoding="utf-8")
    (output / "report.html").write_text(_html_report(results, stress_results, metadata), encoding="utf-8")
