"""MiniMax 代码修改引擎调用（OpenAI 兼容 chat completions）。

- 端点：POST {MINIMAX_BASE_URL}/chat/completions，默认 https://api.minimaxi.com/v1
- 鉴权：Authorization: Bearer $MINIMAX_API_KEY（仅运行时读取，不落盘）
- 模型：$MINIMAX_MODEL，默认 MiniMax-M2.1
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "MiniMax-M2.1"

SYSTEM_PROMPT = """你是严格遵循规格的代码修改引擎。你将收到一个 SDD 开发上下文：任务描述、适用规格条目（含来源）、\
需要修改的代码文件当前内容和验证测试。请完成任务要求的代码修改。

输出格式：仅输出一个 JSON 对象（放在 ```json 围栏代码块中），不要输出其它文字：
{"summary": "一句话说明改动", "files": [{"path": "相对于工程根目录的路径", "content": "该文件修改后的完整内容"}]}

硬性要求：
1. 只能修改“需要修改/相关的代码”中列出的文件；不得新增文件，不得改动测试与规格。
2. 修改后的文件内容必须完整（不是 diff），保持原有导入、注释与无关函数不变。
3. 每条适用的规格条目都必须被满足；列出的回归约束（兼容性/既有行为）必须继续成立。
4. 让“验证测试”中的目标用例通过，同时不破坏现有测试。"""

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class MinimaxError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not key:
        raise MinimaxError("MINIMAX_API_KEY 未设置：MiniMax 调用需要参赛队伍获赠的 API Key（占位示例见 README）。")
    return key


def generate_change(context: dict[str, Any], user_instruction: str | None = None) -> dict[str, Any]:
    """把结构化上下文交给 MiniMax，返回 {request_log, response, parsed}。"""
    from sdd_context.context_builder import render_markdown

    context_md = render_markdown(context)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": context_md + "\n\n" + (user_instruction or "请依据以上上下文完成代码修改，并按要求输出 JSON。"),
        },
    ]
    body = {
        "model": os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL),
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": int(os.environ.get("MINIMAX_MAX_TOKENS", "16000")),
    }
    url = os.environ.get("MINIMAX_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
        json=body,
        timeout=float(os.environ.get("MINIMAX_TIMEOUT", "600")),
    )
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    parsed = parse_files_json(content)
    request_log = {
        "endpoint": url,
        "model": body["model"],
        "temperature": body["temperature"],
        "max_tokens": body["max_tokens"],
        "context_markdown": context_md,
        "usage": payload.get("usage"),
        "response_id": payload.get("id"),
    }
    return {"request_log": request_log, "raw_response": content, "parsed": parsed, "response_json": payload}


def parse_files_json(content: str) -> dict[str, Any]:
    match = _JSON_BLOCK_RE.search(content)
    candidates = [match.group(1)] if match else []
    candidates.append(content)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("files"), list):
            return parsed
    raise MinimaxError("MiniMax 输出中没有可解析的 files JSON；原始输出已保存在运行日志中。")
