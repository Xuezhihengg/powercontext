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

"""Select query-relevant literal fragments from recalled Memory entries."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import pairwise
from typing import Final, Protocol

from powercontext.artifacts import ArtifactAddress, ArtifactRef
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

_BEGIN_MARKER = "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
_END_MARKER = "END_POWERCONTEXT_PREPARED_CONTEXT_V1"
_TOKEN = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
_POSITION_WEIGHT: Final = 1.5
_FIRST_SENTENCE_WEIGHT: Final = 0.15
_DOCUMENT_WEIGHT: Final = 0.15
_COVERAGE_WEIGHT: Final = 0.5
_BIGRAM_WEIGHT: Final = 1.0
_BYTES_MARGIN: Final = 16
_MAX_WINDOW_SENTENCES: Final = 64
_MAX_VERIFIED_WINDOWS: Final = 32
_STOPWORDS = frozenset({
    "a",
    "about",
    "after",
    "against",
    "all",
    "also",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "before",
    "been",
    "being",
    "between",
    "both",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "has",
    "have",
    "he",
    "her",
    "here",
    "his",
    "how",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "may",
    "might",
    "more",
    "most",
    "no",
    "not",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "out",
    "over",
    "same",
    "she",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "under",
    "up",
    "very",
    "was",
    "we",
    "were",
    "when",
    "where",
    "which",
    "while",
    "who",
    "why",
    "will",
    "with",
    "would",
})


class _MemoryCandidates(Protocol):
    scope_id: str
    memory_ref: ArtifactRef | None
    hits: tuple[MemoryHit, ...]


@dataclass(frozen=True)
class MemoryEntryAddress:
    """Identify one exact Memory entry version across Scope boundaries."""

    memory: ArtifactAddress
    entry_id: str
    entry_version_id: str


@dataclass(frozen=True)
class PreparedMemoryFragment:
    """One literal slice of a recalled Memory entry."""

    address: MemoryEntryAddress
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class EvidenceSelection:
    """A complete literal-evidence selection and its rendered context."""

    content: str | None
    fragments: tuple[PreparedMemoryFragment, ...] = ()


@dataclass(frozen=True)
class _Sentence:
    start: int
    end: int
    stems: frozenset[str]
    terms: tuple[str, ...]
    value: float = 0.0


@dataclass(frozen=True)
class _Entry:
    scope_id: str
    memory_ref: ArtifactRef
    entry_id: str
    entry_version_id: str
    text: str
    order: int
    sentences: tuple[_Sentence, ...]
    escaped: tuple[int, ...]
    overhead: int

    def escaped_bytes(self, start: int, end: int) -> int:
        """Return the JSON-escaped UTF-8 bytes of ``text[start:end]`` inside a string."""

        return self.escaped[end] - self.escaped[start]


@dataclass(frozen=True)
class _Window:
    entry: _Entry
    first: int
    last: int
    score: float


def select_evidence(
    *,
    query: str,
    memory_candidates: Sequence[_MemoryCandidates],
    max_bytes: int,
) -> EvidenceSelection:
    """Rank literal Memory sentences by the query and fit the best window into the byte budget."""

    entries = _candidate_entries(memory_candidates)
    if not entries:
        return EvidenceSelection(content=None)
    query_terms = _query_terms(query)
    if not query_terms:
        return EvidenceSelection(content=None)
    scored = _score(entries, query_terms)
    window = _best_window(scored, max_bytes) or _fallback_window(scored, max_bytes)
    if window is None:
        return EvidenceSelection(content=None)
    first, last = _expand(window, max_bytes=max_bytes)
    fragment = _window_fragment(window.entry, first, last)
    content = render_evidence((fragment,))
    if len(content.encode("utf-8")) > max_bytes:
        raise PreparedContextInvariantError("output-budget")
    return EvidenceSelection(content=content, fragments=(fragment,))


def render_evidence(fragments: Sequence[PreparedMemoryFragment]) -> str:
    """Render the existing trust envelope with per-fragment citation and coordinates."""

    envelope = {
        "trust": "untrusted_history",
        "items": [_evidence_item(fragment) for fragment in fragments],
    }
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    return "\n\n".join((TRUST_POLICY, f"{_BEGIN_MARKER}\n{encoded}\n{_END_MARKER}"))


def _candidate_entries(memory_candidates: Sequence[_MemoryCandidates]) -> tuple[_Entry, ...]:
    entries: list[_Entry] = []
    seen: set[tuple[str, str, str, int, str, str, str]] = set()
    order = 0
    for candidates in memory_candidates:
        if candidates.hits and candidates.memory_ref is None:
            raise PreparedContextInvariantError("memory-ref-missing")
        for hit in candidates.hits:
            if hit.memory_ref != candidates.memory_ref:
                raise PreparedContextInvariantError("memory-ref-mismatch")
            if not hit.entry_id.strip() or not hit.entry_version_id.strip() or not hit.text.strip():
                continue
            identity = (
                candidates.scope_id,
                hit.memory_ref.family,
                hit.memory_ref.artifact_id,
                hit.memory_ref.revision,
                hit.entry_id,
                hit.entry_version_id,
                hit.text,
            )
            if identity in seen:
                continue
            seen.add(identity)
            sentences = _sentences(hit.text)
            if not sentences:
                continue
            entry = _Entry(
                scope_id=candidates.scope_id,
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
                text=hit.text,
                order=order,
                sentences=sentences,
                escaped=_escaped_prefix(hit.text),
                overhead=0,
            )
            entries.append(replace(entry, overhead=_overhead(entry)))
            order += 1
    return tuple(entries)


def _sentences(text: str) -> tuple[_Sentence, ...]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for boundary in _SENTENCE_BOUNDARY.finditer(text):
        spans.append((cursor, boundary.start()))
        cursor = boundary.end()
    spans.append((cursor, len(text)))

    sentences: list[_Sentence] = []
    for start, end in spans:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start >= end:
            continue
        value = text[start:end]
        terms = tuple(_stem(term) for term in _TOKEN.findall(value.casefold()))
        if not terms:
            continue
        sentences.append(_Sentence(start=start, end=end, stems=frozenset(terms), terms=terms))
    return tuple(sentences)


def _query_terms(query: str) -> tuple[str, ...]:
    terms = tuple(_TOKEN.findall(query.casefold()))
    content = tuple(term for term in terms if term not in _STOPWORDS)
    return content or terms


def _stem(term: str) -> str:
    if term.isdigit():
        return term
    for suffix, replacement in (
        ("ization", "ize"),
        ("isation", "ize"),
        ("ations", "ate"),
        ("ation", "ate"),
        ("ingly", ""),
        ("edly", ""),
        ("ies", "y"),
        ("ied", "y"),
        ("ing", ""),
        ("ed", ""),
        ("es", ""),
        ("ly", ""),
        ("s", ""),
    ):
        if len(term) > len(suffix) + 3 and term.endswith(suffix):
            term = term[: -len(suffix)] + replacement
            break
    if term.endswith("e") and len(term) > 4:
        term = term[:-1]
    return term


@lru_cache(maxsize=4096)
def _escaped_char_bytes(char: str) -> int:
    return len(json.dumps(char, ensure_ascii=False).encode("utf-8")) - 2


def _escaped_prefix(text: str) -> tuple[int, ...]:
    prefix = [0]
    total = 0
    for char in text:
        total += _escaped_char_bytes(char)
        prefix.append(total)
    return tuple(prefix)


def _score(entries: Sequence[_Entry], query_terms: Sequence[str]) -> tuple[_Entry, ...]:
    sentence_count = sum(len(entry.sentences) for entry in entries)
    frequency = Counter(stem for entry in entries for sentence in entry.sentences for stem in sentence.stems)
    idf = {stem: math.log((sentence_count + 1) / (count + 1)) + 1.0 for stem, count in frequency.items()}
    sequence = tuple(_stem(term) for term in query_terms)
    stems = frozenset(sequence)
    bigrams = frozenset(pairwise(sequence))
    scored: list[_Entry] = []
    for entry in entries:
        values = []
        for index, sentence in enumerate(entry.sentences):
            value = _sentence_value(sentence, stems, bigrams, idf)
            if value:
                value *= 1.0 + _POSITION_WEIGHT * index / max(1, len(entry.sentences) - 1)
            if index == 0:
                value *= _FIRST_SENTENCE_WEIGHT
            values.append(value)
        scored.append(
            replace(
                entry,
                sentences=tuple(
                    replace(sentence, value=value) for sentence, value in zip(entry.sentences, values, strict=True)
                ),
            )
        )
    return tuple(scored)


def _sentence_value(
    sentence: _Sentence,
    query_stems: frozenset[str],
    query_bigrams: frozenset[tuple[str, str]],
    idf: dict[str, float],
) -> float:
    matched = query_stems & sentence.stems
    if not matched:
        return 0.0
    value = sum(idf.get(stem, 1.0) for stem in matched)
    value += _COVERAGE_WEIGHT * len(matched) / len(query_stems)
    if query_bigrams:
        bigrams = frozenset(pairwise(sentence.terms))
        value += _BIGRAM_WEIGHT * len(query_bigrams & bigrams)
    return value


def _best_window(entries: Sequence[_Entry], max_bytes: int) -> _Window | None:
    windows: list[_Window] = []
    for entry in entries:
        overhead = entry.overhead
        sentences = entry.sentences
        for first, sentence in enumerate(sentences):
            if not sentence.value:
                continue
            score = 0.0
            for last in range(first, min(len(sentences), first + _MAX_WINDOW_SENTENCES)):
                score += sentences[last].value
                start, end = sentence.start, sentences[last].end
                if overhead + entry.escaped_bytes(start, end) + _BYTES_MARGIN > max_bytes:
                    break
                windows.append(
                    _Window(
                        entry=entry,
                        first=first,
                        last=last,
                        score=score / (1.0 + _DOCUMENT_WEIGHT * entry.order),
                    )
                )
    windows.sort(key=lambda window: (window.score, window.last - window.first), reverse=True)
    for window in windows[:_MAX_VERIFIED_WINDOWS]:
        if _fits(window.entry, window.first, window.last, max_bytes):
            return window
    return None


def _fallback_window(entries: Sequence[_Entry], max_bytes: int) -> _Window | None:
    """Return a literal window when no sentence matches the query.

    Evidence often sits near the end of a recalled passage, so the fallback prefers the
    longest sentence-aligned suffix of the top-ranked entry. A tight budget may still leave
    no room for the trust envelope, in which case the caller returns an empty context.
    """

    for entry in entries:
        last = len(entry.sentences) - 1
        for first in range(last + 1):
            if _fits(entry, first, last, max_bytes):
                return _Window(entry=entry, first=first, last=last, score=0.0)
        if _fits(entry, last, last, max_bytes):
            return _Window(entry=entry, first=last, last=last, score=0.0)
    return None


def _expand(window: _Window, *, max_bytes: int) -> tuple[int, int]:
    first, last = window.first, window.last
    sentences = window.entry.sentences
    while True:
        options: list[tuple[float, int, int]] = []
        if first > 0:
            options.append((sentences[first - 1].value, first - 1, last))
        if last + 1 < len(sentences):
            options.append((sentences[last + 1].value, first, last + 1))
        for _value, candidate_first, candidate_last in sorted(options, reverse=True):
            if _fits(window.entry, candidate_first, candidate_last, max_bytes):
                first, last = candidate_first, candidate_last
                break
        else:
            return first, last


def _fits(entry: _Entry, first: int, last: int, max_bytes: int) -> bool:
    fragment = _window_fragment(entry, first, last)
    return len(render_evidence((fragment,)).encode("utf-8")) <= max_bytes


def _overhead(entry: _Entry) -> int:
    """Return every output byte except the escaped content for one fragment."""

    sentence = entry.sentences[0]
    sample = _fragment(entry, sentence.start, sentence.start + 1)
    return len(render_evidence((sample,)).encode("utf-8")) - entry.escaped_bytes(sample.start, sample.end)


def _window_fragment(entry: _Entry, first: int, last: int) -> PreparedMemoryFragment:
    return _fragment(entry, entry.sentences[first].start, entry.sentences[last].end)


def _fragment(entry: _Entry, start: int, end: int) -> PreparedMemoryFragment:
    return PreparedMemoryFragment(
        address=MemoryEntryAddress(
            memory=ArtifactAddress(scope_id=entry.scope_id, artifact=entry.memory_ref),
            entry_id=entry.entry_id,
            entry_version_id=entry.entry_version_id,
        ),
        start=start,
        end=end,
        text=entry.text[start:end],
    )


def _evidence_item(fragment: PreparedMemoryFragment) -> dict[str, object]:
    address = fragment.address
    return {
        "citation": {
            "scope_id": address.memory.scope_id,
            "memory_ref": address.memory.artifact.model_dump(mode="json"),
            "entry_id": address.entry_id,
            "entry_version_id": address.entry_version_id,
        },
        "content": fragment.text,
        "start": fragment.start,
        "end": fragment.end,
    }
