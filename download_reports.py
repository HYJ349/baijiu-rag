"""从巨潮资讯网下载白酒公司的年度报告全文 PDF。"""
import os, json, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
COMPANIES = json.load(open(os.path.join(BASE, "baijiu_companies.json"), encoding="utf-8"))
OUT = os.path.join(BASE, "data", "pdfs")
os.makedirs(OUT, exist_ok=True)

QUERY = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
DL = "http://static.cninfo.com.cn/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
    "X-Requested-With": "XMLHttpRequest",
}

def query_reports(code, orgid, n=2):
    plates = {"6": "sse", "0": "szse", "3": "szse"}
    column = plates.get(code[0], "szse")
    data = {
        "pageNum": "1", "pageSize": "50", "column": column, "tabName": "fulltext",
        "plate": "", "stock": f"{code},{orgid}", "searchkey": "", "secid": "",
        "category": "category_ndbg_szsh;", "trade": "", "seDate": "2022-01-01~2026-12-31",
        "sortName": "time", "sortType": "desc", "isHLtitle": "true",
    }
    req = urllib.request.Request(QUERY, data=urllib.parse.urlencode(data).encode(), headers=HEADERS)
    j = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore"))
    anns = j.get("announcements") or []
    picked = []
    for a in anns:
        title = a.get("announcementTitle", "").replace("<em>", "").replace("</em>", "")
        if "英文" in title or "摘要" in title or "取消" in title:
            continue
        if "年度报告" not in title and "年报" not in title:
            continue
        url = a.get("adjunctUrl")
        if not url:
            continue
        picked.append((title, url, a.get("announcementTime")))
        if len(picked) >= n:
            break
    return picked

manifest = []
for name, code, orgid, _ in COMPANIES:
    safe = name.replace(" ", "")
    try:
        reps = query_reports(code, orgid, n=2)
    except Exception as e:
        print(f"[QUERY FAIL] {name}: {e}", flush=True)
        continue
    for i, (title, url, ts) in enumerate(reps):
        ext = os.path.splitext(url)[1] or ".PDF"
        year = "20" + url.split("/")[-2][:2] if False else ""
        fname = f"{safe}_{os.path.basename(url)}"
        path = os.path.join(OUT, fname)
        if not os.path.exists(path):
            try:
                req = urllib.request.Request(DL + url, headers={"User-Agent": HEADERS["User-Agent"]})
                data = urllib.request.urlopen(req, timeout=90).read()
                open(path, "wb").write(data)
                print(f"[OK] {name} {title} {len(data)//1024}KB", flush=True)
            except Exception as e:
                print(f"[DL FAIL] {name} {title}: {e}", flush=True)
                continue
        manifest.append({"company": safe, "code": code, "title": title, "file": fname, "url": DL + url})
        time.sleep(0.4)
    time.sleep(0.6)

json.dump(manifest, open(os.path.join(BASE, "data", "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"DONE files={len(manifest)}", flush=True)
