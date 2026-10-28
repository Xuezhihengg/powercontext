"""离线可复现的确定性稠密向量：字符/词 n-gram 哈希嵌入（仅标准库）。

选型说明：为了在评审的干净环境（甚至离线环境）中稳定复现，稠密向量不依赖
任何需要下载模型的 embedding；检索质量的关键词部分由 seekdb 全文索引（IK 分词）
承担，向量负责近似词形与跨语言字符级召回。接口兼容 pyseekdb.EmbeddingFunction。
"""

from __future__ import annotations

import hashlib
import math
import re

from pyseekdb import EmbeddingFunction, register_embedding_function

DEFAULT_DIM = 256

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+|[\u4e00-\u9fff]{1,2}")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")


@register_embedding_function
class HashNGramEmbedding(EmbeddingFunction):
    def __init__(self, dim: int = DEFAULT_DIM) -> None:
        self._dim = dim

    def __call__(self, documents):
        return [self._embed(doc) for doc in documents]

    def _embed(self, doc: str) -> list[float]:
        vector = [0.0] * self._dim
        tokens = [t.lower() for t in _WORD_RE.findall(doc)]
        tokens.extend(_HAN_RE.findall(doc))  # 单字也入袋，提升中文召回
        for token in tokens:
            digest = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            index = digest % self._dim
            sign = 1.0 if (digest >> 16) % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    @property
    def dimension(self) -> int:
        return self._dim

    @staticmethod
    def name() -> str:
        return "hash-ngram-256"

    def get_config(self) -> dict:
        return {"dim": self._dim}

    @staticmethod
    def build_from_config(config: dict) -> "HashNGramEmbedding":
        return HashNGramEmbedding(dim=int(config.get("dim", DEFAULT_DIM)))
