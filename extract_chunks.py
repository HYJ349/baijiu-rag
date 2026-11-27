# -*- coding: utf-8 -*-
"""从年报 PDF 提取正文与表格，切成带来源元数据的块。

表格还原不依赖 find_tables()（该版本在部分页会崩溃），
改用 get_text('words') 的词坐标聚类：按 y 聚行、按 x 间隙分列。

输出: data/chunks/chunks.json
每块含: id / company / code / year / page / type / text / source
"""
import os
import re
import json
import time

import pymupdf

BASE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE, "data", "pdfs")
MANIFEST = os.path.join(BASE, "data", "manifest.json")
OUT_DIR = os.path.join(BASE, "data", "chunks")
OUT = os.path.join(OUT_DIR, "chunks.json")

MIN_LEN = 30          # 过短的文本块跳过
TARGET_LEN = 600      # 正文块目标长度
MAX_LEN = 950         # 单块上限
COL_GAP = 22.0        # 判定为不同列的 x 间隙
Y_TOL = 4.0           # 同一视觉行的 y 容差


def clean(text):
    if not text:
        return ""
    text = text.replace("\u3000", " ").replace("\xa0", " ").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def split_long(text, maxlen=MAX_LEN):
    """按句子边界拆长文本，避免切断语义。"""
    if len(text) <= maxlen:
        return [text]
    sents = re.split(r"(?<=[。；;！？!?])", text)
    parts, cur = [], ""
    for s in sents:
        if not s:
            continue
        if len(cur) + len(s) > maxlen and cur:
            parts.append(cur.strip())
            cur = s
        else:
            cur += s
    if cur.strip():
        parts.append(cur.strip())
    out = []
    for p in parts:
        while len(p) > maxlen:
            out.append(p[:maxlen])
            p = p[maxlen:]
        if p:
            out.append(p)
    return [x for x in out if len(x) >= MIN_LEN]


def page_visual_lines(words):
    """把 words 聚成视觉行，返回 [(is_table, line_text), ...]。"""
    rows = []
    for w in sorted(words, key=lambda a: ((a[1] + a[3]) / 2, a[0])):
        yc = (w[1] + w[3]) / 2
        if rows and abs(yc - rows[-1]["yc"]) <= Y_TOL:
            rows[-1]["ws"].append(w)
        else:
            rows.append({"yc": yc, "ws": [w]})
    lines = []
    for r in rows:
        ws = sorted(r["ws"], key=lambda a: a[0])
        cols, cur, prev = [], [ws[0]], ws[0][2]
        for w in ws[1:]:
            if w[0] - prev > COL_GAP:
                cols.append("".join(x[4] for x in cur))
                cur = [w]
            else:
                cur.append(w)
            prev = max(prev, w[2])
        cols.append("".join(x[4] for x in cur))
        cols = [clean(c) for c in cols if clean(c)]
        if not cols:
            continue
        # 页眉页脚（页码/报告名）过滤
        joined = " ".join(cols)
        if re.fullmatch(r"\d{1,4}", joined) or "年度报告全文" in joined and len(joined) < 30:
            continue
        lines.append((len(cols) >= 2, " | ".join(cols) if len(cols) >= 2 else cols[0]))
    return lines


def lines_to_blocks(lines, page):
    """把视觉行合并成表格块 / 正文块。"""
    blocks, buf, kind = [], [], None

    def flush():
        if not buf:
            return
        txt = clean("\n".join(buf))
        if len(txt) < MIN_LEN:
            return
        if kind == "table":
            for part in split_long(txt, MAX_LEN * 2):
                blocks.append({"page": page, "type": "table", "text": part})
        else:
            for part in split_long(txt, MAX_LEN):
                blocks.append({"page": page, "type": "text", "text": part})
        buf.clear()

    for is_table, text in lines:
        k = "table" if is_table else "text"
        if kind is not None and k != kind:
            flush()
        kind = k
        buf.append(text)
    flush()
    return blocks


def extract_one(path, company, code, year):
    doc = pymupdf.open(path)
    blocks = []
    for pno in range(len(doc)):
        try:
            words = doc[pno].get_text("words")
            lines = page_visual_lines(words)
            blocks.extend(lines_to_blocks(lines, pno + 1))
        except Exception as ex:
            print(f"  WARN page {pno+1}: {type(ex).__name__} {ex}", flush=True)
    doc.close()
    return blocks


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    all_chunks = []
    t0 = time.time()
    for i, item in enumerate(manifest, 1):
        path = os.path.join(PDF_DIR, item["file"])
        year_m = re.search(r"(20\d{2})", item.get("title", ""))
        year = int(year_m.group(1)) if year_m else 0
        blocks = extract_one(path, item["company"], item["code"], year)
        for j, b in enumerate(blocks, 1):
            all_chunks.append({
                "id": f"{item['code']}_{year}_p{b['page']:04d}_{j:03d}",
                "company": item["company"],
                "code": item["code"],
                "year": year,
                "page": b["page"],
                "type": b["type"],
                "text": b["text"],
                "source": f"{item['company']}{year}年年度报告 PDF 第{b['page']}页",
            })
        print(f"[{i}/{len(manifest)}] {item['company']} {year} -> {len(blocks)} blocks "
              f"({time.time()-t0:.0f}s)", flush=True)

    json.dump(all_chunks, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    stats = {
        "total_chunks": len(all_chunks),
        "table_chunks": sum(1 for c in all_chunks if c["type"] == "table"),
        "text_chunks": sum(1 for c in all_chunks if c["type"] == "text"),
        "companies": len(set(c["company"] for c in all_chunks)),
        "pdfs": len(manifest),
        "size_mb": round(os.path.getsize(OUT) / 1024 / 1024, 2),
        "seconds": round(time.time() - t0, 1),
    }
    json.dump(stats, open(os.path.join(OUT_DIR, "stats.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("DONE", json.dumps(stats, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
