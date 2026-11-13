"""Download publicly provided MOLIT apartment-sale CSVs without API credentials.

This uses the same public form endpoint as the official 자료제공 page.
It neither logs in nor supplies/obtains an API key. Do not infer cancellation
absence permanently: data can be corrected after the retrieval date.
"""
from pathlib import Path
from html.parser import HTMLParser
import http.cookiejar
import json
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
BASE = "https://rt.molit.go.kr"
FORM_URL = BASE + "/pt/xls/xls.do?mobileAt="


class FormFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("input", "select") and attrs.get("name"):
            self.fields[attrs["name"]] = attrs.get("value", "")


def download(code, name, from_date="2026-01-01", to_date="2026-11-13"):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    parser = FormFields()
    parser.feed(opener.open(FORM_URL, timeout=30).read().decode("utf-8"))
    fields = parser.fields
    fields.update(srhThingNo="A", srhDelngSecd="1", srhAddrGbn="1", srhLfstsSecd="1",
                  srhFromDt=from_date, srhToDt=to_date, srhSidoCd="41000", srhSggCd=code,
                  srhEmdCd="", srhHsmpCd="", srhFromAmount="", srhToAmount="",
                  sidoNm="경기도", sggNm=name, emdNm="전체", hsmpNm="전체", srhArea="")
    request = urllib.request.Request(
        BASE + "/pt/xls/ptXlsCSVDown.do",
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Referer": FORM_URL, "User-Agent": "Mozilla/5.0"})
    response = opener.open(request, timeout=45)
    raw = response.read()
    text = raw.decode("cp949")
    if "거래금액(만원)" not in text or "단지명" not in text:
        raise ValueError("Response is not the expected official apartment-sale CSV")
    path = ROOT / f"official_housing_{code}_20260101_20261113.csv"
    path.write_bytes(raw)
    return {"path": path.name, "bytes": len(raw), "city_code": code, "city": name,
            "from_date": from_date, "to_date": to_date, "encoding": "cp949",
            "source_url": FORM_URL,
            "download_endpoint": BASE + "/pt/xls/ptXlsCSVDown.do",
            "method": "POST public download form", "retrieved_on": "2026-11-13"}


if __name__ == "__main__":
    records = [download(code, name) for code, name in
               [("41285", "고양시 일산동구"), ("41310", "구리시"), ("41210", "광명시")]]
    (ROOT / "housing_download_manifest.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(records, ensure_ascii=False, indent=2))
