"""Select and validate three illustrative records from saved official CSVs."""
from pathlib import Path
import csv
import hashlib
import io
import json

ROOT = Path(__file__).resolve().parent
SELECTIONS = [
    ("41285", "숲속마을2단지", "202611", "07", "75.8200", "41,000", "11"),
    ("41310", "한진", "202610", "26", "59.9370", "55,800", "21"),
    ("41210", "우림필유", "202610", "22", "59.7225", "54,000", "8"),
]


def read_rows(path):
    parsed = list(csv.reader(io.StringIO(path.read_bytes().decode("cp949"))))
    header = next(i for i, row in enumerate(parsed) if row and row[0] == "NO")
    return [dict(zip(parsed[header], row)) for row in parsed[header+1:]
            if len(row) == len(parsed[header])]


def build():
    output = []
    for code, name, month, day, area, price, floor in SELECTIONS:
        path = ROOT / f"official_housing_{code}_20260101_20261113.csv"
        rows = read_rows(path)
        found = [row for row in rows if row["단지명"] == name and row["계약년월"] == month
                 and row["계약일"] == day and row["전용면적(㎡)"] == area
                 and row["거래금액(만원)"] == price and row["층"] == floor]
        if len(found) != 1:
            raise ValueError(f"Expected exactly one saved official record: {code} {name}; got {len(found)}")
        row = found[0]
        amount = int(price.replace(",", ""))
        assert amount <= 56000 and float(area) <= 85
        assert row["해제사유발생일"] == "-" and row["거래유형"] == "중개거래"
        contract_date = f"{month[:4]}-{month[4:]}-{int(day):02d}"
        assert contract_date <= "2026-11-13"
        output.append({
            "complex_name": name, "address": row["시군구"], "road_address": row["도로명"],
            "exclusive_area_sqm": float(area), "contract_date": contract_date,
            "price_10k_krw": amount, "floor": int(floor), "construction_year": int(row["건축년도"]),
            "transaction_type": row["거래유형"], "cancellation_date_raw": row["해제사유발생일"],
            "cancellation_interpretation": "조회 원자료에서 해제사유발생일 미표시. 이후 변경·해제 신고 가능",
            "verification_status": "official_public_csv_matched", "retrieved_on": "2026-11-13",
            "source_url": "https://rt.molit.go.kr/pt/xls/xls.do?mobileAt=",
            "source_file": path.name, "source_row_NO": row["NO"],
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "raw_record": row,
            "not_verified": ["실제 출퇴근 시간", "병원·어린이집 접근", "엘리베이터·단지 및 세대 상태",
                             "현재 매물 존재", "추가 수리·가전 비용", "2031년 같은 가격의 매입 가능성"],
        })
    evidence = {"checked_on": "2026-11-13", "status": "three_official_examples_found",
                "purpose": "5.6억 이하 거래가 실제 존재한 가격대 근거; 추천 매물 확정 아님",
                "data_source": "국토교통부 실거래가 공개시스템 조건별 자료제공 아파트 매매 CSV",
                "date_range": ["2026-01-01", "2026-11-13"], "records": output,
                "limitations": [
                    "거래 사례는 계약일 기준이며 현재 호가·매물·전체 시장의 통계가 아닙니다.",
                    "2026년 거래가 2031년 5.6억 원 명목 매입가격을 보장하지 않습니다.",
                    "출퇴근 목적지·고객 최소 면적·연식·시설 조건이 확정되지 않아 주거 적합성은 미확인입니다.",
                    "국토부 자료는 신고정보가 실시간 수정·해제될 수 있으므로 계약 전 재조회해야 합니다.",
                ]}
    (ROOT / "housing_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return evidence


if __name__ == "__main__":
    result = build()
    print(json.dumps({"status": result["status"], "records": [{k:r[k] for k in
        ("complex_name", "address", "exclusive_area_sqm", "contract_date", "price_10k_krw", "floor", "construction_year", "source_row_NO")}
        for r in result["records"]]}, ensure_ascii=False, indent=2))
