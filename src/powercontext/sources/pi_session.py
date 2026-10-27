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

"""Capture the selected branch of a Pi v3 session as immutable event Sources."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from pydantic import BaseModel, JsonValue, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunSession, ConnectorRunStatus
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
_CHECKPOINT_VERSION = 1


class PiSessionInput(BaseModel):
    """One offline Pi JSONL session and the branch leaf to capture."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event from a selected Pi session branch."""

    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """A captured Pi event whose identity is stable across branches."""

    materialization: SourceMaterialization = SourceMaterialization.CAPTURED
    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]

    @model_validator(mode="before")
    @classmethod
    def default_name(cls, value: Any) -> Any:
        if isinstance(value, dict):
            data = dict(value)
            data.setdefault("name", data.get("source_id"))
            return data
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> PiEventSource:
        if self.materialization is not SourceMaterialization.CAPTURED:
            raise ValueError("Pi event sources must be captured")  # noqa: TRY003
        if self.name != self.source_id:
            raise ValueError("Pi event name must equal its source_id")  # noqa: TRY003
        if self.source_id != pi_event_source_id(self.session_id, self.event_id):
            raise ValueError("Pi event source_id does not match its identity components")  # noqa: TRY003
        return self


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Build the stable, delimiter-safe identity of one Pi event."""

    _validate_identity_part("session_id", session_id)
    _validate_identity_part("event_id", event_id)
    source_id = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(source_id) <= MAX_SOURCE_ID_LENGTH:
        return source_id
    canonical = json.dumps([session_id, event_id], ensure_ascii=False, separators=(",", ":"))
    return "pi:h" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse one Pi session and return the visible events on its selected branch."""

    graph = _parse_graph(value.content)
    return _events_for_leaf(graph, value.leaf_id)


class PiEventSourceAdapter:
    """Resolve and read Pi event Sources without changing the catalog."""

    input_class: type[PiEventInput] = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class: type[PiEventSource] = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose one Pi event as canonical text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[PiEventSource] = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_ADAPTER = PiEventSourceAdapter()
PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = cast(
    SourceDefinition[PiEventInput, PiEventSource, PiEventInput],
    AdapterSourceDefinition(
        PI_EVENT_SOURCE_ADAPTER,
        projections=(PiEventTextEvidenceProjection(),),
    ),
)


@dataclass(frozen=True, slots=True)
class _SessionNode:
    event_id: str
    parent_id: str | None
    record: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class _SessionGraph:
    session_id: str
    nodes: dict[str, _SessionNode]
    order: tuple[str, ...]


def _parse_graph(content: bytes) -> _SessionGraph:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be strict UTF-8") from error  # noqa: TRY003

    lines = tuple(line for line in re.split(r"\r\n|\r|\n", text) if line.strip())
    if not lines:
        raise ValueError("Pi session must not be empty")  # noqa: TRY003

    session_id = _parse_header(_load_json_object(lines[0]))
    nodes, order = _parse_nodes(lines[1:])
    return _SessionGraph(session_id=session_id, nodes=nodes, order=order)


def _parse_header(header: dict[str, JsonValue]) -> str:
    if header.get("type") != "session":
        raise ValueError("Pi session first record must have type=session")  # noqa: TRY003
    if header.get("version") != 3:
        raise ValueError("Pi session first record must have version=3")  # noqa: TRY003
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Pi session id must be a non-empty string")  # noqa: TRY003
    return session_id


def _parse_nodes(lines: tuple[str, ...]) -> tuple[dict[str, _SessionNode], tuple[str, ...]]:
    nodes: dict[str, _SessionNode] = {}
    order: list[str] = []
    for line in lines:
        record = _load_json_object(line)
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("Pi session entries must have a non-empty string id")  # noqa: TRY003
        if event_id in nodes:
            raise ValueError("Pi session entry ids must be unique")  # noqa: TRY003
        if "parentId" not in record:
            raise ValueError("Pi session entries must declare parentId")  # noqa: TRY003
        parent_id = record["parentId"]
        if parent_id is not None:
            if not isinstance(parent_id, str) or not parent_id.strip():
                raise ValueError("Pi session parentId must be null or a non-empty string")  # noqa: TRY003
            if parent_id not in nodes:
                raise ValueError("Pi session parentId must reference an earlier entry")  # noqa: TRY003
        nodes[event_id] = _SessionNode(event_id=event_id, parent_id=parent_id, record=record)
        order.append(event_id)
    if not order:
        raise ValueError("Pi session must contain at least one entry")  # noqa: TRY003
    return nodes, tuple(order)


def _events_for_leaf(graph: _SessionGraph, leaf_id: str | None) -> tuple[PiEventInput, ...]:
    selected = graph.order[-1] if leaf_id is None else leaf_id
    if selected not in graph.nodes:
        raise ValueError("Pi session leaf does not exist")  # noqa: TRY003

    chain: list[_SessionNode] = []
    visited: set[str] = set()
    current: str | None = selected
    while current is not None:
        if current in visited:
            raise ValueError("Pi session contains a parent cycle")  # noqa: TRY003
        visited.add(current)
        node = graph.nodes[current]
        chain.append(node)
        current = node.parent_id
    chain.reverse()

    events: list[PiEventInput] = []
    for node in chain:
        rendered = _render_record(node.record)
        if rendered is None:
            continue
        role, body = rendered
        event_type = node.record.get("type")
        events.append(
            PiEventInput(
                session_id=graph.session_id,
                event_id=node.event_id,
                parent_id=node.parent_id,
                event_type=event_type if isinstance(event_type, str) else "",
                role=role,
                content=f"{role}: {body}",
                record=node.record,
            )
        )
    return tuple(events)


def _render_record(record: dict[str, JsonValue]) -> tuple[str, str] | None:
    record_type = record.get("type")
    if not isinstance(record_type, str):
        return None
    if record_type == "message":
        message = record.get("message")
        return _render_message(message) if isinstance(message, dict) else None
    if record_type in {"compaction", "branch_summary"}:
        summary = record.get("summary")
        if summary is None:
            return None
        text = summary if isinstance(summary, str) else str(summary)
        if not text:
            return None
        return record_type, text
    if record_type == "custom_message":
        body = _render_content(record.get("content"))
        if not body:
            return None
        return "custom", body
    return None


def _render_message(message: dict[str, JsonValue]) -> tuple[str, str] | None:
    role = message.get("role")
    if not isinstance(role, str) or not role:
        return None
    if role == "toolResult":
        tool_name = _field_text(message.get("toolName"), "unknown")
        tool_call_id = _field_text(message.get("toolCallId"), "unknown")
        text = _render_content(message.get("content")) or ""
        return role, f"[tool_result {tool_name} {tool_call_id}] {text}"
    if role == "bashExecution":
        command = _field_text(message.get("command"), "")
        output = _field_text(message.get("output"), "")
        return role, f"$ {command}\n{output}"
    body = _render_content(message.get("content"))
    if not body:
        return None
    return role, body


def _render_content(content: JsonValue | None) -> str | None:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            parts.append(_field_text(block.get("text"), ""))
        elif block_type == "toolCall":
            parts.append(_render_tool_call(block))
    return "\n".join(parts)


def _render_tool_call(block: dict[str, JsonValue]) -> str:
    name = _field_text(block.get("name"), "")
    call_id = _field_text(block.get("id"), "")
    arguments = block.get("arguments", {})
    encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"[tool_call {name} {call_id}] {encoded}"


def _field_text(value: JsonValue | None, default: str) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def _load_json_object(line: str) -> dict[str, JsonValue]:
    try:
        value = json.loads(line, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as error:
        raise ValueError("Pi session contains invalid JSON") from error  # noqa: TRY003
    if not isinstance(value, dict):
        raise ValueError("Pi session records must be JSON objects")  # noqa: TRY003, TRY004
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Pi session contains non-standard JSON constant {value!r}")  # noqa: TRY003


def _validate_identity_part(field: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")  # noqa: TRY003


class PiSessionConnector:
    """Incrementally capture visible events from one Pi session path."""

    name = PI_SESSION_CONNECTOR_NAME
    version = "1"
    source_definitions = frozenset({PI_EVENT_SOURCE_DEFINITION.name})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        graph = _parse_graph(self._path.read_bytes())
        events = _events_for_leaf(graph, self._leaf_id)
        imported = _load_checkpoint(session.checkpoint, graph.session_id)

        for event_id, digest in imported.items():
            node = graph.nodes.get(event_id)
            if node is not None and _record_digest(node.record) != digest:
                raise ValueError(f"Pi event {event_id!r} was rewritten after it was captured")  # noqa: TRY003

        pending: list[tuple[PiEventInput, str, str]] = []
        for event in events:
            if event.event_id in imported:
                continue
            pending.append((
                event,
                pi_event_source_id(event.session_id, event.event_id),
                _record_digest(graph.nodes[event.event_id].record),
            ))

        updated = dict(imported)
        for event, source_id, digest in pending:
            await session.submit(source_id, PI_EVENT_SOURCE_DEFINITION.name, event)
            updated[event.event_id] = digest

        checkpoint = {
            "version": _CHECKPOINT_VERSION,
            "session_id": graph.session_id,
            "events": updated,
        }
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=checkpoint)


def _load_checkpoint(value: JsonValue | None, session_id: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Pi connector checkpoint must be a JSON object")  # noqa: TRY003, TRY004
    if value.get("version") != _CHECKPOINT_VERSION:
        raise ValueError("Pi connector checkpoint version is unsupported")  # noqa: TRY003
    stored_session = value.get("session_id")
    events = value.get("events")
    if not isinstance(stored_session, str) or not isinstance(events, dict):
        raise ValueError("Pi connector checkpoint is malformed")  # noqa: TRY003, TRY004
    if stored_session != session_id:
        return {}
    imported: dict[str, str] = {}
    for event_id, digest in events.items():
        if not isinstance(event_id, str) or not isinstance(digest, str):
            raise ValueError("Pi connector checkpoint is malformed")  # noqa: TRY003, TRY004
        imported[event_id] = digest
    return imported


def _record_digest(record: dict[str, JsonValue]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"
