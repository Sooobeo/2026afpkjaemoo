"""Render the complete monitoring plan as a portable offline HTML document.

Uses the markdown_it and BeautifulSoup packages already available in the
workspace. No network assets are loaded by the resulting document.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup, NavigableString
from markdown_it import MarkdownIt


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "6단계_모니터링_시스템_구현계획.md"
OUTPUT = SOURCE.with_suffix(".html")


def mermaid_svg(code: str) -> tuple[str, dict]:
    """Draw this plan's flowchart offline, retaining every node and edge."""
    labels = dict(re.findall(r'([A-Z]+)\["([^"]+)"\]', code))
    edges = []
    for line in code.splitlines():
        match = re.match(r'\s*([A-Z]+)(?:\["[^"]+"\])?\s*-->\s*([A-Z]+)', line)
        if match:
            edges.append(match.groups())
    boxes = {
        "A": (80, 32, 300, 60), "B": (80, 132, 300, 60),
        "C": (80, 232, 300, 60), "M": (500, 32, 300, 60),
        "N": (500, 132, 300, 60), "V": (500, 232, 300, 60),
        "E": (280, 352, 300, 60), "F": (280, 552, 300, 60),
        "S": (600, 452, 260, 60), "G": (280, 652, 300, 60),
        "H": (280, 752, 300, 60), "I": (280, 852, 300, 60),
    }
    if set(labels) != set(boxes):
        raise ValueError("Flowchart nodes changed; update the verified offline diagram layout.")
    paths = {
        ("A", "B"): "M230 92 V132", ("B", "C"): "M230 192 V232",
        ("M", "N"): "M650 92 V132", ("N", "V"): "M650 192 V232",
        ("C", "E"): "M230 292 V322 H380 V352",
        ("V", "E"): "M650 292 V322 H480 V352",
        ("E", "F"): "M430 412 V552",
        ("E", "S"): "M580 382 H730 V452",
        ("S", "F"): "M730 512 V582 H580",
        ("F", "G"): "M430 612 V652", ("G", "H"): "M430 712 V752",
        ("H", "I"): "M430 812 V852",
        ("I", "B"): "M280 882 H28 V162 H80",
    }
    if set(edges) != set(paths):
        raise ValueError("Flowchart edges changed; update the verified offline arrow layout.")
    description = "; ".join(f"{labels[a]} → {labels[b]}" for a, b in edges)
    svg = [
        '<svg class="flow-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 890 950" '
        'role="img" aria-labelledby="flow-title flow-desc">',
        '<title id="flow-title">6단계 모니터링의 입력부터 다음 점검까지</title>',
        f'<desc id="flow-desc">{html.escape(description)}</desc>',
        '<defs><marker id="flow-arrow" markerWidth="9" markerHeight="9" '
        'refX="8" refY="4.5" orient="auto"><path d="M0 0 L9 4.5 L0 9 Z" fill="#7b91ae"/></marker></defs>',
    ]
    for pair in edges:
        dashed = ' stroke-dasharray="6 5"' if pair == ("I", "B") else ""
        svg.append(f'<path class="flow-edge" data-from="{pair[0]}" data-to="{pair[1]}" '
                   f'd="{paths[pair]}" fill="none" stroke="#7b91ae" stroke-width="2" '
                   f'marker-end="url(#flow-arrow)"{dashed}/>')
    for key, label in labels.items():
        x, y, width, height = boxes[key]
        fill, stroke = ("#edf4ff", "#adc6ef") if key in {"E", "F", "G", "H", "I"} else ("#ffffff", "#cbd6e4")
        if key in {"N", "V"}:
            fill, stroke = "#f4f0ff", "#cbbde9"
        svg.append(f'<g class="flow-node" data-node="{key}"><rect x="{x}" y="{y}" '
                   f'width="{width}" height="{height}" rx="10" fill="{fill}" stroke="{stroke}"/>'
                   f'<text x="{x+width/2}" y="{y+height/2+6}" text-anchor="middle" '
                   f'font-size="17" fill="#183353">{html.escape(label)}</text></g>')
    svg += ['<text x="40" y="932" font-size="13" fill="#64758b">새 계획으로 다음 점검을 이어 간다</text>', '</svg>']
    visual = ('<figure class="flow-figure">' + "".join(svg) +
              '<figcaption>월마감 자료와 확인한 변경을 함께 사용해 미래를 다시 계산합니다.</figcaption></figure>' +
              '<details class="diagram-source"><summary>흐름도 원문 보기</summary><pre><code>' +
              html.escape(code) + '</code></pre></details>')
    return visual, {"nodes": len(labels), "edges": len(edges)}


CSS = r"""
:root{--ink:#19324e;--muted:#677a90;--line:#dbe4ee;--blue:#2159c2;--paper:#fff;--bg:#f4f7fb;--side:266px}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:28px}body{margin:0;background:var(--bg);color:var(--ink);font:15.5px/1.85 'Malgun Gothic','Apple SD Gothic Neo',system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #8bb8ff;outline-offset:4px;border-radius:3px}
.skip{position:absolute;left:10px;top:-60px;background:white;padding:10px;z-index:20}.skip:focus{top:10px}
aside{position:fixed;inset:0 auto 0 0;width:var(--side);padding:30px 22px 22px;background:#142b44;color:white;overflow-y:auto;z-index:5}
.brand{font-size:11px;letter-spacing:1.4px;color:#a6bfdc;margin:0 0 9px}.aside-title{font-size:20px;line-height:1.4;font-weight:700;letter-spacing:-.6px;margin:0 0 14px}.aside-sub{font-size:12px;line-height:1.7;color:#b3c6dd;margin-bottom:24px}.toc-label{font-size:11px;letter-spacing:1px;color:#9db4ce;margin:0 0 8px}
nav a{display:block;color:#c7d6e7;font-size:12.3px;line-height:1.55;padding:8px 9px;border-left:2px solid transparent;margin-left:-9px}nav a:hover,nav a.active{color:#fff;text-decoration:none;border-left-color:#83b6ff;background:#203e5f;border-radius:0 5px 5px 0}.aside-bottom{margin-top:25px;font-size:11px;color:#9db4ce}
.page{margin-left:var(--side);padding:36px 44px 70px}.document{max-width:1050px;margin:0 auto;background:var(--paper);border:1px solid var(--line);box-shadow:0 5px 30px #20384b07;border-radius:14px;padding:42px 52px 50px}
.tools{display:flex;gap:10px;justify-content:space-between;align-items:center;max-width:1050px;margin:0 auto 18px;color:var(--muted);font-size:12px}.tools div{display:flex;gap:10px;align-items:center}button,.source-link{font:inherit;border:1px solid #c7d5e6;background:#fff;border-radius:6px;padding:7px 12px;color:#315477;cursor:pointer}
h1{font-size:30px;line-height:1.45;margin:0 0 11px;letter-spacing:-1.1px;color:#122c48}h2{font-size:23px;line-height:1.5;margin:48px 0 18px;padding-top:12px;letter-spacing:-.7px}h2:before{content:'';display:block;width:28px;height:3px;background:#5786d2;margin-bottom:12px;border-radius:2px}h3{font-size:18px;line-height:1.6;margin:30px 0 10px;letter-spacing:-.3px}p{margin:12px 0}strong{font-weight:700;color:#163a68}.doc-date{font-size:12px;color:var(--muted);margin:0 0 28px}
ul,ol{padding-left:24px;margin:14px 0}li{margin:8px 0}li>p{margin:5px 0}blockquote{border-left:3px solid #bccfe9;padding:0 0 0 20px;margin-left:0;color:#526780}
.table-wrap{overflow:auto;margin:20px 0 24px;border:1px solid var(--line);border-radius:8px}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.75;min-width:580px;margin:0}th,td{padding:12px 13px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left;overflow-wrap:anywhere}th{background:#eaf1fb;color:#294c75;font-weight:700}tbody tr:last-child td{border-bottom:0}tbody tr:nth-child(even){background:#f8fafd}tbody tr:hover{background:#eff5ff}th:first-child,td:first-child{min-width:72px}td p{margin:0}.source-table td:first-child{width:60px;min-width:60px}.source-table td:nth-child(2){min-width:180px}
code{font:12.4px/1.7 Consolas,'Cascadia Code',monospace;background:#eef2f7;border:1px solid #e2e8f0;border-radius:4px;padding:1px 5px;overflow-wrap:anywhere;color:#334d6d}pre{background:#f5f7fa;border:1px solid #dfe6ef;border-radius:8px;padding:18px 20px;overflow:auto;line-height:1.7;margin:20px 0}pre code{background:none;border:0;padding:0;font-size:12.5px;white-space:pre;color:#314b68;overflow-wrap:normal}
.flow-figure{margin:22px 0 6px;padding:16px;background:#f8faff;border:1px solid var(--line);border-radius:10px}.flow-svg{display:block;width:100%;max-width:840px;height:auto;margin:auto;font-family:'Malgun Gothic',system-ui,sans-serif}.flow-figure figcaption{font-size:12px;color:var(--muted);text-align:center;margin-top:12px}.diagram-source{font-size:12px;color:var(--muted);margin:5px 0 24px}.diagram-source summary{cursor:pointer;padding:4px 0}.diagram-source pre{margin:10px 0}
.reference{font-size:12px;white-space:nowrap}.doc-footer{border-top:1px solid var(--line);margin-top:45px;padding-top:20px;color:var(--muted);font-size:11px;overflow-wrap:anywhere}.mobile-toc{display:none}.anchor{position:relative;top:-8px}
@media(min-width:1600px){.page{padding-left:70px;padding-right:70px}.document{padding-left:62px;padding-right:62px}}
@media(max-width:1100px){:root{--side:225px}.page{padding:24px}.document{padding:30px}.aside-title{font-size:18px}body{font-size:15px}}
@media(max-width:800px){aside{display:none}.page{margin-left:0;padding:16px 12px 35px}.document{border-radius:9px;padding:26px 20px;box-shadow:none}h1{font-size:25px}h2{font-size:21px;margin-top:38px}h3{font-size:17px}.tools{gap:10px;align-items:flex-start}.tools>span{max-width:46%;font-size:11px}.tools div{gap:6px}.source-link,button{padding:6px 9px;font-size:11px}.mobile-toc{display:block;border:1px solid var(--line);border-radius:7px;padding:9px 12px;margin:18px 0 26px}.mobile-toc summary{cursor:pointer;font-weight:600}.mobile-toc a{display:block;font-size:13px;padding:5px 0}.table-wrap{margin-left:-2px;margin-right:-2px}td,th{padding:10px;font-size:12px}.flow-figure{padding:4px}.flow-svg{min-width:580px}.flow-figure{overflow:auto}.flow-figure figcaption{min-width:540px}pre{padding:14px}.doc-footer{font-size:10px}}
@page{size:A4;margin:14mm 14mm 16mm}
@media print{html{scroll-behavior:auto}body{background:#fff;color:#111;font-size:10.5pt;line-height:1.65}aside,.tools,.mobile-toc,.diagram-source{display:none!important}.page{margin:0;padding:0}.document{border:0;box-shadow:none;max-width:none;padding:0;border-radius:0}h1{font-size:22pt}h2{font-size:16pt;break-after:avoid;margin-top:25pt;padding:0}h2:before{display:none}h3{font-size:12.5pt;break-after:avoid}p{orphans:3;widows:3}a{color:#153d69;text-decoration:none}.table-wrap{overflow:visible;border-radius:0;break-inside:auto;margin:12pt 0}table{min-width:0;font-size:9pt;table-layout:auto}th,td{padding:6pt;overflow-wrap:anywhere}thead{display:table-header-group}tr{break-inside:avoid}pre{white-space:pre-wrap;overflow:visible;font-size:8pt;break-inside:avoid}pre code{white-space:pre-wrap;font-size:8pt}.flow-figure{break-inside:avoid;max-width:140mm;margin-left:auto;margin-right:auto;padding:4mm}.flow-svg{min-width:0}.flow-figure figcaption{min-width:0}.doc-footer{font-size:8pt}}
"""


def build(source: Path = SOURCE, output: Path = OUTPUT) -> dict:
    original = source.read_bytes()
    text = original.decode("utf-8")
    diagrams = []

    def fence(renderer, tokens, idx, options, env):
        token = tokens[idx]
        if token.info.strip() == "mermaid":
            visual, metadata = mermaid_svg(token.content)
            diagrams.append(metadata)
            return visual
        language = html.escape(token.info.strip())
        return f'<pre><code class="language-{language}">{html.escape(token.content)}</code></pre>\n'

    markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
    markdown.add_render_rule("fence", fence)
    soup = BeautifulSoup(markdown.render(text), "html.parser")
    headings = []
    used = set()
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        title = heading.get_text("", strip=True)
        anchor = re.sub(r"[^\w가-힣-]+", "-", title, flags=re.UNICODE).strip("-").lower()
        unique = anchor
        count = 2
        while unique in used:
            unique = f"{anchor}-{count}"
            count += 1
        used.add(unique)
        heading["id"] = unique
        headings.append({"level": int(heading.name[1]), "title": title, "id": unique})
    for table in soup.find_all("table"):
        wrapper = soup.new_tag("div", attrs={"class": "table-wrap", "tabindex": "0", "role": "region", "aria-label": "가로로 스크롤할 수 있는 비교표"})
        table.wrap(wrapper)
        cells = table.select("tbody tr td:first-child")
        if cells and re.fullmatch(r"D\d+", cells[0].get_text(strip=True)):
            table["class"] = "source-table"
            for cell in cells:
                cell["id"] = "source-" + cell.get_text(strip=True).lower()
    for item in soup.select("li"):
        first_text = item.get_text(" ", strip=True)
        if re.match(r"T[1-4]\s", first_text):
            item["id"] = "source-" + first_text.split()[0].lower()
    # Turn the source references already present in prose into navigable links.
    for node in list(soup.find_all(string=re.compile(r"\b(?:D\d+|T[1-4])\b"))):
        if node.parent.name in {"code", "pre", "a", "td", "th", "summary", "title", "desc"}:
            continue
        if node.find_parent(["svg", "pre", "code"]):
            continue
        value = str(node)
        chunks = []
        position = 0
        for match in re.finditer(r"\b(D\d+|T[1-4])\b", value):
            chunks.append(NavigableString(value[position:match.start()]))
            tag = soup.new_tag("a", href="#source-"+match.group().lower(), attrs={"class": "reference"})
            tag.string = match.group()
            chunks.append(tag)
            position = match.end()
        chunks.append(NavigableString(value[position:]))
        for chunk in chunks:
            node.insert_before(chunk)
        node.extract()
    h1 = soup.find("h1")
    if h1:
        after = h1.find_next_sibling("p")
        if after and "작성 기준일" in after.get_text():
            after["class"] = "doc-date"
    toc_entries = [h for h in headings if h["level"] == 2]
    toc = "".join(f'<a href="#{html.escape(h["id"])}">{html.escape(h["title"])}</a>' for h in toc_entries)
    mobile = '<details class="mobile-toc"><summary>목차 바로가기</summary>' + toc + '</details>'
    if h1:
        h1.insert_before(BeautifulSoup(mobile, "html.parser"))
    source_hash = hashlib.sha256(original).hexdigest()
    final = f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(headings[0]['title'])}</title><meta name="description" content="AFPK 공모전 6단계 모니터링의 기능·데이터·개발 순서·검증 기준 전체 계획"><style>{CSS}</style></head>
<body><a class="skip" href="#main-content">본문으로 바로가기</a>
<aside><p class="brand">AFPK CHALLENGE 2026</p><p class="aside-title">6단계 모니터링<br>시스템 구현 계획</p><p class="aside-sub">실제 변화에서 다음 계획까지<br>개발 범위와 검증 기준</p><p class="toc-label">CONTENTS</p><nav aria-label="문서 목차">{toc}</nav><div class="aside-bottom">Markdown 전체 내용 · 오프라인 열람</div></aside>
<div class="page"><div class="tools"><span>팀 검토와 구현을 위한 상세 계획</span><div><a class="source-link" href="{html.escape(source.name)}">원본 MD</a><button type="button" onclick="window.print()">인쇄 · PDF</button></div></div>
<main id="main-content" class="document">{soup}<footer class="doc-footer">이 HTML은 원본 Markdown의 전체 내용을 변환한 열람본입니다. 구현 완료 상태를 뜻하지 않습니다.<br>원본 SHA-256 {source_hash}</footer></main></div>
<script>const links=[...document.querySelectorAll('aside nav a')];const observer=new IntersectionObserver(entries=>{{for(const entry of entries){{if(entry.isIntersecting){{links.forEach(link=>link.classList.toggle('active',link.hash==='#'+entry.target.id));}}}}}},{{rootMargin:'-6% 0px -74% 0px'}});document.querySelectorAll('main h2').forEach(heading=>observer.observe(heading));</script></body></html>'''
    output.write_text(final, encoding="utf-8")
    result = validate(text, final, headings, diagrams)
    result.update({"source": str(source), "output": str(output), "source_sha256": source_hash,
                   "source_unchanged": original == source.read_bytes()})
    return result


def validate(source: str, document: str, headings, diagrams) -> dict:
    soup = BeautifulSoup(document, "html.parser")
    main = soup.select_one("main")
    source_tokens = MarkdownIt("commonmark", {"html": False}).enable("table").parse(source)
    source_headings = [t for t in source_tokens if t.type == "heading_open"]
    source_tables = [t for t in source_tokens if t.type == "table_open"]
    assert len(source_headings) == len(main.find_all(re.compile(r"^h[1-6]$"))), "Heading coverage"
    assert len(source_tables) == len(main.find_all("table")), "Table coverage"
    # Compare all inline token text, preserving every paragraph/list/table item.
    inline_values = [t.content for t in source_tokens if t.type == "inline"]
    normalized = re.sub(r"\s+", "", main.get_text("", strip=True))
    converter = MarkdownIt("commonmark", {"html": False}).enable("table")
    for value in inline_values:
        plain = BeautifulSoup(converter.renderInline(value), "html.parser").get_text("", strip=True)
        assert re.sub(r"\s+", "", plain) in normalized, f"Missing inline content: {plain[:60]}"
    ids = {tag['id'] for tag in soup.find_all(id=True)}
    broken_anchors = [a['href'] for a in soup.select('a[href^="#"]') if a['href'][1:] not in ids]
    assert not broken_anchors, broken_anchors
    assert not soup.select('script[src], link[rel="stylesheet"], img[src^="http"]'), "External rendering asset"
    for token in source_tokens:
        if token.type == 'fence' and token.info.strip() != 'mermaid':
            assert token.content.rstrip() in main.get_text(), "Code fence coverage"
    return {"status": "PASS", "headings": len(source_headings), "tables": len(source_tables),
            "inline_blocks_checked": len(inline_values), "diagram": diagrams,
            "broken_anchors": broken_anchors, "external_assets": 0,
            "html_bytes": len(document.encode('utf-8'))}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
