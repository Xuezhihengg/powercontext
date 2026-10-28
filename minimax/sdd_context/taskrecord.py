"""任务状态记录：与 PowerContext atomic-memory 的文本载荷一一对应。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

MEMORY_KIND = "task_state"
MAX_TEXT_BYTES = 8000  # PowerContext remember 限制 8192 UTF-8 字节，留余量


@dataclass
class TaskRecord:
    task_id: str
    title: str = ""
    phase: str = ""
    done: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    updated_at: str = ""

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    def to_text(self) -> str:
        payload = {
            "task_id": self.task_id,
            "title": self.title,
            "phase": self.phase,
            "done": self.done,
            "todo": self.todo,
            "results": self.results,
            "notes": self.notes,
            "updated_at": self.updated_at,
        }

        def dump(data: dict) -> str:
            return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

        text = dump(payload)
        if len(text.encode("utf-8")) <= MAX_TEXT_BYTES:
            return text
        payload["notes"] = payload["notes"][:400]
        text = dump(payload)
        if len(text.encode("utf-8")) <= MAX_TEXT_BYTES:
            return text
        payload["results"] = {"truncated": True, "keys": sorted(self.results)}
        text = dump(payload)
        if len(text.encode("utf-8")) <= MAX_TEXT_BYTES:
            return text
        return text.encode("utf-8")[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")

    @classmethod
    def from_text(cls, text: str) -> "TaskRecord | None":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or "task_id" not in payload:
            return None
        return cls(
            task_id=str(payload.get("task_id", "")),
            title=str(payload.get("title", "")),
            phase=str(payload.get("phase", "")),
            done=[str(item) for item in payload.get("done", []) if isinstance(item, (str, int))],
            todo=[str(item) for item in payload.get("todo", []) if isinstance(item, (str, int))],
            results=payload.get("results", {}) if isinstance(payload.get("results"), dict) else {},
            notes=str(payload.get("notes", "")),
            updated_at=str(payload.get("updated_at", "")),
        )
