"""seekdb 存储层：工程资料集合的建库、写入与混合检索，并记录检索日志。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pyseekdb
from pyseekdb import AdminClient, FulltextIndexConfig, HNSWConfiguration, Schema, VectorIndexConfig

from sdd_context.embedding import HashNGramEmbedding

COLLECTION = "eng_docs"
DATABASE = "sdd_ctx"


class SeekStore:
    """一个项目对应一个嵌入式 seekdb 数据库文件。"""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "seekdb.db"
        admin = AdminClient(path=str(self.db_path))
        try:
            admin.create_database(DATABASE)
        except Exception:  # 已存在
            pass
        self.client = pyseekdb.Client(path=str(self.db_path), database=DATABASE)
        dim = HashNGramEmbedding().dimension
        schema = Schema(
            vector_index=VectorIndexConfig(
                hnsw=HNSWConfiguration(dimension=dim, distance="cosine"),
                embedding_function=HashNGramEmbedding(dim),
            ),
            fulltext_index=FulltextIndexConfig(analyzer="ik"),
        )
        self.collection = self.client.get_or_create_collection(COLLECTION, schema=schema)
        self.last_get_logs: list[dict[str, Any]] = []

    # ---------- 写入 ----------
    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        if not ids:
            return
        self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def delete(self, ids: list[str]) -> None:
        if ids:
            self.collection.delete(ids=ids)

    def refresh(self) -> None:
        self.collection.refresh_index()

    def count(self) -> int:
        return int(self.collection.count())

    # ---------- 检索 ----------
    def hybrid(self, kind: str, text: str, n_results: int = 8) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """按资料类别做混合检索（全文 $contains + 向量），RRF 融合排序。"""
        query = {
            "where_document": {"$contains": text},
            "where": {"kind": kind},
            "n_results": n_results,
        }
        knn = {"query_texts": text, "where": {"kind": kind}, "n_results": n_results}
        result = self.collection.hybrid_search(
            query=query,
            knn=knn,
            rank={"rrf": {"rank_window_size": 30, "rank_constant": 20}},
            n_results=n_results,
            include=["metadatas", "documents"],
        )
        hits: list[dict[str, Any]] = []
        ids = (result.get("ids") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        for doc_id, meta, doc in zip(ids, metas, docs):
            hits.append({"id": doc_id, "metadata": meta, "document": doc})
        log = {
            "engine": "seekdb.hybrid_search",
            "collection": COLLECTION,
            "database_path": str(self.db_path),
            "where": {"kind": kind},
            "query": {"where_document": {"$contains": _clip(text)}},
            "knn": {"query_texts": _clip(text)},
            "rank": {"rrf": {"rank_window_size": 30, "rank_constant": 20}},
            "n_results": n_results,
            "returned_ids": ids,
        }
        return hits, log

    def fetch_by_source(self, kind: str, source: str) -> list[dict[str, Any]]:
        """按元数据精确取回某文件的全部已索引块（用于规格同文档扩展）。"""
        result = self.collection.get(where={"kind": kind, "source": source}, include=["metadatas", "documents"])
        hits = []
        ids = result.get("ids") or []
        metas = result.get("metadatas") or []
        docs = result.get("documents") or []
        for doc_id, meta, doc in zip(ids, metas, docs):
            hits.append({"id": doc_id, "metadata": meta, "document": doc})
        log = {"engine": "seekdb.get", "collection": COLLECTION, "where": {"kind": kind, "source": source}, "returned_ids": ids}
        self.last_get_logs.append(log)
        return hits

    @staticmethod
    def content_sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _clip(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[:limit] + "…"
