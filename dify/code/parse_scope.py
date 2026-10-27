# ruff: noqa: RUF001
import json

CLAUSE_SEPARATORS = "，,。；;！!？?\n"


def focus(text: str) -> str:
    current = []
    for character in text or "":
        if character in CLAUSE_SEPARATORS:
            break
        current.append(character)
    clause = "".join(current).strip()
    return (clause or (text or "").strip())[:20]


def main(arg_body: str, arg_action: str, arg_player: str, arg_deed: str) -> dict:
    try:
        payload = json.loads(arg_body or "{}")
    except (TypeError, ValueError) as error:
        return {
            "scope_id": "",
            "has_scope": "no",
            "error_reason": ("无法解析 scope 响应：" + str(error))[:200],
            "search_body": "{}",
            "list_body": "{}",
            "remember_body": "{}",
        }
    scope_id = str(payload.get("scope_id") or "").strip() if isinstance(payload, dict) else ""
    if not scope_id:
        return {
            "scope_id": "",
            "has_scope": "no",
            "error_reason": "scope 响应中没有 scope_id",
            "search_body": "{}",
            "list_body": "{}",
            "remember_body": "{}",
        }
    search_body = json.dumps(
        {"scope_id": scope_id, "query": focus(arg_action), "limit": 4, "mode": "auto"},
        ensure_ascii=False,
    )
    list_body = json.dumps(
        {"scope_id": scope_id, "query": arg_player, "limit": 20, "mode": "auto"},
        ensure_ascii=False,
    )
    remember_body = json.dumps(
        {
            "scope_id": scope_id,
            "kind": "tavern-deed",
            "text": arg_deed,
            "reason": "酒馆账本自动记账",
        },
        ensure_ascii=False,
    )
    return {
        "scope_id": scope_id,
        "has_scope": "yes",
        "error_reason": "",
        "search_body": search_body,
        "list_body": list_body,
        "remember_body": remember_body,
    }
