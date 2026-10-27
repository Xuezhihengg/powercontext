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

"""Capture offline CSV rows as independently addressable Sources."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, cast
from urllib.parse import quote

from pydantic import BaseModel, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

CSV_ROW_SOURCE_NAME = "csv-row"


class CSVDocumentInput(BaseModel):
    """One complete offline CSV document identified by its primary key column."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One parsed data record with its header and original field values."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """A captured CSV data row whose identity is stable across reordering."""

    materialization: SourceMaterialization = SourceMaterialization.CAPTURED
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="before")
    @classmethod
    def default_name(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
            data.setdefault("name", data.get("source_id"))
            return data
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> CSVRowSource:
        if self.materialization is not SourceMaterialization.CAPTURED:
            raise ValueError("CSV row sources must be captured")  # noqa: TRY003
        if self.name != self.source_id:
            raise ValueError("CSV row name must equal its source_id")  # noqa: TRY003
        if self.source_id != csv_row_source_id(self.document_id, self.primary_key_value):
            raise ValueError("CSV row source_id does not match its identity components")  # noqa: TRY003
        if len(self.columns) != len(self.values):
            raise ValueError("CSV row columns and values must have the same width")  # noqa: TRY003
        return self


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Build the stable, delimiter-safe identity of one CSV row."""

    _validate_document_id(document_id)
    _validate_primary_key_value(primary_key_value)
    source_id = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"CSV row source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse and fully validate one CSV document before returning any row."""

    _validate_document_id(value.document_id)
    if not isinstance(value.primary_key, str) or not value.primary_key.strip():
        raise ValueError("primary_key must be a non-empty string")  # noqa: TRY003

    try:
        text = value.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV content must be strict UTF-8") from error  # noqa: TRY003

    try:
        records = tuple(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as error:
        raise ValueError(f"CSV content is malformed: {error}") from error  # noqa: TRY003

    if not records:
        raise ValueError("CSV document must not be empty")  # noqa: TRY003

    header = tuple(records[0])
    _validate_header(header)
    try:
        key_index = header.index(value.primary_key)
    except ValueError as error:
        raise ValueError("primary_key must exactly match one CSV header field") from error  # noqa: TRY003

    rows: list[CSVRowInput] = []
    seen_keys: set[str] = set()
    for record in records[1:]:
        if not record:
            continue
        if len(record) != len(header):
            raise ValueError("CSV record width must equal the header width")  # noqa: TRY003
        primary_key_value = record[key_index]
        _validate_primary_key_value(primary_key_value)
        if primary_key_value in seen_keys:
            raise ValueError("CSV primary key values must be unique within a document")  # noqa: TRY003
        seen_keys.add(primary_key_value)
        rows.append(
            CSVRowInput(
                document_id=value.document_id,
                primary_key=value.primary_key,
                primary_key_value=primary_key_value,
                columns=header,
                values=tuple(record),
            )
        )
    return tuple(rows)


class CSVRowSourceAdapter:
    """Resolve and read row-level CSV Sources without changing the catalog."""

    input_class: type[CSVRowInput] = CSVRowInput
    name = CSV_ROW_SOURCE_NAME
    source_class: type[CSVRowSource] = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class CSVRowTextEvidenceProjection:
    """Expose one CSV row as canonical text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[CSVRowSource] = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


CSV_ROW_SOURCE_ADAPTER = CSVRowSourceAdapter()
CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = cast(
    SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput],
    AdapterSourceDefinition(
        CSV_ROW_SOURCE_ADAPTER,
        projections=(CSVRowTextEvidenceProjection(),),
    ),
)


def _validate_document_id(document_id: str) -> None:
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    if document_id != document_id.strip():
        raise ValueError("document_id must not contain leading or trailing whitespace")  # noqa: TRY003


def _validate_primary_key_value(primary_key_value: str) -> None:
    if not isinstance(primary_key_value, str) or not primary_key_value.strip():
        raise ValueError("primary_key_value must be a non-empty string")  # noqa: TRY003


def _validate_header(header: tuple[str, ...]) -> None:
    if not header:
        raise ValueError("CSV document must not have an empty header")  # noqa: TRY003
    seen: set[str] = set()
    for column in header:
        if not column or not column.strip():
            raise ValueError("CSV header fields must be non-empty")  # noqa: TRY003
        if column in seen:
            raise ValueError("CSV header fields must be unique")  # noqa: TRY003
        seen.add(column)
