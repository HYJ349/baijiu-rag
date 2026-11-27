# -*- coding: utf-8 -*-
"""独立构建索引：从 retriever 模块导入类，确保 pickle 记录的tokenize归属 retriever 模块。"""
from retriever import HybridRetriever

r = HybridRetriever()
r.save()
print("INDEX BUILT OK", flush=True)
