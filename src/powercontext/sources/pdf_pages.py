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

"""Capture every physical page of a PDF report and retrieve evidence pages."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
from collections import Counter
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from pydantic import BaseModel, model_validator
from pypdf import PdfReader

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import MemoryCitation

PDF_PAGE_SOURCE_NAME = "pdf-page"

_WORD = re.compile(r"[a-z0-9]+")
_DOMAIN_TERM = re.compile(r"(?:d\s*&\s*a|ebitda|capex)")

_QUERY_STOPWORDS = frozenset({
    "a",
    "about",
    "according",
    "all",
    "also",
    "an",
    "and",
    "answer",
    "any",
    "are",
    "as",
    "assume",
    "at",
    "available",
    "based",
    "be",
    "been",
    "being",
    "between",
    "both",
    "but",
    "by",
    "calculate",
    "can",
    "company",
    "compute",
    "could",
    "defined",
    "detail",
    "details",
    "did",
    "do",
    "does",
    "during",
    "each",
    "either",
    "end",
    "ended",
    "fiscal",
    "for",
    "from",
    "fy",
    "give",
    "given",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "his",
    "how",
    "i",
    "if",
    "in",
    "information",
    "into",
    "is",
    "it",
    "its",
    "may",
    "me",
    "million",
    "millions",
    "must",
    "my",
    "no",
    "not",
    "of",
    "on",
    "only",
    "or",
    "other",
    "our",
    "outlined",
    "over",
    "per",
    "period",
    "perspective",
    "please",
    "provided",
    "question",
    "rely",
    "report",
    "reported",
    "reporting",
    "respond",
    "response",
    "same",
    "say",
    "shall",
    "she",
    "should",
    "show",
    "shown",
    "so",
    "some",
    "state",
    "stated",
    "such",
    "supplied",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "under",
    "us",
    "use",
    "used",
    "using",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "why",
    "will",
    "with",
    "within",
    "without",
    "would",
    "year",
    "years",
    "you",
    "your",
})


class PDFDocumentInput(BaseModel):
    """One complete PDF report, read page by page from the original bytes."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical page of a PDF report with its revision identity."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """A captured physical page whose identity is bound to the PDF revision."""

    materialization: SourceMaterialization = SourceMaterialization.CAPTURED
    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str

    @model_validator(mode="before")
    @classmethod
    def default_name(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
            data.setdefault("name", data.get("source_id"))
            return data
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> PDFPageSource:
        if self.materialization is not SourceMaterialization.CAPTURED:
            raise ValueError("PDF page sources must be captured")  # noqa: TRY003
        if self.name != self.source_id:
            raise ValueError("PDF page name must equal its source_id")  # noqa: TRY003
        if self.source_id != pdf_page_source_id(self.document_id, self.document_sha256, self.page_number):
            raise ValueError("PDF page source_id does not match its identity components")  # noqa: TRY003
        return self


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Build the stable identity of one page in one exact PDF revision."""

    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    if not isinstance(document_sha256, str) or not document_sha256:
        raise ValueError("document_sha256 must be a non-empty string")  # noqa: TRY003
    if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number < 1:
        raise ValueError("page_number must be a positive integer")  # noqa: TRY003
    source_id = f"pdf:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(source_id) <= MAX_SOURCE_ID_LENGTH:
        return source_id
    canonical = json.dumps([document_id, document_sha256, page_number], separators=(",", ":"))
    return "pdf:h" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of one PDF before returning any page."""

    if not isinstance(value.document_id, str) or not value.document_id.strip():
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    if not value.content:
        raise ValueError("PDF content must not be empty")  # noqa: TRY003

    try:
        return _parse_pdf_pages(value.document_id, value.content)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("PDF document could not be parsed completely") from error  # noqa: TRY003


def _parse_pdf_pages(document_id: str, content: bytes) -> tuple[PDFPageInput, ...]:
    digest = hashlib.sha256(content).hexdigest()
    reader = PdfReader(io.BytesIO(content), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("PDF requires a password that was not supplied")  # noqa: TRY003
    pages = tuple(
        PDFPageInput(
            document_id=document_id,
            document_sha256=digest,
            page_number=index,
            text=_page_text(page),
        )
        for index, page in enumerate(reader.pages, start=1)
    )
    if not pages:
        raise ValueError("PDF document must contain at least one page")  # noqa: TRY003
    return pages


def _page_text(page: Any) -> str:
    text = page.extract_text()
    return text if isinstance(text, str) else ""


class PDFPageAdapter:
    """Resolve and read captured PDF pages without loading report-level state."""

    input_class: type[PDFPageInput] = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class: type[PDFPageSource] = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose one physical page as text evidence with revision metadata."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[PDFPageSource] = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_ADAPTER = PDFPageAdapter()
PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = cast(
    SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput],
    AdapterSourceDefinition(
        PDF_PAGE_ADAPTER,
        projections=(PDFPageTextEvidenceProjection(),),
    ),
)


_PROBE_LIMIT = 200
_DOCUMENT_LIMIT = 2000
_MAX_RESOLUTIONS = 400
_EXPANSION_WEIGHT = 0.5
_SECTION_PRIOR = 0.3

_YEAR = re.compile(r"(?:19|20)\d\d")
_COMPANY_PART = re.compile(r"[a-z0-9]+")
_DOCUMENT_TRAILER = frozenset({"10k", "10q", "8k", "earnings", "dated"})

_EXPANSIONS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = tuple(
    (re.compile(pattern), tuple(terms))
    for pattern, terms in (
        (r"quick ratio|current ratio", ("current", "assets", "liabilities", "cash", "receivables", "inventories")),
        (r"liquidity", ("current", "assets", "liabilities", "cash", "credit", "facilities")),
        (
            r"capital.?intensive",
            (
                "capital",
                "expenditures",
                "property",
                "plant",
                "equipment",
                "depreciation",
                "revenues",
                "net",
                "sales",
                "total",
                "assets",
            ),
        ),
        (r"gross margin", ("gross", "margin", "net", "sales", "cost", "profit")),
        (r"operating margin", ("operating", "income", "net", "sales", "margin")),
        (r"ebitda", ("operating", "income", "depreciation", "amortization")),
        (r"capex|capital expenditure", ("capital", "expenditures", "property", "plant", "equipment")),
        (r"free cash flow", ("cash", "flows", "operating", "activities", "capital", "expenditures")),
        (r"customer concentration", ("customer", "accounted", "percent", "net", "revenue", "concentration")),
        (r"largest liability", ("total", "liabilities", "accounts", "payable", "long", "term", "debt")),
        (r"geograph|region", ("geographic", "regions", "countries", "north", "america", "europe", "asia", "africa")),
        (
            r"legal battle|legal proceeding|litigation|lawsuit",
            ("legal", "proceedings", "litigation", "claims", "contingencies", "dispute"),
        ),
        (r"restructuring", ("restructuring", "severance", "charges")),
        (r"segment", ("segment", "segments", "sales", "operating", "income")),
        (r"effective tax rate", ("effective", "tax", "rate", "income", "taxes", "provision")),
        (r"debt securities|registered.*exchange", ("securities", "registered", "exchange", "debt", "common", "stock")),
        (r"customer|card member|client", ("customer", "customers", "members", "clients")),
        (r"product|service", ("products", "services", "product", "service")),
        (r"cyclical", ("cyclical", "cycle", "demand", "economic", "conditions")),
        (r"production rate", ("production", "rate", "rates", "aircraft", "deliveries")),
        (
            r"revenue change|sales change|drove revenue|drove operating margin|drove.*change",
            ("results", "operations", "net", "sales", "increase", "decrease", "change", "operating", "income"),
        ),
        (r"primary customers", ("customers", "risk", "demand", "commercial", "government")),
        (r"cash flow", ("operating", "investing", "financing", "activities", "cash", "flows")),
        (r"categor", ("segment", "revenues", "products", "services", "net", "sales")),
        (r"inventor", ("inventories", "inventory", "cost", "sales", "net", "income")),
        (
            r"ppne|property,? plant|\bppe\b",
            ("property", "plant", "equipment", "capital", "expenditures", "depreciation"),
        ),
        (r"\bdebt\b|borrowing", ("debt", "borrowings", "long", "term", "obligations", "notes", "repayment")),
        (r"margin|profitab", ("gross", "operating", "net", "margin", "income", "sales", "cost")),
    )
)

_SECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "income": re.compile(r"consolidated statements? of (?:income|operations|earnings)|statements? of operations"),
    "balance": re.compile(r"consolidated balance sheets?"),
    "cashflow": re.compile(r"consolidated statements? of cash flows"),
    "segment": re.compile(
        r"summary of business segment data|geographic operations|by business segment|segment information"
    ),
    "mdna": re.compile(
        r"management.s discussion and analysis|analysis of consolidated earnings"
        r"|results of operations|liquidity and capital resources"
    ),
    "notes": re.compile(r"notes to (?:the )?consolidated financial statements"),
    "legal": re.compile(r"legal proceedings"),
    "risk": re.compile(r"risk factors"),
    "business": re.compile(r"item 1\. business|business environment|forward-looking statements"),
    "selected": re.compile(r"summary of financial performance|selected financial data"),
}

_SECTION_CONCEPTS: dict[str, re.Pattern[str]] = {
    "income": re.compile(
        r"income statement|statement of income|revenue|sales|gross margin|operating margin|operating income"
        r"|net income|earnings|ebitda|profit|cost of sales|margin|capital.?intensive"
    ),
    "balance": re.compile(
        r"balance sheet|liabilit|quick ratio|current ratio|liquidity|working capital|total assets|equity"
        r"|receivable|inventor|property plant|ppne|ppe"
    ),
    "cashflow": re.compile(
        r"cash flow|cash flows|operating activities|investing activities|financing activities|capex"
        r"|capital expenditure|depreciation|amortization|capital.?intensive"
    ),
    "segment": re.compile(r"segment|geograph|region|categor"),
    "mdna": re.compile(r"drove|change|improv|declin|growth|result|margin|revenue|sales"),
    "legal": re.compile(r"legal|litigation|lawsuit|proceeding|contingenc|claim|dispute|battle"),
    "risk": re.compile(r"risk|uncertaint|cyclical"),
    "business": re.compile(r"business|product|customer|operate|market|employee|supplier|concentration|cyclical"),
    "notes": re.compile(r"note|debt|borrow|pension|lease|goodwill|contingenc|commitment"),
}


def _query_terms(question: str) -> tuple[str, ...]:
    lowered = question.casefold()
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        if term and term not in seen:
            seen.add(term)
            terms.append(term)

    for match in _DOMAIN_TERM.finditer(lowered):
        add(re.sub(r"\s+", "", match.group(0)))
    for match in _WORD.finditer(_DOMAIN_TERM.sub(" ", lowered)):
        term = match.group(0)
        if term in _QUERY_STOPWORDS or len(term) < 2:
            continue
        add(term)
        if term.startswith("fy") and term[2:].isdigit():
            add(term[2:])
    return tuple(terms)


def _expanded_terms(question: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    folded = " ".join(question.casefold().split())
    base = _query_terms(question)
    seen = set(base)
    extra: list[str] = []
    for pattern, terms in _EXPANSIONS:
        if pattern.search(folded):
            for term in terms:
                if term not in seen:
                    seen.add(term)
                    extra.append(term)
    return base, tuple(extra)


def _question_sections(question: str) -> frozenset[str]:
    folded = question.casefold()
    return frozenset(name for name, pattern in _SECTION_CONCEPTS.items() if pattern.search(folded))


def _page_sections(text: str) -> frozenset[str]:
    head = " ".join(text.casefold().split())[:600]
    return frozenset(name for name, pattern in _SECTION_PATTERNS.items() if pattern.search(head))


def _bm25_scores(pages: dict[str, str], question: str) -> dict[str, float]:
    tokens = {entry_id: _WORD.findall(text.casefold()) for entry_id, text in pages.items()}
    if not tokens:
        return {}
    count = len(tokens)
    average = sum(len(value) for value in tokens.values()) / count
    frequencies = {entry_id: Counter(value) for entry_id, value in tokens.items()}
    base, extra = _expanded_terms(question)
    scores = dict.fromkeys(tokens, 0.0)
    for term, weight in [(term, 1.0) for term in base] + [(term, _EXPANSION_WEIGHT) for term in extra]:
        documents = sum(1 for frequency in frequencies.values() if frequency.get(term))
        if not documents:
            continue
        inverse = math.log(1.0 + (count - documents + 0.5) / (documents + 0.5))
        for entry_id, frequency in frequencies.items():
            term_frequency = frequency.get(term, 0)
            if not term_frequency:
                continue
            length = len(tokens[entry_id])
            scores[entry_id] += (
                weight
                * inverse
                * (term_frequency * (1.2 + 1.0))
                / (term_frequency + 1.2 * (1.0 - 0.75 + 0.75 * length / average))
            )
    return scores


def _company_key(document_id: str) -> str:
    parts = _COMPANY_PART.findall(document_id.casefold())
    kept: list[str] = []
    for part in parts:
        if _YEAR.fullmatch(part) or part in _DOCUMENT_TRAILER:
            break
        kept.append(part)
    return "".join(kept)


_COMPANY_ALIASES: dict[str, str] = {
    "amex": "americanexpress",
    "jnj": "johnsonjohnson",
    "pfe": "pfizer",
    "cvs": "cvshealth",
    "vz": "verizon",
    "mmm": "3m",
    "ko": "cocacola",
    "pep": "pepsico",
    "ba": "boeing",
    "gm": "generalmotors",
    "ge": "generalelectric",
    "jpm": "jpmorgan",
    "bofa": "bankofamerica",
}


def _company_aliases(document_id: str) -> frozenset[str]:
    parts = _COMPANY_PART.findall(document_id.casefold())
    words: list[str] = []
    for part in parts:
        if _YEAR.fullmatch(part) or part in _DOCUMENT_TRAILER:
            break
        words.append(part)
    key = "".join(words)
    aliases = {key}
    if len(words) >= 2:
        initials = [word[:1] for word in words]
        aliases.add("".join(initials))
        aliases.add("n".join(initials))
    return frozenset(alias for alias in aliases if len(alias) >= 2)


def _matches_document(compact: str, tokens: set[str], document_id: str) -> bool:
    company = _company_key(document_id)
    if len(company) < 2:
        return False
    if company in compact or company in tokens:
        return True
    if any(alias in tokens for alias in _company_aliases(document_id)):
        return True
    return any(len(token) >= 4 and company.startswith(token) for token in tokens)


def _select_document(question: str, counts: dict[str, int]) -> str | None:
    compact = re.sub(r"[^a-z0-9]+", "", question.casefold())
    tokens = set(_WORD.findall(question.casefold()))
    tokens.update(_COMPANY_ALIASES[token] for token in tuple(tokens) if token in _COMPANY_ALIASES)
    if "j&j" in question.casefold():
        tokens.add("johnsonjohnson")
    strongest = max(counts.values(), default=0) or 1
    best: str | None = None
    best_score = -1.0
    for document_id, count in counts.items():
        if not _matches_document(compact, tokens, document_id):
            continue
        score = 2.0 + count / strongest
        if any(year in compact for year in _YEAR.findall(document_id)):
            score += 0.5
        if score > best_score:
            best, best_score = document_id, score
    if best is None and counts:
        best = max(counts, key=lambda document_id: counts[document_id])
    return best


def _document_id(text: str) -> str:
    return text.split("\n", 1)[0].strip()


def _collect_pages(hits: Any, document: str | None) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
    pages: dict[str, str] = {}
    versions: dict[str, str] = {}
    references: dict[str, Any] = {}
    for hit in hits:
        page_document, _, text = hit.text.partition("\n")
        if document is not None and page_document.strip() != document:
            continue
        pages[hit.entry_id] = text
        versions[hit.entry_id] = hit.entry_version_id
        references[hit.entry_id] = hit.memory_ref
    return pages, versions, references


def _rank_pages(pages: dict[str, str], question: str) -> dict[str, float]:
    scores = _bm25_scores(pages, question)
    sections = _question_sections(question)
    if not sections or not scores:
        return scores
    maximum = max(scores.values())
    if maximum <= 0:
        return scores
    for entry_id, value in scores.items():
        scores[entry_id] = value / maximum + (_SECTION_PRIOR if _page_sections(pages[entry_id]) & sections else 0.0)
    return scores


async def _get_entry(memory: Any, reference: Any, entry_id: str, version: str) -> Any:
    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime import GetMemoryEntryRequest

    try:
        return (
            await memory.get(
                GetMemoryEntryRequest(
                    citation=MemoryCitation(
                        memory_ref=reference,
                        entry_id=entry_id,
                        entry_version_id=version,
                    )
                )
            )
        ).entry
    except Exception:
        return None


async def _resolve_citations(
    memory: Any,
    scores: dict[str, float],
    references: dict[str, Any],
    versions: dict[str, str],
    limit: int,
) -> tuple[MemoryCitation, ...]:
    from powercontext.builtin.artifacts.memory.models import MemoryCitation

    results: list[MemoryCitation] = []
    seen: set[str] = set()
    resolved = 0
    for entry_id in sorted(scores, key=lambda key: (-scores[key], key)):
        if len(results) >= limit or resolved >= _MAX_RESOLUTIONS:
            break
        resolved += 1
        entry = await _get_entry(memory, references[entry_id], entry_id, versions[entry_id])
        if entry is None:
            continue
        for source in entry.sources:
            if source.source_type != PDF_PAGE_SOURCE_NAME or source.source_id in seen:
                continue
            seen.add(source.source_id)
            results.append(
                MemoryCitation(
                    memory_ref=references[entry_id],
                    entry_id=entry_id,
                    entry_version_id=versions[entry_id],
                )
            )
            break
    return tuple(results)


async def search_pdf_pages(memory: Any, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]:
    """Retrieve distinct evidence pages from one scoped Memory."""

    from powercontext.builtin.runtime import SearchMemoryRequest

    if limit < 1 or not isinstance(question, str) or not question.strip():
        return ()

    probe = await memory.search(SearchMemoryRequest(query=question, mode="fts", limit=_PROBE_LIMIT))
    counts: dict[str, int] = {}
    for hit in probe.hits:
        document_id = _document_id(hit.text)
        if document_id:
            counts[document_id] = counts.get(document_id, 0) + 1
    document = _select_document(question, counts)

    if document is not None:
        page = await memory.search(SearchMemoryRequest(query=document, mode="fts", limit=_DOCUMENT_LIMIT))
        pages, versions, references = _collect_pages(page.hits, document)
    else:
        pages, versions, references = {}, {}, {}
    if not pages:
        pages, versions, references = _collect_pages(probe.hits, None)

    scores = _rank_pages(pages, question)
    return await _resolve_citations(memory, scores, references, versions, limit)
