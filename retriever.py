# -*- coding: utf-8 -*-
"""混合检索器：BM25 关键词召回 + TF-IDF 向量余弦召回，RRF 融合排序。

设计要点（对应课程"知识深加工·深度二：向量 RAG"）：
- 两路独立召回，分数尺度不同，用 RRF(Reciprocal Rank Fusion) 融合，避免分数不可比
- 中文用 jieba 分词；同时保留单字 bigram 兜底，缓解专有名词切分错误
- 公司名/年份作为强过滤条件，支持"某公司某年"的定向问答
- 纯 sklearn 实现，无需下载大模型，本地可跑
"""
import os
import re
import json
import pickle
import joblib

import jieba
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

BASE = os.path.dirname(os.path.abspath(__file__))
CHUNKS = os.path.join(BASE, "data", "chunks", "chunks.json")
INDEX_DIR = os.path.join(BASE, "index")
BM25_PATH = os.path.join(INDEX_DIR, "bm25.pkl")
TFIDF_PATH = os.path.join(INDEX_DIR, "tfidf.pkl")
MATRIX_PATH = os.path.join(INDEX_DIR, "tfidf_matrix.npz")

# 财报高频领域词，加入 jieba 词库避免被切碎
DOMAIN_TERMS = [
    "营业总收入", "营业收入", "净利润", "归母净利润", "扣非净利润", "毛利率",
    "净利率", "资产负债率", "经营活动现金流", "每股收益", "净资产收益率",
    "经销商", "直销渠道", "批发代理", "i茅台", "茅台酒", "系列酒",
    "五粮液", "普五", "泸州老窖", "国窖1573", "山西汾酒", "玻汾",
    "洋河股份", "梦之蓝", "海之蓝", "古井贡酒", "年份原浆", "今世缘",
    "口子窖", "水井坊", "舍得酒业", "酒鬼酒", "迎驾贡酒",
    "预收款", "合同负债", "存货", "基酒", "产能", "吨酒价格",
]
for t in DOMAIN_TERMS:
    jieba.add_word(t)


def tokenize(text):
    """jieba 分词 + 过滤标点，保留数字与英文。"""
    text = re.sub(r"[^\w\u4e00-\u9fff.]", " ", text)
    toks = [t.lower() for t in jieba.lcut(text) if t.strip()]
    return toks


class HybridRetriever:
    def __init__(self, chunks=None):
        self.chunks = chunks if chunks is not None else json.load(open(CHUNKS, encoding="utf-8"))
        self._build()

    def _build(self):
        os.makedirs(INDEX_DIR, exist_ok=True)
        corpus = [c["text"] for c in self.chunks]
        print(f"building index over {len(corpus)} chunks ...", flush=True)
        tokenized = [tokenize(t) for t in corpus]
        # BM25
        self.bm25 = BM25Okapi(tokenized)
        # TF-IDF 向量（word 1-2gram）
        self.vectorizer = TfidfVectorizer(
            tokenizer=tokenize, token_pattern=None,
            ngram_range=(1, 2), min_df=2, max_features=200000,
            sublinear_tf=True,
        )
        self.matrix = normalize(self.vectorizer.fit_transform(corpus))
        self.companies = sorted(set(c["company"] for c in self.chunks))
        self.years = sorted(set(c["year"] for c in self.chunks))
        print(f"index ready: vocab={len(self.vectorizer.vocabulary_)} "
              f"companies={len(self.companies)} years={self.years}", flush=True)

    def save(self):
        with open(BM25_PATH, "wb") as f:
            pickle.dump(self.bm25, f)
        joblib.dump(self.vectorizer, TFIDF_PATH)
        import scipy.sparse as sp
        sp.save_npz(MATRIX_PATH, self.matrix)
        print("index saved", flush=True)

    @staticmethod
    def load():
        r = HybridRetriever.__new__(HybridRetriever)
        r.chunks = json.load(open(CHUNKS, encoding="utf-8"))
        with open(BM25_PATH, "rb") as f:
            r.bm25 = pickle.load(f)
        r.vectorizer = joblib.load(TFIDF_PATH)
        import scipy.sparse as sp
        r.matrix = sp.load_npz(MATRIX_PATH)
        r.companies = sorted(set(c["company"] for c in r.chunks))
        r.years = sorted(set(c["year"] for c in r.chunks))
        return r

    def _rank_bm25(self, query, candidate_idx, topk):
        scores = self.bm25.get_scores(tokenize(query))
        scored = [(scores[i], i) for i in candidate_idx]
        scored.sort(reverse=True)
        return [i for _, i in scored[:topk]]

    def _rank_tfidf(self, query, candidate_idx, topk):
        qv = self.vectorizer.transform([query])
        qv = normalize(qv)
        scores = (self.matrix[candidate_idx] @ qv.T).toarray().ravel()
        order = scores.argsort()[::-1][:topk]
        return [candidate_idx[i] for i in order]

    @staticmethod
    def _rrf(rankings, k=60):
        """Reciprocal Rank Fusion: score = sum(1/(k+rank))。"""
        fused = {}
        for ranking in rankings:
            for rank, idx in enumerate(ranking, 1):
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
        return sorted(fused, key=lambda i: fused[i], reverse=True)

    def _rewrite_query(self, query, company=None, year=None):
        """剥离公司名、年份、疑问词，避免高频词主导；返回检索意图词。"""
        q = query
        # 去掉公司全称与简称
        aliases = {
            "贵州茅台": ["贵州茅台", "茅台"], "五粮液": ["五粮液"],
            "泸州老窖": ["泸州老窖", "老窖"], "山西汾酒": ["山西汾酒", "汾酒"],
            "洋河股份": ["洋河股份", "洋河"], "古井贡酒": ["古井贡酒", "古井"],
            "今世缘": ["今世缘"], "口子窖": ["口子窖"], "水井坊": ["水井坊"],
            "舍得酒业": ["舍得酒业", "舍得"], "酒鬼酒": ["酒鬼酒"],
            "迎驾贡酒": ["迎驾贡酒", "迎驾"],
        }
        names = aliases.get(company, []) if company else []
        for n in sorted(names, key=len, reverse=True):
            q = q.replace(n, "")
        # 去掉年份与疑问/量词
        q = re.sub(r"20\d{2}\s*年?", "", q)
        # 只删疑问词和修饰性泛化词；保留"收入/销售/利润"等指标词（它们是检索意图本身）
        stop = ["情况如何", "是多少", "多少", "什么", "哪家", "哪些", "几个", "怎么样",
                "请问", "一下", "的情况", "情况", "渠道", "平台", "占比", "排名",
                "的", "了", "和", "与", "及", "？", "?", "，", ",", "。"]
        for w in sorted(stop, key=len, reverse=True):
            q = q.replace(w, " ")
        q = re.sub(r"\s+", " ", q).strip()
        return q if len(q) >= 2 else query  # 改写后太短则用原查询

    def search(self, query, topk=5, company=None, year=None, type_filter=None):
        """返回 [(chunk, score), ...]。company/year/type_filter 为可选强过滤。"""
        n = len(self.chunks)
        idxs = list(range(n))
        if company:
            idxs = [i for i in idxs if company in self.chunks[i]["company"]]
        if year:
            idxs = [i for i in idxs if self.chunks[i]["year"] == int(year)]
        if type_filter:
            idxs = [i for i in idxs if self.chunks[i]["type"] == type_filter]
        if not idxs:
            return []

        q = self._rewrite_query(query, company, year)
        pool = min(max(topk * 8, 50), len(idxs))
        r_bm25 = self._rank_bm25(q, idxs, pool)
        r_tfidf = self._rank_tfidf(q, idxs, pool)
        fused = self._rrf([r_bm25, r_tfidf])[:topk]
        out = []
        for i in fused:
            c = dict(self.chunks[i])
            c["_bm25_rank"] = r_bm25.index(i) + 1 if i in r_bm25 else None
            c["_tfidf_rank"] = r_tfidf.index(i) + 1 if i in r_tfidf else None
            out.append((c, round(1.0 / (60 + fused.index(i) + 1), 5)))
        return out


if __name__ == "__main__":
    r = HybridRetriever()
    r.save()
    for q in ["2024年营业总收入是多少", "i茅台销售收入", "直销渠道收入占比"]:
        print("\n=== Q:", q)
        for c, s in r.search(q, topk=3):
            print(f"  [{s}] {c['company']}{c['year']} p{c['page']} ({c['type']})")
            print("   ", c["text"][:140].replace("\n", " / "))
