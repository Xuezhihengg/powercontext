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

"""Prefix-reusable context packs with exact, independently verifiable wire data."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import ClassVar

CONTEXT_PACK_SCHEMA = "powercontext.context-pack.v1"
CONTEXT_PACK_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class ContextPackError(ValueError):
    """A context pack or delta violates its wire or reconstruction contract."""


@dataclass(frozen=True, slots=True)
class ContextPack:
    """A complete context split into independently encoded byte chunks."""

    schema: ClassVar[str] = CONTEXT_PACK_SCHEMA
    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        if not all(isinstance(item, bytes) for item in self.items):
            raise ContextPackError("context pack items must be bytes")  # noqa: TRY003
        _validate_digest(self.digest)
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ContextPackError("context pack byte_count must be non-negative")  # noqa: TRY003

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        """Build a complete pack from ordered byte chunks."""

        normalized = tuple(items)
        digest = _pack_digest(normalized)
        byte_count = _pack_byte_count(normalized, digest)
        return cls(items=normalized, digest=digest, byte_count=byte_count)

    @classmethod
    def from_content(cls, content: str | bytes | None, *, chunk_bytes: int = 512) -> ContextPack:
        """Split UTF-8 content deterministically into bounded, valid UTF-8 chunks."""

        if type(chunk_bytes) is not int or chunk_bytes < 1:
            raise ContextPackError("chunk_bytes must be a positive integer")  # noqa: TRY003
        if content is None:
            return cls.build(())
        if isinstance(content, str):
            raw = content.encode("utf-8")
        elif isinstance(content, bytes):
            raw = content
        else:
            raise ContextPackError("content must be text or UTF-8 bytes")  # noqa: TRY003
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContextPackError("content must be valid UTF-8") from error  # noqa: TRY003
        return cls.build(_chunk_text(text, chunk_bytes))

    def to_bytes(self) -> bytes:
        """Serialize the canonical complete-pack wire representation."""

        return _canonical_json({
            "schema": self.schema,
            "items": [_encode_item(item) for item in self.items],
            "digest": self.digest,
            "byte_count": self.byte_count,
        })

    @classmethod
    def from_bytes(cls, raw: bytes) -> ContextPack:
        """Decode and verify one complete-pack wire representation."""

        payload = _load_object(raw)
        if set(payload) != {"schema", "items", "digest", "byte_count"}:
            raise ContextPackError("context pack fields are incomplete or unexpected")  # noqa: TRY003
        if payload["schema"] != CONTEXT_PACK_SCHEMA:
            raise ContextPackError("unsupported context pack schema")  # noqa: TRY003
        items = _decode_items(payload["items"])
        digest = _validate_digest(payload["digest"])
        byte_count = payload["byte_count"]
        if type(byte_count) is not int or byte_count < 0:
            raise ContextPackError("context pack byte_count must be non-negative")  # noqa: TRY003
        pack = cls(items=items, digest=digest, byte_count=byte_count)
        if pack.digest != _pack_digest(items) or pack.byte_count != len(pack.to_bytes()):
            raise ContextPackError("context pack digest or byte_count is invalid")  # noqa: TRY003
        return pack


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A retained base prefix plus the target chunks that follow it."""

    schema: ClassVar[str] = CONTEXT_PACK_DELTA_SCHEMA
    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _validate_digest(self.base_digest)
        _validate_digest(self.target_digest)
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("delta prefix_items must be a non-negative integer")  # noqa: TRY003
        object.__setattr__(self, "appended", tuple(self.appended))
        if not all(isinstance(item, bytes) for item in self.appended):
            raise ContextPackError("delta appended items must be bytes")  # noqa: TRY003

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        """Keep the longest shared chunk prefix and append the target suffix."""

        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("delta endpoints must be context packs")  # noqa: TRY003
        prefix = 0
        for left, right in zip(base.items, target.items, strict=False):
            if left != right:
                break
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    @property
    def byte_count(self) -> int:
        """The serialized delta size; never emitted as an extra wire field."""

        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        """Serialize the canonical delta wire representation."""

        return _canonical_json({
            "schema": self.schema,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": [_encode_item(item) for item in self.appended],
        })

    @classmethod
    def from_bytes(cls, raw: bytes) -> ContextPackDelta:
        """Decode and verify one delta wire representation."""

        payload = _load_object(raw)
        if set(payload) != {"schema", "base_digest", "target_digest", "prefix_items", "appended"}:
            raise ContextPackError("context pack delta fields are incomplete or unexpected")  # noqa: TRY003
        if payload["schema"] != CONTEXT_PACK_DELTA_SCHEMA:
            raise ContextPackError("unsupported context pack delta schema")  # noqa: TRY003
        delta = cls(
            base_digest=_validate_digest(payload["base_digest"]),
            target_digest=_validate_digest(payload["target_digest"]),
            prefix_items=payload["prefix_items"],
            appended=_decode_items(payload["appended"]),
        )
        return delta


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild and authenticate a target pack from one existing base pack."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("delta application requires a pack and a delta")  # noqa: TRY003
    if delta.base_digest != base.digest:
        raise ContextPackError("delta base digest does not match the supplied pack")  # noqa: TRY003
    if delta.prefix_items > len(base.items):
        raise ContextPackError("delta prefix exceeds the base pack")  # noqa: TRY003
    target = ContextPack.build((*base.items[: delta.prefix_items], *delta.appended))
    if target.digest != delta.target_digest:
        raise ContextPackError("delta target digest does not match the rebuilt pack")  # noqa: TRY003
    return target


def _chunk_text(text: str, chunk_bytes: int) -> tuple[bytes, ...]:
    chunks: list[bytes] = []
    current = bytearray()

    def flush() -> None:
        if current:
            chunks.append(bytes(current))
            current.clear()

    for line in text.splitlines(keepends=True):
        pieces = (line,) if len(line.encode("utf-8")) <= chunk_bytes else tuple(line)
        for piece in pieces:
            encoded = piece.encode("utf-8")
            if len(encoded) > chunk_bytes:
                raise ContextPackError("chunk_bytes cannot hold one UTF-8 character")  # noqa: TRY003
            if len(current) + len(encoded) > chunk_bytes:
                flush()
            current.extend(encoded)
    flush()
    return tuple(chunks)


def _encode_item(item: bytes) -> str:
    return base64.b64encode(item).decode("ascii")


def _decode_items(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError("wire items must be a Base64 string array")  # noqa: TRY003
    items: list[bytes] = []
    for encoded in value:
        if not isinstance(encoded, str):
            raise ContextPackError("wire items must be Base64 strings")  # noqa: TRY003
        try:
            item = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ContextPackError("wire item is not valid Base64") from error  # noqa: TRY003
        if _encode_item(item) != encoded:
            raise ContextPackError("wire item is not canonical Base64")  # noqa: TRY003
        items.append(item)
    return tuple(items)


def _validate_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ContextPackError("digest must be sha256:<64 lowercase hex characters>")  # noqa: TRY003
    return value


def _load_object(raw: bytes) -> dict[str, object]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContextPackError("wire payload must be UTF-8 JSON") from error  # noqa: TRY003
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ContextPackError("wire payload must be valid JSON") from error  # noqa: TRY003
    if not isinstance(payload, dict):
        raise ContextPackError("wire payload must be a JSON object")  # noqa: TRY003
    return payload


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pack_digest(items: tuple[bytes, ...]) -> str:
    unsigned = {
        "schema": CONTEXT_PACK_SCHEMA,
        "items": [_encode_item(item) for item in items],
    }
    return "sha256:" + hashlib.sha256(_canonical_json(unsigned)).hexdigest()


def _pack_byte_count(items: tuple[bytes, ...], digest: str) -> int:
    count = 0
    while True:
        payload = {
            "schema": CONTEXT_PACK_SCHEMA,
            "items": [_encode_item(item) for item in items],
            "digest": digest,
            "byte_count": count,
        }
        measured = len(_canonical_json(payload))
        if measured == count:
            return count
        count = measured


__all__ = [
    "CONTEXT_PACK_DELTA_SCHEMA",
    "CONTEXT_PACK_SCHEMA",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
