# ruff: noqa: RUF001
import json

MAX_PLAYER_CHARS = 24
MAX_ACTION_CHARS = 400
MAX_DEED_CHARS = 600


def main(arg_name: str, arg_action: str) -> dict:
    player = " ".join((arg_name or "").split())[:MAX_PLAYER_CHARS].strip() or "无名旅人"
    action = " ".join((arg_action or "").split())[:MAX_ACTION_CHARS].strip() or "我站在门口发呆"
    scope_body = json.dumps(
        {
            "title": "鲸落酒馆账本 · " + player,
            "summary": "酒馆账房先生保存的玩家恶作剧、赊账与赖账记录",
            "idempotency_key": "tavern-ledger-v1:" + player,
        },
        ensure_ascii=False,
    )
    deed_text = ("玩家" + player + "：" + action)[:MAX_DEED_CHARS]
    return {
        "player": player,
        "action": action,
        "scope_body": scope_body,
        "deed_text": deed_text,
    }
