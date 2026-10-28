"""MiniMax 代码修改引擎调用（OpenAI 兼容 chat completions）。

- 端点：POST {MINIMAX_BASE_URL}/chat/completions，默认 https://api.minimaxi.com/v1
- 鉴权：Authorization: Bearer $MINIMAX_API_KEY（仅运行时读取环境变量，不落盘、不写进证据文件）
- 模型：$MINIMAX_MODEL，默认 MiniMax-M3（开放平台当前可下单的推理模型；
  旧版 MiniMax-M2.x 已下线，请求返回 404 "model is no longer available"）

MiniMax-M3 属于「先思考再作答」的推理模型：思考过程与答案一起放在 message.content 里，\
用 <think>…</think> 包裹（部分型号思考放在 reasoning_content 字段）。所以解析约定 JSON 之前\
要先剥离思考块，并且 max_tokens 必须给思考留足预算（默认 24000，可用 MINIMAX_MAX_TOKENS 覆盖）。
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MODEL = "MiniMax-M3"

SYSTEM_PROMPT = """你是严格遵循规格的代码修改引擎。你将收到一个 SDD 开发上下文：任务描述、适用规格条目（含来源）、\
需要修改的代码文件当前内容和验证测试。请完成任务要求的代码修改。

输出格式：仅输出一个 JSON 对象（放在 ```json 围栏代码块中），不要输出其它文字：
{"summary": "一句话说明改动", "files": [{"path": "相对于工程根目录的路径", "content": "该文件修改后的完整内容"}]}

硬性要求：
1. 只能修改“需要修改/相关的代码”中列出的文件；不得新增文件，不得改动测试与规格。
2. 修改后的文件内容必须完整（不是 diff），保持原有导入、注释与无关函数不变。
3. 每条适用的规格条目都必须被满足；列出的回归约束（兼容性/既有行为）必须继续成立。
4. 让“验证测试”中的目标用例通过，同时不破坏现有测试。"""

_JSON_BLOCK_RE = re.compile(r"```(?:json|JSON)?[ \t]*\r?\n?(.*?)```", re.DOTALL)
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?(?:</think>|<END_THINK>|$)", re.DOTALL | re.IGNORECASE)


class MinimaxError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not key:
        raise MinimaxError("MINIMAX_API_KEY 未设置：MiniMax 调用需要参赛队伍获赠的 API Key（占位示例见 README）。")
    return key


def _post(body: dict[str, Any]) -> dict[str, Any]:
    url = os.environ.get("MINIMAX_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"},
            json=body,
            timeout=float(os.environ.get("MINIMAX_TIMEOUT", "900")),
        )
    except httpx.HTTPError as error:  # 网络层失败也要给出可读原因
        raise MinimaxError(f"调用 MiniMax {url} 失败：{error}") from error
    if response.status_code != 200:
        # 异常信息里没有 Key，只有 MiniMax 的错误体（含 request_id，便于排查额度/模型问题）
        raise MinimaxError(f"MiniMax HTTP {response.status_code} @ {url}: {response.text[:600]}")
    payload = response.json()
    payload["_endpoint"] = url
    return payload


def generate_change(context: dict[str, Any], user_instruction: str | None = None) -> dict[str, Any]:
    """把结构化上下文交给 MiniMax，返回 {request_log, raw_response, answer, parsed, response_json}。

    解析失败或输出被 max_tokens 截断时自动追加重试（MINIMAX_ATTEMPTS，默认 2 次）；
    每次尝试的端点、finish_reason、usage、耗时都记录在 request_log["attempts"] 中（开发记录）。
    """
    from sdd_context.context_builder import render_markdown

    context_md = render_markdown(context)
    instruction = user_instruction or "请依据以上上下文完成代码修改，并按要求输出 JSON。"
    body = {
        "model": os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context_md + "\n\n" + instruction},
        ],
        "temperature": float(os.environ.get("MINIMAX_TEMPERATURE", "0.1")),
        "max_tokens": int(os.environ.get("MINIMAX_MAX_TOKENS", "24000")),
    }
    attempts = max(1, int(os.environ.get("MINIMAX_ATTEMPTS", "2")))
    attempts_log: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}
    content = ""
    parsed: dict[str, Any] | None = None
    failure = ""

    for attempt in range(1, attempts + 1):
        started = time.time()
        payload = _post(body)
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        answer = _strip_think(content)
        attempts_log.append(
            {
                "attempt": attempt,
                "endpoint": payload.get("_endpoint"),
                "model": body["model"],
                "temperature": body["temperature"],
                "max_tokens": body["max_tokens"],
                "messages_count": len(body["messages"]),
                "finish_reason": choice.get("finish_reason"),
                "usage": payload.get("usage"),
                "response_id": payload.get("id"),
                "elapsed_ms": int((time.time() - started) * 1000),
                "content_chars": len(content),
                "reasoning_field_chars": len(reasoning),
            }
        )
        try:
            parsed = parse_files_json(answer, fallback_content=content)
            failure = ""
            break
        except MinimaxError as error:
            failure = str(error)
            if attempt < attempts:
                body["messages"] = body["messages"] + [
                    {"role": "assistant", "content": content[-4000:] or "(空)"},
                    {
                        "role": "user",
                        "content": (
                            f"上一次输出无法解析为约定的 JSON（{failure}）。"
                            "请收敛思考，直接输出唯一的 ```json 围栏代码块，块内只有 "
                            '{"summary": "...", "files": [{"path": "...", "content": "..."}]}，'
                            "不要输出其它文字。"
                        ),
                    },
                ]
    if parsed is None:
        last = attempts_log[-1]
        raise MinimaxError(
            f"{failure}（共尝试 {len(attempts_log)} 次；最后一次 finish_reason={last.get('finish_reason')}，"
            f"usage={last.get('usage')}。若输出被 max_tokens 截断，请提高 MINIMAX_MAX_TOKENS 后重跑）"
        )

    request_log = {
        **attempts_log[-1],
        "endpoint": attempts_log[0]["endpoint"],
        "attempts": attempts_log,
        "context_markdown": context_md,
        "user_instruction": instruction,
    }
    return {
        "request_log": request_log,
        "raw_response": content,
        "answer": answer,
        "parsed": parsed,
        "response_json": payload,
    }


def _strip_think(content: str) -> str:
    """剥掉推理模型写在正文里的思考块，只留最终答案（无思考块时原样返回）。"""
    stripped = _THINK_BLOCK_RE.sub("", content).strip()
    return stripped or content.strip()


def _balanced_objects(text: str) -> list[str]:
    """扫描出括号配对完整的顶层 JSON 对象（容忍缺失围栏、前后有废话）。"""
    found: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth:
                depth -= 1
                if depth == 0 and start >= 0:
                    found.append(text[start : index + 1])
    return found


def parse_files_json(content: str, fallback_content: str = "") -> dict[str, Any]:
    """从模型输出里取出 {"summary", "files"}：先围栏代码块，再整段文本，再括号配对扫描。"""
    candidates: list[str] = [content]
    candidates += [block for block in _JSON_BLOCK_RE.findall(content) if block.strip()]
    if fallback_content and fallback_content != content:
        candidates.append(fallback_content)
        candidates += [block for block in _JSON_BLOCK_RE.findall(fallback_content) if block.strip()]
    for candidate in candidates:
        for payload in [candidate.strip()] + _balanced_objects(candidate):
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and isinstance(parsed.get("files"), list):
                return parsed
    raise MinimaxError("MiniMax 输出中没有可解析的 files JSON；原始输出已保存在运行日志 raw_model_output 中。")
