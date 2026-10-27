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

"""Propagate Source lifecycle state through a per-Scope dependency DAG."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, field_validator

from powercontext.artifacts import ArtifactRef
from powercontext.artifacts.models import MemoryCitation
from powercontext.builtin.artifacts.memory.errors import (
    CapabilityNotSupportedError,
    InvalidMemoryCitationError,
    MemoryEntryNotFoundError,
)
from powercontext.builtin.artifacts.topic_memory import TopicMemory
from powercontext.builtin.persistence.errors import RepositoryNotFoundError
from powercontext.builtin.persistence.source_lifecycle import (
    LifecycleNode,
    LifecyclePolicy,
    LifecycleReference,
    SourceLifecycleRepository,
)
from powercontext.builtin.sources.journal import validate_scope_id
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime
    from powercontext.builtin.runtime.relational import RelationalContexts

_PURPOSES = frozenset({"generation", "audit"})


class SourceLifecycleError(ValueError):
    """Reject an invalid lifecycle identity, graph, event, or read purpose."""

    _MESSAGES: ClassVar[dict[str, str]] = {
        "conflict": "node identity is already bound to a different registration",
        "derived-parents": "a derived node requires at least one parent",
        "event-revision": "event revision does not match the registered Source",
        "event-sequence": "event sequence is already bound to different content",
        "event-order": "event sequence does not increase monotonically",
        "event-source": "event targets an unknown Source",
        "memory-artifact": "Memory artifact is not readable",
        "memory-citation": "Memory citation is not readable",
        "memory-entry": "Memory entry is not readable",
        "memory-node": "Memory node has the wrong reference type",
        "memory-reference": "memory reference must be a MemoryCitation",
        "node": "unknown lifecycle node",
        "node-id": "node id must be non-empty and contain non-whitespace characters",
        "node-unavailable": "lifecycle node is unavailable for generation",
        "parent-duplicate": "parents must not repeat",
        "parent-missing": "parent is not registered",
        "parent-self": "a node cannot depend on itself",
        "policy": "support policy must be all or any",
        "purpose": "unknown lifecycle purpose",
        "revision": "revision must be a positive integer",
        "source-reference": "Source reference is not readable",
        "topic-family": "topic reference must be a Topic Memory ArtifactRef",
        "topic-reference": "Topic reference is not readable",
    }

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        message = self._MESSAGES.get(code, f"invalid source lifecycle request: {code}")
        super().__init__(message if detail is None else f"{message}: {detail}")


class SourceLifecycleEvent(BaseModel):
    """One explicit availability event for a registered Source node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: StrictInt
    sequence: StrictInt
    available: StrictBool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must be non-empty and contain non-whitespace characters")  # noqa: TRY003
        return value

    @field_validator("revision", "sequence")
    @classmethod
    def validate_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be a positive integer")  # noqa: TRY003
        return value


class ScopedSourceLifecycleApplication:
    """Register one Scope's dependency graph and apply Source events to it."""

    def __init__(
        self,
        runtime: BuiltinRuntime,
        contexts: RelationalContexts,
        scope_id: str,
    ) -> None:
        self._runtime = runtime
        self._contexts = contexts
        self._store = SourceLifecycleRepository()
        self.scope_id = validate_scope_id(scope_id)

    async def register_source(
        self,
        node_id: str,
        reference: SourceRef,
        /,
        *,
        revision: int = 1,
    ) -> None:
        """Bind one node id to an exact readable Source and lifecycle revision."""

        _require_node_identity(node_id)
        _require_positive_int("revision", revision)
        if not isinstance(reference, SourceRef):
            raise SourceLifecycleError("source-reference")
        async with self._runtime._scoped_operation(self.scope_id), self._runtime._locked(self.scope_id):
            nodes = await self._nodes()
            existing = nodes.get(node_id)
            if existing is not None:
                if existing.kind == "source" and existing.reference == reference and existing.revision == revision:
                    return
                raise SourceLifecycleError("conflict")
            async with self._contexts.database.transaction() as connection:
                try:
                    await self._contexts.repositories.sources.get(connection, self.scope_id, reference)
                except RepositoryNotFoundError as error:
                    raise SourceLifecycleError("source-reference") from error
                await self._store.insert_node(
                    connection,
                    self.scope_id,
                    LifecycleNode(
                        node_id=node_id,
                        kind="source",
                        reference=reference,
                        parents=(),
                        policy=None,
                        revision=revision,
                        available=True,
                    ),
                )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        parents: Sequence[str],
        policy: LifecyclePolicy,
    ) -> None:
        """Bind one node id to an exact Memory citation and its support policy."""

        _require_node_identity(node_id)
        _require_memory_reference(citation)
        normalized_parents = _normalize_parents(node_id, parents)
        normalized_policy = _require_policy(policy)
        async with self._runtime._scoped_operation(self.scope_id), self._runtime._locked(self.scope_id):
            nodes = await self._nodes()
            existing = nodes.get(node_id)
            if existing is not None:
                if (
                    existing.kind == "memory"
                    and existing.reference == citation
                    and existing.parents == normalized_parents
                    and existing.policy == normalized_policy
                ):
                    await self._reconcile_memory(nodes)
                    return
                raise SourceLifecycleError("conflict")
            _require_registered_parents(nodes, normalized_parents)
            await self._validate_memory_citation(citation)
            available = _child_available(nodes, normalized_parents, normalized_policy)
            async with self._contexts.database.transaction() as connection:
                await self._store.insert_node(
                    connection,
                    self.scope_id,
                    LifecycleNode(
                        node_id=node_id,
                        kind="memory",
                        reference=citation,
                        parents=normalized_parents,
                        policy=normalized_policy,
                        revision=None,
                        available=available,
                    ),
                )
            await self._reconcile_memory(await self._nodes())

    async def register_topic(
        self,
        node_id: str,
        reference: ArtifactRef,
        parents: Sequence[str],
        policy: LifecyclePolicy,
    ) -> None:
        """Bind one node id to an exact Topic Memory revision and support policy."""

        _require_node_identity(node_id)
        _require_topic_reference(reference)
        normalized_parents = _normalize_parents(node_id, parents)
        normalized_policy = _require_policy(policy)
        async with self._runtime._scoped_operation(self.scope_id), self._runtime._locked(self.scope_id):
            nodes = await self._nodes()
            existing = nodes.get(node_id)
            if existing is not None:
                if (
                    existing.kind == "topic"
                    and existing.reference == reference
                    and existing.parents == normalized_parents
                    and existing.policy == normalized_policy
                ):
                    return
                raise SourceLifecycleError("conflict")
            _require_registered_parents(nodes, normalized_parents)
            async with self._contexts.database.transaction() as connection:
                try:
                    artifact = await self._contexts.repositories.artifacts.get(connection, self.scope_id, reference)
                except RepositoryNotFoundError as error:
                    raise SourceLifecycleError("topic-reference") from error
                if not isinstance(artifact, TopicMemory):
                    raise SourceLifecycleError("topic-family")
                available = _child_available(nodes, normalized_parents, normalized_policy)
                await self._store.insert_node(
                    connection,
                    self.scope_id,
                    LifecycleNode(
                        node_id=node_id,
                        kind="topic",
                        reference=reference,
                        parents=normalized_parents,
                        policy=normalized_policy,
                        revision=None,
                        available=available,
                    ),
                )

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        """Apply one Source event and return every currently available node id."""

        async with self._runtime._scoped_operation(self.scope_id), self._runtime._locked(self.scope_id):
            replay = False
            retry = False
            available: list[str] = []
            reconcile_nodes: dict[str, LifecycleNode] | None = None
            async with self._contexts.database.transaction() as connection:
                nodes = await self._store.nodes(connection, self.scope_id)
                node = nodes.get(event.node_id)
                if node is None or node.kind != "source":
                    raise SourceLifecycleError("event-source")
                if node.revision != event.revision:
                    raise SourceLifecycleError("event-revision")
                existing = await self._store.event(
                    connection,
                    self.scope_id,
                    event.node_id,
                    event.sequence,
                )
                if existing is not None:
                    if (
                        existing.revision != event.revision
                        or existing.available != event.available
                        or existing.reason != event.reason
                    ):
                        raise SourceLifecycleError("event-sequence")
                    if existing.applied:
                        replay = True
                        available = _available_ids(nodes)
                    else:
                        retry = True
                        available = _available_ids(nodes)
                else:
                    maximum = await self._store.max_sequence(connection, self.scope_id, event.node_id)
                    if maximum is not None and event.sequence <= maximum:
                        raise SourceLifecycleError("event-order")
                    await self._store.insert_event(
                        connection,
                        self.scope_id,
                        event.node_id,
                        revision=event.revision,
                        sequence=event.sequence,
                        available=event.available,
                        reason=event.reason,
                        applied=False,
                    )
                    updated = dict(nodes)
                    updated[event.node_id] = replace(node, available=event.available)
                    computed = _compute_availability(updated)
                    await self._store.set_availability(connection, self.scope_id, computed)
                    reconcile_nodes = {
                        node_id: replace(item, available=computed[node_id]) for node_id, item in updated.items()
                    }
                    available = _available_ids(reconcile_nodes)
            if replay:
                return available

            if retry:
                reconcile_nodes = await self._nodes()
                available = _available_ids(reconcile_nodes)
            if reconcile_nodes is None:
                raise SourceLifecycleError("node")
            await self._reconcile_memory(reconcile_nodes)
            async with self._contexts.database.transaction() as connection:
                await self._store.mark_applied(
                    connection,
                    self.scope_id,
                    event.node_id,
                    event.sequence,
                )
            return available

    async def resolve(self, node_id: str, /, *, purpose: str) -> LifecycleReference:
        """Return the original reference when generation or audit permits it."""

        if purpose not in _PURPOSES:
            raise SourceLifecycleError("purpose")
        node = await self._node(node_id)
        if node is None:
            raise SourceLifecycleError("node")
        if purpose == "generation" and not node.available:
            raise SourceLifecycleError("node-unavailable")
        return node.reference

    async def hidden_topic_refs(self) -> frozenset[tuple[str, int]]:
        """Return Topic revisions that native search and Context must omit."""

        async with self._contexts.database.transaction() as connection:
            return await self._store.hidden_topic_refs(connection, self.scope_id)

    async def _nodes(self) -> dict[str, LifecycleNode]:
        async with self._contexts.database.transaction() as connection:
            return await self._store.nodes(connection, self.scope_id)

    async def _node(self, node_id: str) -> LifecycleNode | None:
        _require_node_identity(node_id)
        async with self._contexts.database.transaction() as connection:
            return await self._store.node(connection, self.scope_id, node_id)

    async def _validate_memory_citation(self, citation: MemoryCitation) -> None:
        async with self._runtime._context(self.scope_id) as context:
            try:
                await context.artifacts.memory.validate_citation(citation)
            except (
                CapabilityNotSupportedError,
                InvalidMemoryCitationError,
                MemoryEntryNotFoundError,
                RepositoryNotFoundError,
            ) as error:
                raise SourceLifecycleError("memory-citation") from error

    async def _reconcile_memory(self, nodes: Mapping[str, LifecycleNode]) -> None:
        memory_nodes = [node for node in nodes.values() if node.kind == "memory"]
        if not memory_nodes:
            return
        async with self._runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            artifact_id = context.artifacts.memory_artifact_id
            try:
                memory = await service.head(artifact_id)
            except RepositoryNotFoundError as error:
                raise SourceLifecycleError("memory-artifact") from error
            for node in sorted(memory_nodes, key=lambda item: item.node_id):
                citation = _memory_citation(node)
                manifest = {item.entry_id: item for item in memory.content.manifest.entries}
                item = manifest.get(citation.entry_id)
                if item is None:
                    raise SourceLifecycleError("memory-entry")
                desired = node.available
                if (item.state == "active") == desired:
                    continue
                entries = {entry.entry_id: entry for entry in await service.entries(memory)}
                entry = entries.get(citation.entry_id)
                if entry is None:
                    raise SourceLifecycleError("memory-entry")
                if desired:
                    memory = await service.reactivate(memory, entries=(entry,), reason="source lifecycle")
                else:
                    memory = await service.forget(memory, entries=(entry,), reason="source lifecycle")


class SourceLifecycleApplication:
    """Select the lifecycle service for one Scope."""

    def __init__(self, runtime: BuiltinRuntime, contexts: RelationalContexts) -> None:
        self._runtime = runtime
        self._contexts = contexts

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycleApplication:
        return ScopedSourceLifecycleApplication(self._runtime, self._contexts, scope_id)

    async def hidden_topic_refs(self, scope_id: str, /) -> frozenset[tuple[str, int]]:
        return await self.for_scope(scope_id).hidden_topic_refs()


def _available_ids(nodes: Mapping[str, LifecycleNode]) -> list[str]:
    return sorted(node_id for node_id, node in nodes.items() if node.available)


def _compute_availability(nodes: Mapping[str, LifecycleNode]) -> dict[str, bool]:
    computed: dict[str, bool] = {}

    def resolve(node_id: str) -> bool:
        cached = computed.get(node_id)
        if cached is not None:
            return cached
        node = nodes[node_id]
        if node.kind == "source":
            value = node.available
        else:
            support = [resolve(parent) for parent in node.parents]
            value = all(support) if node.policy == "all" else any(support)
        computed[node_id] = value
        return value

    for node_id in nodes:
        resolve(node_id)
    return computed


def _child_available(nodes: Mapping[str, LifecycleNode], parents: tuple[str, ...], policy: LifecyclePolicy) -> bool:
    support = [nodes[parent].available for parent in parents]
    return all(support) if policy == "all" else any(support)


def _require_registered_parents(nodes: Mapping[str, LifecycleNode], parents: tuple[str, ...]) -> None:
    missing = [parent for parent in parents if parent not in nodes]
    if missing:
        raise SourceLifecycleError("parent-missing", missing[0])


def _normalize_parents(node_id: str, parents: Sequence[str]) -> tuple[str, ...]:
    values = tuple(parents)
    if not values:
        raise SourceLifecycleError("derived-parents")
    for parent in values:
        _require_node_identity(parent)
    if len(set(values)) != len(values):
        raise SourceLifecycleError("parent-duplicate")
    if node_id in values:
        raise SourceLifecycleError("parent-self")
    return values


def _require_node_identity(node_id: str) -> None:
    if not isinstance(node_id, str) or not node_id or not node_id.strip():
        raise SourceLifecycleError("node-id")


def _require_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SourceLifecycleError("revision", name)


def _require_policy(policy: object) -> LifecyclePolicy:
    if policy not in ("all", "any"):
        raise SourceLifecycleError("policy")
    return policy  # type: ignore[return-value]


def _require_memory_reference(citation: object) -> None:
    if not isinstance(citation, MemoryCitation):
        raise SourceLifecycleError("memory-reference")


def _require_topic_reference(reference: object) -> None:
    if not isinstance(reference, ArtifactRef) or reference.family != TopicMemory.family:
        raise SourceLifecycleError("topic-family")


def _memory_citation(node: LifecycleNode) -> MemoryCitation:
    reference = node.reference
    if not isinstance(reference, MemoryCitation):
        raise SourceLifecycleError("memory-node")
    return reference
