"""PowerContext 任务状态通道。

模块自身不落任何本地状态文件：保存与读取一律通过 PowerContext Server 的
atomic-memory API（/v1/memory/remember、/v1/memory/search、/v1/memory/entries/list）。
因此上下文模块进程重启（甚至换机器）后仍能读取并使用先前保存的任务状态。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from sdd_context.taskrecord import MEMORY_KIND, TaskRecord

SCOPE_TITLE = "MiniMax SDD demo (powercontext repo / minimax)"
SCOPE_SUMMARY = "SDD 上下文模块的任务状态 Scope：保存任务进展、待办与验证结果。"
SCOPE_IDEMPOTENCY_KEY = "minimax-sdd-scope-v1"


class PowerContextState:
    def __init__(self, base_url: str, scope_id: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.scope_id = scope_id
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # ---------- Scope ----------
    def ensure_scope(self) -> str:
        """固定幂等键创建/复用本作品的 Scope：任何新进程都会解析到同一 Scope。"""
        if self.scope_id:
            return self.scope_id
        created = self._client.post(
            "/v1/scopes",
            json={"title": SCOPE_TITLE, "summary": SCOPE_SUMMARY, "idempotency_key": SCOPE_IDEMPOTENCY_KEY},
        )
        if created.status_code < 400:
            self.scope_id = created.json()["scope_id"]
            return self.scope_id
        default = self._client.get("/v1/scopes/default")
        if default.status_code == 200:
            self.scope_id = default.json()["scope_id"]
            return self.scope_id
        created.raise_for_status()
        raise AssertionError("unreachable")

    # ---------- 写 ----------
    def save(self, record: TaskRecord) -> dict[str, Any]:
        scope = self.ensure_scope()
        response = self._client.post(
            "/v1/memory/remember",
            json={"scope_id": scope, "kind": MEMORY_KIND, "text": record.to_text()},
        )
        response.raise_for_status()
        payload = response.json()
        return {"scope_id": scope, "request_text": record.to_text(), "response": payload}

    # ---------- 读 ----------
    def search(self, query: str, limit: int = 20) -> list[TaskRecord]:
        scope = self.ensure_scope()
        response = self._client.post("/v1/memory/search", json={"scope_id": scope, "query": query, "limit": limit})
        response.raise_for_status()
        records = []
        for hit in response.json().get("hits", []):
            record = TaskRecord.from_text(hit["memory"]["text"])
            if record:
                records.append(record)
        return records

    def latest(self, task_id: str) -> TaskRecord | None:
        candidates = [record for record in self.search(task_id) if record.task_id == task_id]
        if not candidates:
            return None
        return max(candidates, key=lambda record: record.updated_at)

    def audit_dump(self, limit: int = 50) -> dict[str, Any]:
        """读取 Scope 内全部 task_state 记录，供“技术使用记录”归档与评审核对。"""
        scope = self.ensure_scope()
        response = self._client.post("/v1/memory/entries/list", json={"scope_id": scope, "include_inactive": True, "limit": limit})
        response.raise_for_status()
        entries = []
        for entry in response.json().get("entries", []):
            entries.append(
                {
                    "artifact": entry["artifact"],
                    "kind": entry["kind"],
                    "state": entry["state"],
                    "text": entry["text"],
                }
            )
        return {"scope_id": scope, "entries": entries}

    def close(self) -> None:
        self._client.close()
