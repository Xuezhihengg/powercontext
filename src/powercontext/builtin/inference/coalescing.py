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

"""Coalesce concurrent Embedding work and cache successful vectors.

One wrapper instance owns a single event-loop queue. Calls that overlap inside
the coalescing window, including calls that arrive while a request is already
executing, share each distinct text. Every call still receives vectors in its
own original order (duplicates preserved) and is charged only for the distinct
underlying batches it actually waited on.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import EmbeddingProfile
    from powercontext.builtin.inference.protocols import EmbeddingModel

_COUNT_THRESHOLD_ERROR = "must be a positive integer"
_CACHE_SIZE_ERROR = "must be a non-negative integer"
_COALESCE_ERROR = "must be a non-negative number of milliseconds"
_VECTOR_COUNT_ERROR = "embedding vector count does not match the batch"


@dataclass(slots=True)
class _Batch:
    """One distinct text batch accepted for a single underlying request."""

    token: int
    texts: tuple[str, ...]
    usage: InferenceUsage = field(default_factory=lambda: InferenceUsage(requests=0))


@dataclass(slots=True)
class _TextWork:
    """Shared work for one distinct text, reused by every waiting call."""

    text: str
    future: asyncio.Future[None]
    batch: _Batch | None = None
    vector: EmbeddingVector | None = None


class CoalescingEmbeddingModel:
    """Merge concurrent Embedding requests and reuse successful vectors.

    ``max_batch_size`` bounds the distinct texts of one underlying request,
    ``coalesce_ms`` sets how long new texts may join the next batch, and
    ``cache_size`` bounds the cross-call LRU of successful vectors. Setting the
    cache to zero disables cross-call reuse but still shares in-flight work.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        _require_positive_int("max_batch_size", max_batch_size)
        _require_non_negative_int("cache_size", cache_size)
        if isinstance(coalesce_ms, bool) or not isinstance(coalesce_ms, int | float) or coalesce_ms < 0:
            raise ValueError(_COALESCE_ERROR)
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = float(coalesce_ms) / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._pending: dict[str, _TextWork] = {}
        self._queue: deque[_TextWork] = deque()
        self._next_token = 0
        self._drain_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def profile(self) -> EmbeddingProfile:
        return self._model.profile

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Return one ordered vector per input text, sharing distinct texts."""

        if not texts:
            return EmbeddingResult(vectors=())

        cached: dict[str, EmbeddingVector] = {}
        works: dict[str, _TextWork] = {}
        queued = False
        for text in texts:
            if text in cached or text in works:
                continue
            if self._cache_size > 0 and text in self._cache:
                # A hit refreshes recency so the LRU tracks actual access.
                self._cache.move_to_end(text)
                cached[text] = self._cache[text]
                continue
            work = self._pending.get(text)
            if work is None:
                work = _TextWork(text=text, future=asyncio.get_running_loop().create_future())
                work.future.add_done_callback(_retrieve_future_exception)
                self._pending[text] = work
                self._queue.append(work)
                queued = True
            works[text] = work

        if queued:
            self._ensure_drain()
        if works:
            # Shield the shared work: cancelling this call must not cancel a
            # request other calls are still waiting on.
            await asyncio.gather(*(asyncio.shield(work.future) for work in works.values()))

        vectors = tuple(cached[text] if text in cached else _resolved_vector(works[text]) for text in texts)
        batches: dict[int, _Batch] = {}
        for work in works.values():
            if work.batch is not None:
                batches[work.batch.token] = work.batch
        usage = _sum_usage(batch.usage for batch in batches.values())
        return EmbeddingResult(vectors=vectors, usage=usage)

    def _ensure_drain(self) -> None:
        if self._drain_task is None:
            task = asyncio.get_running_loop().create_task(self._drain())
            self._drain_task = task
            task.add_done_callback(self._drain_finished)

    def _drain_finished(self, task: asyncio.Task[None]) -> None:
        self._drain_task = None
        if not task.cancelled():
            task.exception()
        if self._queue:
            self._ensure_drain()

    async def _drain(self) -> None:
        if self._coalesce_seconds > 0:
            await asyncio.sleep(self._coalesce_seconds)
        loop = asyncio.get_running_loop()
        while self._queue:
            works = tuple(self._queue.popleft() for _ in range(min(self._max_batch_size, len(self._queue))))
            batch = _Batch(token=self._next_batch_token(), texts=tuple(work.text for work in works))
            for work in works:
                work.batch = batch
            task = loop.create_task(self._run_batch(batch, works))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _next_batch_token(self) -> int:
        self._next_token += 1
        return self._next_token

    async def _run_batch(self, batch: _Batch, works: tuple[_TextWork, ...]) -> None:
        try:
            result = await self._model.embed(batch.texts)
            vectors = tuple(tuple(vector) for vector in result.vectors)
            _require_vector_count(vectors, len(works))
        except asyncio.CancelledError as error:
            self._release(works)
            self._fail(works, error)
            raise
        except Exception as error:
            # A failed batch is never cached; later calls retry the same text.
            self._release(works)
            self._fail(works, error)
        else:
            batch.usage = result.usage
            for work, vector in zip(works, vectors, strict=True):
                work.vector = vector
            self._remember(batch.texts, vectors)
            self._release(works)
            for work in works:
                if not work.future.done():
                    work.future.set_result(None)

    def _release(self, works: tuple[_TextWork, ...]) -> None:
        for work in works:
            if self._pending.get(work.text) is work:
                del self._pending[work.text]

    @staticmethod
    def _fail(works: tuple[_TextWork, ...], error: BaseException) -> None:
        for work in works:
            if not work.future.done():
                work.future.set_exception(error)

    def _remember(self, texts: tuple[str, ...], vectors: tuple[EmbeddingVector, ...]) -> None:
        if self._cache_size <= 0:
            return
        for text, vector in zip(texts, vectors, strict=True):
            self._cache[text] = vector
            self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _resolved_vector(work: _TextWork) -> EmbeddingVector:
    vector = work.vector
    if vector is None:
        raise RuntimeError("embedding work completed without a vector")  # noqa: TRY003
    return vector


def _require_vector_count(vectors: tuple[EmbeddingVector, ...], expected: int) -> None:
    if len(vectors) != expected:
        raise ValueError(_VECTOR_COUNT_ERROR)


def _retrieve_future_exception(future: asyncio.Future[None]) -> None:
    # Waiters that were cancelled may leave no consumer; keep asyncio from
    # logging an unobserved failure for work the wrapper already handled.
    if not future.cancelled():
        future.exception()


def _sum_usage(items: Iterable[InferenceUsage]) -> InferenceUsage:
    requests = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    for usage in items:
        requests += usage.requests
        if usage.input_tokens is not None:
            input_tokens = (input_tokens or 0) + usage.input_tokens
        if usage.output_tokens is not None:
            output_tokens = (output_tokens or 0) + usage.output_tokens
    return InferenceUsage(requests=requests, input_tokens=input_tokens, output_tokens=output_tokens)


def _require_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} {_COUNT_THRESHOLD_ERROR}")  # noqa: TRY003


def _require_non_negative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} {_CACHE_SIZE_ERROR}")  # noqa: TRY003


__all__ = ["CoalescingEmbeddingModel"]
