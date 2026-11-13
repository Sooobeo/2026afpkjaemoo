from pathlib import Path
import urllib.request, urllib.parse, http.cookiejar, re, json
from html.parser import HTMLParser

class Fields(HTMLParser):
    def __init__(self): super().__init__(); self.fields={}
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ('input','select') and a.get('name'):
            self.fields[a['name']]=a.get('value','')

jar=http.cookiejar.CookieJar()
op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
base='https://rt.molit.go.kr'
html=op.open(base+'/pt/xls/xls.do?mobileAt=').read().decode('utf-8')
f=Fields();f.feed(html)
print('fields',f.fields)
data=f.fields
data.update(srhThingNo='A',srhDelngSecd='1',srhAddrGbn='1',srhLfstsSecd='1',
            srhFromDt='2026-01-01',srhToDt='2026-11-13',srhSidoCd='41000',srhSggCd='41285',
            srhEmdCd='',srhHsmpCd='',srhFromAmount='',srhToAmount='56000',
            sidoNm='경기도',sggNm='고양시 일산동구',emdNm='전체',hsmpNm='전체',srhArea='')
routes=['/pt/xls/ptXlsDownDataCheck.do','/pt/xls/ptXlsCSVDown.do']
for route in routes:
    req=urllib.request.Request(base+route,data=urllib.parse.urlencode(data).encode(),headers={'Referer':base+'/pt/xls/xls.do?mobileAt=','User-Agent':'Mozilla/5.0'})
    try:
        response=op.open(req,timeout=45);raw=response.read()
        print(route,response.status,response.headers.get('content-type'),len(raw),raw[:100])
        if route.endswith('CSVDown.do'):
            Path('.codex-work/combined2/official_goyang_2026.csv').write_bytes(raw)
    except Exception as e:print(type(e).__name__,str(e))
