# AFPK 4단계 계산 및 대안 비교 도구

출산·육아휴직과 주택 마련을 함께 준비하는 가상 부부의 대안을 계산합니다. 기존 자료를 바꾸지 않고 이 폴더 안에서 입력, 계산 코드, 검증, 결과를 관리합니다. Python 3.10 이상에서 실행하며 외부 패키지 설치나 API 키가 필요하지 않습니다. 개발·실행 검증 환경은 Python 3.13입니다.

## 바로 열기

이미 계산한 결과는 [결과 화면](outputs/latest/report.html)에서 볼 수 있습니다. 파일 탐색기에서 `outputs/latest/report.html`을 브라우저로 열어도 됩니다. 인터넷 연결 없이 대안 선택, 월말 잔액 그래프, 지급일 자금, 조건별 판정을 볼 수 있습니다.

다시 계산하려면 Windows에서 **`실행.cmd`를 두 번 클릭**합니다. Python이 PATH에 등록되어 있어야 합니다. 계산 후 결과 화면이 열립니다.

터미널에서는 이 폴더에서 다음 명령을 사용합니다.

```powershell
python run.py
```

기본 실행은 **12개 대안과 110개 추가 스트레스**를 계산하고 `outputs/latest`에 결과를 생성합니다. 확인 필요 표시는 오류가 아니라 실제 대출 승인·제도·증빙·고객 상환한도가 아직 없다는 뜻입니다.

## 계산할 수 있는 것

- 2027·2030·2031년 7.5억 안의 원기간과 취득 후 5년 경로
- 2031년 6.3억 기본·비거래 복합, 6억·5.8억·5.6억 후보, 전세 유지
- 소득·휴직·지원·출산·돌봄·연금이체·대출을 반영한 월별 장부
- 기초잔액과 계약·잔금·등록 사건을 포함한 현금·보호여유 최저점
- 단일 충격과 복합 충격, 최초 부족일과 부족액
- 고객 합의 상환한도, 실제 대출 승인·실행 조건과 수치 조건의 분리
- 범위·단위·최대 검사횟수를 명시한 대출 후보 탐색
- 실제 사건의 부분 실행, 원계획 잔액 대체, 기준일 이전 거래 재가산 방지
- 동일 결과에서 생성하는 HTML·MD·CSV·JSON과 5·6단계 인계용 기준계획 초안

별도의 6단계 모니터링 서비스 화면·은행 연결·자동 금융거래·실시간 정책 수집은 이 도구의 구현 범위가 아닙니다. 실행 중 외부 AI를 호출하지 않습니다. AI가 정리한 값은 입력 파일에 근거와 확인 상태를 기록한 뒤 계산하고, 실제 AI 활용 내역은 기록 파일에 보존할 수 있습니다.

## 입력 바꾸기

| 파일 | 바꿀 내용 |
|---|---|
| `inputs/case.json` | 기초잔액, 소득, 생애 일정, 생활비, 출산비, 바우처, 지원, 출처·상환한도 |
| `inputs/policy_rules.json` | 적용 범위가 명시된 취득세·거래비용 가정과 정책 버전 |
| `inputs/scenarios.json` | 매입일·가격·대출·금리·종료월·각 충격의 변경분 |
| `inputs/events.csv` | 날짜·순서가 있는 보조 현금거래, 계획·실제 연결 |
| `inputs/ai_usage.json` | 이번 구현 요청의 실제 프롬프트·자동 검사 기록. 모델 정보·참가자 판단·직접 검증은 확인 후 보완 |

금액 단위는 **만 원**입니다. 금리는 `0.05`가 연 5%, 부담률은 `0.30`이 30%입니다. JSON 숫자에 천 단위 쉼표를 넣지 않습니다. 원 단위 입력을 섞거나 수익률을 임의로 넣으면 계산 전 차단합니다.

먼저 입력 검사를 실행할 수 있습니다.

```powershell
python run.py validate
```

원본 입력을 보존하려면 `inputs`를 새 폴더로 복사하고 `--input-dir`로 지정합니다. 상대 경로는 명령을 실행한 폴더 기준입니다.

```powershell
python run.py run --input-dir inputs --output outputs/my_run
python run.py run --scenario candidate_60000 --skip-stress --output outputs/60000
python run.py run --scenario base_2030 --scenario post_2030 --output outputs/2030
```

시나리오 ID는 `base_2027`, `base_2030`, `base_2031`, `post_2027`, `post_2030`, `post_2031`, `candidate_63000`, `candidate_63000_nontrade`, `candidate_60000`, `candidate_58000`, `candidate_56000`, `rent_only`입니다.

### 날짜가 있는 추가 지출

`events.csv`는 기본적으로 헤더만 있습니다. 예를 들어 치료비 계획과 확인한 실제 납부를 추가하려면 다음처럼 입력합니다. 이는 **입력 예시이며 기본 사례에 반영되지 않은 값**입니다.

```csv
event_id,date,sequence,type,amount,record_kind,planned_event_id,verification_status,source_id,reason
medical_plan,2030-12-10,50,expense,100,planned,,source_matched,MY_ESTIMATE,추가 치료비 예산
medical_actual,2030-12-08,50,expense,40,actual,medical_plan,evidence_verified,MY_RECEIPT,확인한 일부 납부
```

확인된 실제 40과 남은 계획 60으로 합계 100만 계산합니다. 실제 값이 미확인이면 적용하지 않습니다. 기준잔액일 이전에 이미 반영된 실제 거래는 다시 현금에 더하지 않습니다. 증빙 ID는 `case.json`의 출처 목록에 함께 등록합니다.

보조 사건은 `income`, `expense`, `retirement`, `settlement_payment`, `stock_sale`, `rental_return`을 지원합니다. 주택 계약·잔금·대출은 시나리오의 날짜와 조건으로 관리하며, 상환표 없는 별도 `loan_draw` 등을 사건 CSV에 중복 입력하면 차단합니다. 사건 ID와 기본 생성 사건 ID가 충돌해도 차단합니다.

### 생애주기와 스트레스

`case.json`의 `life_stage_schedule`에 시작·종료월과 `adult`, `child`, `care`, `nursery`, `cash_support`, `husband`, `wife` 중 바뀔 값을 적으면 그 기간에만 기본값을 덮어씁니다. 생활비 항목은 기준연도 가격, 소득·현금지원은 명목금액입니다. `working_plan`도 등록한 일정만 계산하므로 자료 완결성과 제도 적용은 자동 확정되지 않습니다.

`scenario.overrides`는 `delay_months`, `care_multiplier`, `care_start`, `parent_support_amount`, `parent_support_month`, `deposit_delay_months`, `renew_extra`, `stock_loss`, `extra_expenses`를 지원합니다. `extra_expenses`는 `{start,end,amount,inflate}` 형태의 월별 추가비용 목록입니다. `rate`는 시나리오의 신규 대출 금리입니다.

부모 지원 지연의 기존 재현은 **5월 말 예정→잔금 3개월 뒤인 9월 유입**입니다. 보증금 1·3개월 지연은 30·90일의 월 단위 근사입니다. 비거래 복합에는 이 두 반환·지원 지연이 포함되지 않습니다.

## 대출 탐색

```powershell
python run.py find-loan --scenario candidate_60000 --lower 0 --upper 40000 --step 100 --max-evaluations 500 --output outputs/loan_search.json
```

0~40,000만 원을 100만 원 간격으로 오름차순 검사합니다. `FOUND`는 **지정한 유한 격자에서의 첫 수치 통과액**이며 은행 승인이나 연속 범위 최적값이 아닙니다. 미확인 승인 조건은 함께 반환합니다. 확인된 승인한도가 있으면 그 범위로 제한하고, 합의한 상환한도가 있으면 함께 검사합니다.

`CONTRACT_BLOCKED`는 잔금일 대출로 앞선 계약금 문제를 해결할 수 없는 경우입니다. `SEARCH_INCONCLUSIVE`는 검사 예산 소진, `NO_FEASIBLE_LOAN`은 명시한 격자 전체 실패입니다. 비단조 가능성이 있는 함수에서 상한 한 번의 실패만으로 해가 없다고 판단하지 않습니다. CLI 종료 코드는 성공 0, 입력·실행 오류 2, 탐색 미성립/미완료 3입니다.

## 결과 파일

| 파일 | 용도 |
|---|---|
| `report.html` | 브라우저에서 보는 대안별 결과·그래프·조건 |
| `report_stage4.md` | 4.1~4.5 구조의 본문용 계산 결과와 한계 |
| `scenario_comparison.csv` | 동일 열의 대안 비교, 공통시점 순자산 별도 열 |
| `monthly_cashflow.csv` | 모든 기본 대안의 월별 장부 |
| `event_liquidity.csv` | 기본 자동 생성 및 사용자 등록 사건 |
| `transaction_summary.csv` | 계약금·잔금 요약 |
| `protected_funds.csv` | 월별 비상현금·목적자금 구성 |
| `results.json`, `stress_results.json` | 가정·장부·전체 시계열·판정·해시를 포함한 계산 결과 |
| `stress_results.csv` | 스트레스 핵심 결과 |
| `validation_results.json` | 입력 확인사항과 조건별 판정 |
| `baseline_plan.json` | 주택 거래 미승인 상태의 준비행동 기준계획 초안 |
| `inputs_snapshot.json`, `run_metadata.json` | 실행 입력·코드·정책 버전과 재현 해시 |
| `ai_usage_record.json` | 입력한 실제 AI 활용 기록의 보존본. 참가자 검토와 자동 검사를 구분 |

`baseline_plan.json`의 `housing_execution_allowed=false`는 주택 계약에만 적용합니다. 고객의 매입안 선택을 만들어 넣지 않으며, 준비행동은 별도 확인·동의에 따라 이어갈 수 있습니다.

## 판정과 계산의 적용 범위

`PASS`는 표시한 기간·가정의 해당 수치 조건을 충족했다는 뜻입니다. `FAIL`은 위반이며, 월적자만 있는 경우는 단독 탈락 조건이 아닙니다. `UNKNOWN`은 승인·제도·증빙·합의가 부족한 상태, `NOT_EVALUATED`는 분석하지 않은 항목입니다.

기존 6.3억 비거래 복합의 잔금 보호여유 약 30.542698, 2033.6 월수지 약 -7.538612, 2033.7 월말 보호기준 위반을 그대로 재현합니다. 해당 안을 최종 권고로 자동 승인하지 않습니다. 6억·5.8억·5.6억은 새 입력의 계산 결과이며, Google Docs의 치료비·지원금 축소 사고 시연과 동일한 시험이라고 표시하지 않습니다.

다음 한계가 결과에도 표시됩니다.

- 반복 급여·생활비·수당·원리금은 월말 합계 근사입니다. 명시한 사건 날짜와 순서만 날짜별로 계산하므로 모든 실제 일자의 지급능력이 검증된 것은 아닙니다.
- 지원·양육비는 별도 생애주기 일정이 없으면 기존 고정구조를 연장합니다. 취학·연령별 지원 종료·수선·미래 세금·임금변화를 자동 예측하지 않습니다.
- `historical_replay`는 원모델 재현을 위해 계약금의 취득 전 선급자산을 순자산에 별도로 계상하지 않습니다. `working_plan`은 선급자산을 반영합니다.
- 실제 대출 승인, DSR·LTV, 지원 적격성, 증여·감면, 거래일의 세법은 별도 증빙이 필요합니다. 일반세율 계산 범위를 벗어나면 0으로 대체하지 않습니다.
- 은퇴저축 납입은 계산하지만 장기 노후 충분성은 미평가입니다. 연금 예상액·수급일·생활비·인출 조건이 필요합니다.
- 현재 자산 수익과 집값 상승은 0인 모델입니다. 지원하지 않는 수익률을 입력하면 오류로 차단합니다.

## 검증과 코드

```powershell
python -m unittest discover -s tests -v
```

검사는 기존 장부의 모든 숫자 열 재현, 독립 PMT·가격 구간별 비용 계산, 현금 보존, 장기 반례, 월중·기초잔액 부족, 계획/실제 부분 실행, 입력 오류, 대출 탐색과 출력 경로를 포함합니다. 회귀검사는 `../hw/verify_plan.py`를 비메인 함수로 읽으므로 원본을 재생성하거나 수정하지 않습니다. 일반 실행은 이 폴더의 입력만 사용합니다.

구현 근거는 [4단계 시스템 구현계획](../hw/4단계_시스템_구현계획.md)과 입력 출처 목록에 있습니다. 취득세 산식은 [찾기쉬운 생활법령정보](https://www.easylaw.go.kr/CSP/CnpClsMain.laf?ccfNo=2&cciNo=2&cnpClsNo=4&csmSeq=666), Decimal 동작은 [Python 공식 문서](https://docs.python.org/3/library/decimal.html)를 참고했습니다. 코드의 과거 제도 스냅샷 계산과 실행일의 현행 적격성을 구분합니다.

이번 구현의 세 차례 검토와 수정 사항은 [검증 결과](검증결과.md)에 기록했습니다.
