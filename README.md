# 白酒年报问答知识库 · 第三课作业 A

从巨潮资讯网下载 12 家白酒上市公司 2024、2025 两年共 24 份真实年报，构建可溯源的问答知识库。
问任何问题，系统从年报原文里检索证据片段，并标出**公司 / 年份 / PDF 页码**。

## 交付内容映射（对应作业要求）

| 作业要求 | 本项目对应 |
|---|---|
| 下载 10 家以上公司财报 | `data/pdfs/` 24 份 PDF（12 家 × 2 年），来源巨潮资讯网 |
| 提取文字 + 表格还原 | `extract_chunks.py`：坐标聚类还原表格为「列 \| 列」结构，28,498 块 |
| 向量 + BM25 | `retriever.py`：TF-IDF 向量余弦 + BM25 关键词，RRF 融合排序 |
| 出 10 道题（含 2 道跨公司题） | `tests/run_tests.py` + `tests/results.md`（原始召回）+ `tests/evaluation.md`（逐题答案/页码/判定/失败原因）。真实分层：5 可答 / 3 部分 / 2 失败 |
| 页面截图 | `tests/page_screenshot.png` |
| 一页结论 | `tests/一页结论.pdf`（A4 单页，含代表性结果 + 两道全景题表现 + 失败原因；HTML 源 `tests/conclusion_print.html`） |

## 对应老师批语的逐项落实

- **12 家公司具体报告入口**：`data/manifest.json` —— 24 条官方年报 URL（巨潮资讯 static.cninfo.com.cn），含公司、代码、标题、文件名、下载地址。
- **索引 / 表格 / 出处代码**：`build_index.py`（BM25+TF-IDF 索引）、`extract_chunks.py`（词坐标聚类还原表格、带页码出处）、`retriever.py`（检索 + 查询改写）；三者都能从下载脚本一路重建。
- **10 题记录（含 2 道全景题）**：`tests/results.md` + `tests/evaluation.md`，后者逐题写真实答案、召回原文与页码、判定和失败原因。
- **一页结论 PDF**：`tests/一页结论.pdf`，已把最有代表性的结果、两道全景题表现和失败原因收束为 A4 单页。
- **负面结果如实保留**：老师批语「不要求先把所有错题改对」——第 9、10 题（全景排序）与第 3、4、6 题（表头/数值分离）均按失败/部分如实记录，未事后修改检索结果。

## 运行方式

环境：Python 3.13，依赖 `pymupdf scikit-learn rank_bm25 jieba joblib scipy`。

```bash
# 1. 从零重建（可选，索引已构建好）
python download_reports.py      # 下载年报
python extract_chunks.py        # 提取正文与表格 → data/chunks/chunks.json
python build_index.py           # 构建 BM25 + TF-IDF 索引 → index/

# 2. 启动问答服务
python server.py
# 浏览器打开 http://127.0.0.1:8765

# 3. 运行测试
python tests/run_tests.py       # 需服务已启动，输出 tests/results.md
```

## 项目结构

```
baijiu-rag/
├── download_reports.py    # 巨潮资讯网年报下载（orgId 查询 + 公告接口）
├── extract_chunks.py      # PDF 正文/表格提取与切块
├── retriever.py           # 混合检索器（BM25 + TF-IDF + RRF + 查询改写）
├── build_index.py         # 独立索引构建入口
├── server.py              # 本地 HTTP 服务（标准库，无 Flask 依赖）
├── web/index.html         # 问答前端页面
├── data/
│   ├── pdfs/              # 24 份年报原件
│   ├── manifest.json      # 年报清单（公司/代码/标题/来源URL）
│   └── chunks/            # chunks.json + stats.json
├── index/                 # bm25.pkl / tfidf.pkl / tfidf_matrix.npz
└── tests/                 # 测试脚本、结果、页面截图
```

## 数据一览

- 公司：贵州茅台、五粮液、泸州老窖、山西汾酒、洋河股份、古井贡酒、今世缘、口子窖、水井坊、舍得酒业、酒鬼酒、迎驾贡酒
- 年份：2024、2025
- 知识块：28,498（表格 17,750 / 正文 10,748）

## 技术说明

- **表格还原**：PyMuPDF 的 `find_tables()` 在该版本对部分页会段错误，改用 `get_text("words")` 的词坐标聚类——按 y 中心聚成视觉行、按 x 间隙（22pt）分列，连续的表格行合并成块。实测财报表格还原为「项目 | 2024年度 | 2023年度」结构。
- **查询改写**：从问题里剥离公司名、年份、疑问词和修饰性泛化词（渠道/平台/情况），保留「营业总收入/净利润/直销/i茅台」等区分度高的指标词。这是让单公司细节题的**术语召回**更稳的关键（注意：术语命中 ≠ 能答对，严格判定见 `tests/evaluation.md`）。
- **RRF 融合**：BM25 与 TF-IDF 的分数尺度不同，不做加权求和，而按各自排名用 `1/(60+rank)` 融合，避免尺度不可比。
- **可溯源优先**：系统返回原文证据片段而非生成式答案，每个片段都带精确出处——这是课程强调的「可溯源」，也避免了大模型幻觉。
