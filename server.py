# -*- coding: utf-8 -*-
"""年报问答知识库 · 本地服务。

启动: python server.py  → 浏览器打开 http://127.0.0.1:8765
纯标准库 HTTP 服务 + HybridRetriever，无额外 Web 依赖。
"""
import os
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from retriever import HybridRetriever

BASE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE, "web")
PORT = 8765

print("loading retriever ...", flush=True)
R = HybridRetriever.load()
print("server ready", flush=True)


def highlight(text, query):
    """把查询词在文本里标红（返回带 <mark> 的 HTML，已转义）。"""
    import html
    safe = html.escape(text)
    terms = [t for t in re.split(r"[^\w\u4e00-\u9fff]+", query) if len(t) >= 2]
    for t in sorted(set(terms), key=len, reverse=True)[:8]:
        safe = re.sub(re.escape(t), lambda m: f"<mark>{m.group(0)}</mark>", safe,
                      flags=re.IGNORECASE)
    return safe


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            p = os.path.join(WEB_DIR, "index.html")
            if os.path.exists(p):
                self._send(200, open(p, "rb").read(), "text/html; charset=utf-8")
            else:
                self._send(404, "index.html missing", "text/plain; charset=utf-8")
        elif path == "/api/meta":
            self._send(200, json.dumps({
                "companies": R.companies,
                "years": R.years,
                "chunks": len(R.chunks),
                "example_questions": [
                    "贵州茅台2024年的营业总收入是多少？",
                    "五粮液2025年的净利润是多少？",
                    "i茅台平台2024年的销售收入是多少？",
                    "泸州老窖2024年营业收入和2023年相比增长了多少？",
                    "山西汾酒2025年省内销售占比是多少？",
                    "哪家公司2024年的营业总收入最高？",
                    "12家白酒公司2024年营业总收入排名",
                    "哪些公司2025年提到了直销渠道？",
                    "古井贡酒2024年的毛利率是多少？",
                    "洋河股份2025年经营活动现金流净额是多少？",
                ],
            }, ensure_ascii=False))
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/search":
            self._send(404, "not found")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        query = body.get("query", "").strip()
        company = body.get("company") or None
        year = body.get("year") or None
        topk = min(int(body.get("topk", 5)), 20)
        if not query:
            self._send(200, json.dumps({"results": []}, ensure_ascii=False))
            return
        hits = R.search(query, topk=topk, company=company, year=year)
        results = []
        for c, score in hits:
            results.append({
                "company": c["company"], "code": c["code"], "year": c["year"],
                "page": c["page"], "type": c["type"], "source": c["source"],
                "text": highlight(c["text"], query),
                "raw": c["text"], "score": score,
                "bm25_rank": c.get("_bm25_rank"), "tfidf_rank": c.get("_tfidf_rank"),
            })
        self._send(200, json.dumps({"query": query, "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"http://127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()
