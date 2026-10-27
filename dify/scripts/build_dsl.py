#!/usr/bin/env python3
# ruff: noqa: RUF001
"""Build the Dify Chatflow DSL from the code node sources in ../code."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = ROOT / "code"
OUTPUT = ROOT / "tavern-ledger.chatflow.yml"

START = "1001"
PREP = "1002"
SCOPE = "1003"
PARSE = "1004"
BRANCH = "1005"
SEARCH = "1006"
SEARCH_ALL = "1013"
MEMORY = "1007"
LLM = "1008"
REMEMBER = "1009"
FOOTER = "1010"
ANSWER = "1011"
ANSWER_ERROR = "1012"

BASE_URL = "{{#env.POWERCONTEXT_BASE_URL#}}"

SYSTEM_PROMPT = """你是「鲸落酒馆」的账房先生老周，怀里抱着一本从不离身的《鲸落账本》。
账本记着每位旅人干过的每一件荒唐事，你靠它收账、记仇，也靠它认人。

【旅人】{{#1002.player#}}
【本轮动作】{{#1002.action#}}
【账本检索】命中 {{#1007.hit_count_text#}} 条旧账：
{{#1007.memory_block#}}
【当前好感度】{{#1007.favor_text#}}（{{#1007.grudge_text#}}）
【你的心情】{{#1007.mood_hint#}}

说话规则：
1. 用市井、阴阳怪气、带账房术语的口吻（“记你一笔”“连本带利”“坏账”），每次 80~160 个汉字。
2. 只要账本里有旧账，就必须具体提到至少一条（复述玩家的原话或行为），并把它和本轮动作联系起来。
3. 如果本轮动作和某条旧账很像，要点明“你又来了”，再加一句夸张的“利息”。
4. 如果账本为空，就装大度，但暗示“你做的每件事我都会记下来”。
5. 不要编造账本里没有的具体旧事；不要输出好感度数字、列表或 Markdown。
6. 结尾用一句账房口吻的短句收束。"""

USER_PROMPT = "{{#1002.action#}}"

OPENING = """🏮 欢迎来到「鲸落酒馆」。我是账房先生老周，怀里这本《鲸落账本》，记着每位旅人干过的荒唐事。
先报个名号（本次对话里一直用这个名字），然后每说一句话，就是你干的一件事——赊账、吹牛、往汤里加料都行。
下次再进来，只要还叫这个名号，我可都记得。"""

SUGGESTED = [
    "我把盐当成糖，倒进了麦酒桶",
    "我赊了三杯麦酒，还把账本上的名字改成了隔壁老王",
    "我今天是来道歉的，上次的麦酒钱我补上",
]


class Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


Dumper.add_representer(str, _represent_str)


def load_code(name: str) -> str:
    return (CODE_DIR / name).read_text(encoding="utf-8")


def code_data(title: str, source: str, variables: list[tuple[str, list[str]]], outputs: dict[str, str]) -> dict:
    return {
        "title": title,
        "desc": "",
        "type": "code",
        "selected": False,
        "code_language": "python3",
        "code": source,
        "variables": [{"variable": var, "value_selector": selector} for var, selector in variables],
        "outputs": {name: {"type": kind, "children": None} for name, kind in outputs.items()},
    }


def http_data(title: str, path: str, body_selector: list[str], fallback: bool = False) -> dict:
    data = {
        "title": title,
        "desc": "",
        "type": "http-request",
        "selected": False,
        "method": "post",
        "url": BASE_URL + path,
        "headers": "Content-Type:application/json",
        "params": "",
        "body": {
            "type": "json",
            "data": [{"key": "", "type": "text", "value": "{{#" + ".".join(body_selector) + "#}}"}],
        },
        "authorization": {"type": "no-auth", "config": None},
        "timeout": {"max_connect_timeout": 5000, "max_read_timeout": 15000, "max_write_timeout": 5000},
        "retry_config": {"retry_enabled": True, "max_retries": 2, "retry_interval": 1000},
        "ssl_verify": True,
        "variables": [],
    }
    if fallback:
        data["error_strategy"] = "default-value"
        data["default_value"] = [
            {"key": "body", "type": "string", "value": "{}"},
            {"key": "status_code", "type": "number", "value": 0},
            {"key": "headers", "type": "object", "value": {}},
            {"key": "files", "type": "array[object]", "value": []},
        ]
    return data


def node(node_id: str, data: dict[str, Any], x: int, y: int, height: int) -> dict:
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": x, "y": y},
        "positionAbsolute": {"x": x, "y": y},
        "width": 244,
        "height": height,
        "selected": False,
        "sourcePosition": "right",
        "targetPosition": "left",
        "data": data,
    }


def edge(source: str, target: str, source_type: str, target_type: str, handle: str = "source") -> dict:
    return {
        "id": f"{source}-{handle}-{target}-target",
        "source": source,
        "sourceHandle": handle,
        "target": target,
        "targetHandle": "target",
        "type": "custom",
        "data": {
            "sourceType": source_type,
            "targetType": target_type,
            "isInIteration": False,
            "isInLoop": False,
        },
    }


def build() -> dict:
    nodes = [
        node(
            START,
            {
                "title": "开始",
                "desc": "收集旅人名号；每轮聊天内容就是本轮动作",
                "type": "start",
                "selected": False,
                "variables": [
                    {
                        "variable": "player_name",
                        "label": "你的名号",
                        "description": "账本按名号记账。下次用同名再进店，老周就能翻出旧账。",
                        "type": "text-input",
                        "required": True,
                        "max_length": 24,
                        "options": [],
                    }
                ],
            },
            80,
            300,
            130,
        ),
        node(
            PREP,
            code_data(
                "整理输入",
                load_code("prep_inputs.py"),
                [("arg_name", [START, "player_name"]), ("arg_action", ["sys", "query"])],
                {"player": "string", "action": "string", "scope_body": "string", "deed_text": "string"},
            ),
            380,
            300,
            160,
        ),
        node(
            SCOPE,
            http_data("开账本 / 取账本", "/v1/scopes", [PREP, "scope_body"], fallback=True),
            680,
            300,
            150,
        ),
        node(
            PARSE,
            code_data(
                "解析账本",
                load_code("parse_scope.py"),
                [
                    ("arg_body", [SCOPE, "body"]),
                    ("arg_action", [PREP, "action"]),
                    ("arg_player", [PREP, "player"]),
                    ("arg_deed", [PREP, "deed_text"]),
                ],
                {
                    "scope_id": "string",
                    "has_scope": "string",
                    "error_reason": "string",
                    "search_body": "string",
                    "list_body": "string",
                    "remember_body": "string",
                },
            ),
            980,
            300,
            180,
        ),
        node(
            BRANCH,
            {
                "title": "账本能用吗",
                "desc": "scope 创建失败时走错误提示，不继续查账",
                "type": "if-else",
                "selected": False,
                "logical_operator": "and",
                "cases": [
                    {
                        "case_id": "true",
                        "id": "true",
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "id": "cond-scope-ok",
                                "variable_selector": [PARSE, "has_scope"],
                                "comparison_operator": "is",
                                "value": "yes",
                                "varType": "string",
                            }
                        ],
                    }
                ],
            },
            1280,
            330,
            160,
        ),
        node(
            SEARCH,
            http_data("翻旧账", "/v1/memory/search", [PARSE, "search_body"]),
            1580,
            240,
            150,
        ),
        node(
            SEARCH_ALL,
            http_data("取整本账", "/v1/memory/search", [PARSE, "list_body"]),
            1880,
            240,
            150,
        ),
        node(
            MEMORY,
            code_data(
                "整理旧账与好感度",
                load_code("summarize_memory.py"),
                [
                    ("arg_relevant_body", [SEARCH, "body"]),
                    ("arg_list_body", [SEARCH_ALL, "body"]),
                    ("arg_action", [PREP, "action"]),
                ],
                {
                    "memory_block": "string",
                    "hit_count": "number",
                    "hit_count_text": "string",
                    "relevant_count": "number",
                    "relevant_count_text": "string",
                    "top_score_text": "string",
                    "has_memory": "string",
                    "favor": "number",
                    "favor_text": "string",
                    "grudge_text": "string",
                    "excerpt": "string",
                    "mood_hint": "string",
                },
            ),
            2180,
            240,
            280,
        ),
        node(
            LLM,
            {
                "title": "老周开口",
                "desc": "按账本旧账与好感度生成台词",
                "type": "llm",
                "selected": False,
                "model": {
                    "provider": "langgenius/openai/openai",
                    "name": "gpt-4o-mini",
                    "mode": "chat",
                    "completion_params": {"temperature": 0.9},
                },
                "prompt_template": [
                    {"role": "system", "text": SYSTEM_PROMPT},
                    {"role": "user", "text": USER_PROMPT},
                ],
                "context": {"enabled": False, "variable_selector": []},
                "vision": {"enabled": False},
                "variables": [],
            },
            2480,
            240,
            170,
        ),
        node(
            REMEMBER,
            http_data("记你一笔", "/v1/memory/remember", [PARSE, "remember_body"]),
            2780,
            240,
            150,
        ),
        node(
            FOOTER,
            code_data(
                "生成账本回执",
                load_code("build_footer.py"),
                [
                    ("arg_remember_body", [REMEMBER, "body"]),
                    ("arg_scope", [PARSE, "scope_id"]),
                    ("arg_relevant", [MEMORY, "relevant_count_text"]),
                    ("arg_hits", [MEMORY, "hit_count"]),
                    ("arg_score", [MEMORY, "top_score_text"]),
                    ("arg_favor_text", [MEMORY, "favor_text"]),
                    ("arg_grudge", [MEMORY, "grudge_text"]),
                    ("arg_excerpt", [MEMORY, "excerpt"]),
                ],
                {"footer": "string"},
            ),
            3080,
            240,
            240,
        ),
        node(
            ANSWER,
            {
                "title": "回答",
                "desc": "",
                "type": "answer",
                "selected": False,
                "answer": "{{#" + LLM + ".text#}}{{#" + FOOTER + ".footer#}}",
                "variables": [],
            },
            3380,
            240,
            200,
        ),
        node(
            ANSWER_ERROR,
            {
                "title": "账本坏了",
                "desc": "",
                "type": "answer",
                "selected": False,
                "answer": (
                    "😵 「账本今天被猫抓花了……」老周把账本合上，假装什么都没发生。\n\n"
                    "（PowerContext scope 创建失败：{{#" + PARSE + ".error_reason#}}）"
                ),
                "variables": [],
            },
            1580,
            520,
            160,
        ),
    ]

    edges = [
        edge(START, PREP, "start", "code"),
        edge(PREP, SCOPE, "code", "http-request"),
        edge(SCOPE, PARSE, "http-request", "code"),
        edge(PARSE, BRANCH, "code", "if-else"),
        edge(BRANCH, SEARCH, "if-else", "http-request", handle="true"),
        edge(SEARCH, SEARCH_ALL, "http-request", "http-request"),
        edge(SEARCH_ALL, MEMORY, "http-request", "code"),
        edge(MEMORY, LLM, "code", "llm"),
        edge(LLM, REMEMBER, "llm", "http-request"),
        edge(REMEMBER, FOOTER, "http-request", "code"),
        edge(FOOTER, ANSWER, "code", "answer"),
        edge(BRANCH, ANSWER_ERROR, "if-else", "answer", handle="false"),
    ]

    return {
        "app": {
            "name": "鲸落酒馆 · 老账房",
            "description": "一个会跨会话记住你每件荒唐事的酒馆 NPC。由 Dify Chatflow 编排，PowerContext 记账与翻旧账。",
            "icon": "🏮",
            "icon_background": "#FFEAD5",
            "mode": "advanced-chat",
            "use_icon_as_answer_icon": False,
        },
        "dependencies": [],
        "kind": "app",
        "version": "0.3.0",
        "workflow": {
            "conversation_variables": [],
            "environment_variables": [
                {
                    "name": "POWERCONTEXT_BASE_URL",
                    "description": "PowerContext Server 地址，例如 http://127.0.0.1:8000",
                    "value": "http://127.0.0.1:8000",
                    "value_type": "string",
                    "selector": ["env", "POWERCONTEXT_BASE_URL"],
                }
            ],
            "features": {
                "file_upload": {
                    "allowed_file_extensions": [".JPG", ".JPEG", ".PNG", ".GIF", ".WEBP", ".SVG"],
                    "allowed_file_types": ["image"],
                    "allowed_file_upload_methods": ["local_file", "remote_url"],
                    "enabled": False,
                    "fileUploadConfig": {
                        "audio_file_size_limit": 500,
                        "batch_count_limit": 5,
                        "file_size_limit": 15,
                        "image_file_size_limit": 100,
                        "video_file_size_limit": 500,
                        "workflow_file_upload_limit": 10,
                    },
                    "image": {"enabled": False, "number_limits": 3, "transfer_methods": ["local_file", "remote_url"]},
                    "number_limits": 3,
                },
                "opening_statement": OPENING,
                "retriever_resource": {"enabled": False},
                "sensitive_word_avoidance": {"enabled": False},
                "speech_to_text": {"enabled": False},
                "suggested_questions": SUGGESTED,
                "suggested_questions_after_answer": {"enabled": False},
                "text_to_speech": {"enabled": False, "language": "", "voice": ""},
            },
            "graph": {
                "nodes": nodes,
                "edges": edges,
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            },
        },
    }


def main() -> int:
    dsl = build()
    OUTPUT.write_text(
        yaml.dump(dsl, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT.relative_to(ROOT.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
