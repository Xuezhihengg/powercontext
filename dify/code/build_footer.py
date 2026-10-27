# ruff: noqa: RUF001
import json


def main(
    arg_remember_body: str,
    arg_scope: str,
    arg_relevant: str,
    arg_hits,
    arg_score: str,
    arg_favor_text: str,
    arg_grudge: str,
    arg_excerpt: str,
) -> dict:
    entry_note = "未入账（见服务日志）"
    try:
        payload = json.loads(arg_remember_body or "{}")
        entry = payload.get("entry") if isinstance(payload, dict) else None
        citation = entry.get("citation") if isinstance(entry, dict) else None
        entry_id = str((citation or {}).get("entry_id") or "").strip()
        if entry_id:
            entry_note = entry_id[:24] + "…（kind: tavern-deed）"
        elif isinstance(payload, dict) and payload.get("memory"):
            entry_note = "重复旧账，已合并（未新增）"
    except (TypeError, ValueError):
        pass
    footer = (
        "\n\n---\n"
        "🏮 鲸落酒馆 · 账本回执\n"
        "玩家账本：" + str(arg_scope) + "\n"
        "本轮检索：相关 "
        + str(arg_relevant)
        + " 条 / 账本共 "
        + str(arg_hits)
        + " 条（最高相关度 "
        + str(arg_score)
        + "）\n"
        "本轮入账：" + entry_note + "\n"
        "好感度：" + str(arg_favor_text) + " · " + str(arg_grudge) + "\n"
        "账本摘录：" + str(arg_excerpt)
    )
    return {"footer": footer}
