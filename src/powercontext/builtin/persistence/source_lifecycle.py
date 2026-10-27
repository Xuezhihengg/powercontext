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

"""Persist Source dependency nodes and lifecycle events."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef
from powercontext.artifacts.models import MemoryCitation
from powercontext.builtin.persistence.codec import stored_bytes
from powercontext.builtin.persistence.tables import (
    SOURCE_LIFECYCLE_EVENTS_TABLE,
    SOURCE_LIFECYCLE_NODES_TABLE,
)
from powercontext.sources import SourceRef

NodeKind = Literal["source", "memory", "topic"]
LifecyclePolicy = Literal["all", "any"]
LifecycleReference = SourceRef | MemoryCitation | ArtifactRef

_REFERENCE_TYPES: dict[str, type[BaseModel]] = {
    "source": SourceRef,
    "memory": MemoryCitation,
    "topic": ArtifactRef,
}


@dataclass(frozen=True)
class LifecycleNode:
    """One registered node and its last computed availability."""

    node_id: str
    kind: NodeKind
    reference: LifecycleReference
    parents: tuple[str, ...]
    policy: LifecyclePolicy | None
    revision: int | None
    available: bool


@dataclass(frozen=True)
class LifecycleEventRecord:
    """One persisted source lifecycle event."""

    revision: int
    sequence: int
    available: bool
    reason: str
    applied: bool


class SourceLifecycleRepository:
    """Read and write the per-Scope dependency graph."""

    async def nodes(self, connection: AsyncConnection, scope_id: str, /) -> dict[str, LifecycleNode]:
        statement = select(SOURCE_LIFECYCLE_NODES_TABLE).where(SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id)
        rows = (await connection.execute(statement)).mappings()
        return {str(row["node_id"]): _decode_node(row) for row in rows}

    async def node(self, connection: AsyncConnection, scope_id: str, node_id: str, /) -> LifecycleNode | None:
        statement = select(SOURCE_LIFECYCLE_NODES_TABLE).where(
            SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id,
            SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == node_id,
        )
        row = (await connection.execute(statement)).mappings().one_or_none()
        return None if row is None else _decode_node(row)

    async def insert_node(self, connection: AsyncConnection, scope_id: str, node: LifecycleNode, /) -> None:
        await connection.execute(
            SOURCE_LIFECYCLE_NODES_TABLE.insert().values(
                scope_id=scope_id,
                node_id=node.node_id,
                kind=node.kind,
                reference=_encode_reference(node.reference),
                parents=_encode_parents(node.parents),
                policy=node.policy,
                revision=node.revision,
                available=node.available,
            )
        )

    async def set_availability(
        self,
        connection: AsyncConnection,
        scope_id: str,
        availability: Mapping[str, bool],
        /,
    ) -> None:
        for node_id, available in availability.items():
            await connection.execute(
                update(SOURCE_LIFECYCLE_NODES_TABLE)
                .where(
                    SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id,
                    SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == node_id,
                )
                .values(available=available)
            )

    async def event(
        self,
        connection: AsyncConnection,
        scope_id: str,
        node_id: str,
        sequence: int,
        /,
    ) -> LifecycleEventRecord | None:
        statement = select(SOURCE_LIFECYCLE_EVENTS_TABLE).where(
            SOURCE_LIFECYCLE_EVENTS_TABLE.c.scope_id == scope_id,
            SOURCE_LIFECYCLE_EVENTS_TABLE.c.node_id == node_id,
            SOURCE_LIFECYCLE_EVENTS_TABLE.c.sequence == sequence,
        )
        row = (await connection.execute(statement)).mappings().one_or_none()
        return None if row is None else _decode_event(row)

    async def max_sequence(self, connection: AsyncConnection, scope_id: str, node_id: str, /) -> int | None:
        statement = select(SOURCE_LIFECYCLE_EVENTS_TABLE.c.sequence).where(
            SOURCE_LIFECYCLE_EVENTS_TABLE.c.scope_id == scope_id,
            SOURCE_LIFECYCLE_EVENTS_TABLE.c.node_id == node_id,
        )
        values = (await connection.execute(statement)).scalars().all()
        return None if not values else max(int(value) for value in values)

    async def insert_event(
        self,
        connection: AsyncConnection,
        scope_id: str,
        node_id: str,
        *,
        revision: int,
        sequence: int,
        available: bool,
        reason: str,
        applied: bool,
    ) -> None:
        await connection.execute(
            SOURCE_LIFECYCLE_EVENTS_TABLE.insert().values(
                scope_id=scope_id,
                node_id=node_id,
                sequence=sequence,
                revision=revision,
                available=available,
                reason=reason,
                applied=applied,
            )
        )

    async def mark_applied(
        self,
        connection: AsyncConnection,
        scope_id: str,
        node_id: str,
        sequence: int,
        /,
    ) -> None:
        await connection.execute(
            update(SOURCE_LIFECYCLE_EVENTS_TABLE)
            .where(
                SOURCE_LIFECYCLE_EVENTS_TABLE.c.scope_id == scope_id,
                SOURCE_LIFECYCLE_EVENTS_TABLE.c.node_id == node_id,
                SOURCE_LIFECYCLE_EVENTS_TABLE.c.sequence == sequence,
            )
            .values(applied=True)
        )

    async def hidden_topic_refs(
        self,
        connection: AsyncConnection,
        scope_id: str,
        /,
    ) -> frozenset[tuple[str, int]]:
        statement = select(SOURCE_LIFECYCLE_NODES_TABLE.c.reference).where(
            SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id,
            SOURCE_LIFECYCLE_NODES_TABLE.c.kind == "topic",
            SOURCE_LIFECYCLE_NODES_TABLE.c.available.is_(False),
        )
        hidden: set[tuple[str, int]] = set()
        for payload in (await connection.execute(statement)).scalars():
            reference = ArtifactRef.model_validate_json(stored_bytes(payload, column="reference"), strict=True)
            hidden.add((reference.artifact_id, reference.revision))
        return frozenset(hidden)


def _decode_node(row: Mapping[str, object]) -> LifecycleNode:
    kind = str(row["kind"])
    reference_type = _REFERENCE_TYPES.get(kind)
    if reference_type is None:
        raise ValueError(f"unknown lifecycle node kind: {kind}")  # noqa: TRY003
    reference = reference_type.model_validate_json(
        stored_bytes(row["reference"], column="reference"),
        strict=True,
    )
    return LifecycleNode(
        node_id=str(row["node_id"]),
        kind=kind,
        reference=reference,
        parents=_decode_parents(stored_bytes(row["parents"], column="parents")),
        policy=row["policy"],
        revision=None if row["revision"] is None else int(row["revision"]),
        available=bool(row["available"]),
    )


def _decode_event(row: Mapping[str, object]) -> LifecycleEventRecord:
    return LifecycleEventRecord(
        revision=int(row["revision"]),
        sequence=int(row["sequence"]),
        available=bool(row["available"]),
        reason=str(row["reason"]),
        applied=bool(row["applied"]),
    )


def _encode_reference(reference: LifecycleReference) -> bytes:
    return reference.model_dump_json(by_alias=True).encode("utf-8")


def _encode_parents(parents: Sequence[str]) -> bytes:
    return json.dumps(list(parents), separators=(",", ":")).encode("utf-8")


def _decode_parents(payload: bytes) -> tuple[str, ...]:
    decoded = json.loads(payload)
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise ValueError("invalid lifecycle parent list")  # noqa: TRY003
    return tuple(decoded)
