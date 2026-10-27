# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""HTTP cross-encoder reranking with request batching and global selection."""

from __future__ import annotations

import math
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

DEFAULT_HTTP_RERANK_POLICY_ID = "http-cross-encoder-v1"


class HTTPMemoryReranker:
    """Score Memory candidates through a batching HTTP rerank endpoint."""

    policy_id: str

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = DEFAULT_HTTP_RERANK_POLICY_ID,
    ) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Score every candidate once and select by the complete score pool."""

        _validate_bounds(len(candidates), limit)
        scores: dict[int, float] = {}
        requests = 0
        for offset in range(0, len(candidates), self._batch_size):
            batch = candidates[offset : offset + self._batch_size]
            ranks = tuple(range(offset + 1, offset + len(batch) + 1))
            payload = {
                "query": query,
                "candidates": [
                    {"rank": rank, "text": candidate.text} for rank, candidate in zip(ranks, batch, strict=True)
                ],
            }
            response = await self._client.post(self._endpoint, json=payload)
            requests += 1
            response.raise_for_status()
            scores.update(_parse_scores(response, ranks))

        ordered = sorted(scores, key=lambda rank: (-scores[rank], rank))
        return MemoryRerankDecision(
            selected_ranks=tuple(ordered[:limit]),
            usage=InferenceUsage(requests=requests),
        )


def _validate_bounds(candidate_count: int, limit: int) -> None:
    if candidate_count < 1:
        raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
    if type(limit) is not int or limit < 1 or limit > candidate_count:
        raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003


def _parse_scores(response: httpx.Response, expected_ranks: tuple[int, ...]) -> dict[int, float]:
    try:
        payload: Any = response.json()
    except ValueError as error:
        raise ValueError("reranker response must be valid JSON") from error  # noqa: TRY003

    if not isinstance(payload, dict) or set(payload) != {"scores"}:
        raise ValueError("reranker response must contain exactly scores")  # noqa: TRY003
    raw_scores = payload["scores"]
    if not isinstance(raw_scores, list):
        raise ValueError("reranker scores must be a list")  # noqa: TRY003, TRY004

    expected = set(expected_ranks)
    scores: dict[int, float] = {}
    for item in raw_scores:
        _parse_score_item(item, expected, scores)

    if set(scores) != expected:
        raise ValueError("reranker scores must cover each request rank exactly once")  # noqa: TRY003
    return scores


def _parse_score_item(item: Any, expected: set[int], scores: dict[int, float]) -> None:
    if not isinstance(item, dict) or set(item) != {"rank", "score"}:
        raise ValueError("each reranker score must contain exactly rank and score")  # noqa: TRY003
    rank = item["rank"]
    score = item["score"]
    if type(rank) is not int or rank not in expected:
        raise ValueError("reranker score rank is outside its request batch")  # noqa: TRY003
    if rank in scores:
        raise ValueError("reranker score rank must not be duplicated")  # noqa: TRY003
    if type(score) not in (int, float):
        raise ValueError("reranker score must be a finite number")  # noqa: TRY003
    try:
        numeric = float(score)
    except OverflowError as error:
        raise ValueError("reranker score must be a finite number") from error  # noqa: TRY003
    if not math.isfinite(numeric):
        raise ValueError("reranker score must be a finite number")  # noqa: TRY003
    scores[rank] = numeric


__all__ = ["DEFAULT_HTTP_RERANK_POLICY_ID", "HTTPMemoryReranker"]
