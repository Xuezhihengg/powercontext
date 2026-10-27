# ruff: noqa: RUF001
import json

APOLOGY_WORDS = ("道歉", "对不起", "赔", "请客", "原谅", "补账", "认错", "还钱")
MAX_HITS = 8
TEXT_PREVIEW = 120


def collect(arg_body: str) -> list:
    try:
        payload = json.loads(arg_body or "{}")
    except (TypeError, ValueError):
        return []
    raw_hits = payload.get("hits") if isinstance(payload, dict) else []
    if not isinstance(raw_hits, list):
        return []
    return [item for item in raw_hits if isinstance(item, dict)]


def main(arg_relevant_body: str, arg_list_body: str, arg_action: str) -> dict:
    relevant = collect(arg_relevant_body)
    listed = collect(arg_list_body)
    merged = []
    seen = set()
    for hit in relevant + listed:
        text = str(hit.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(hit)
        if len(merged) >= MAX_HITS:
            break
    lines = []
    excerpt = []
    top_score = 0.0
    for index, hit in enumerate(merged, start=1):
        text = str(hit.get("text") or "").strip()
        try:
            score = float(hit.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        top_score = max(top_score, score)
        lines.append(f"[{index}] {text[:TEXT_PREVIEW]}（相关度 {score:.3f}）")
        if len(excerpt) < 3:
            excerpt.append(text[:60])
    apology = any(word in (arg_action or "") for word in APOLOGY_WORDS)
    favor = max(5, min(100, 80 - 7 * len(merged) + (12 if apology else 0)))
    if favor >= 75:
        grudge = "笑脸相迎"
    elif favor >= 50:
        grudge = "皮笑肉不笑"
    elif favor >= 25:
        grudge = "阴阳怪气"
    else:
        grudge = "已经忍你很久了"
    return {
        "memory_block": "\n".join(lines) or "（账本上还没有任何记录）",
        "hit_count": len(merged),
        "hit_count_text": str(len(merged)),
        "relevant_count": len(relevant),
        "relevant_count_text": str(len(relevant)),
        "top_score_text": f"{top_score:.3f}",
        "has_memory": "yes" if merged else "no",
        "favor": favor,
        "favor_text": str(favor) + "/100",
        "grudge_text": grudge,
        "excerpt": "；".join(excerpt) or "（无）",
        "mood_hint": (
            "账本上有旧账，你翻页的动作很熟练，语气里带着算总账的味道。"
            if merged
            else "账本是空的，你对这个生面孔还有一点耐心，但笔已经握在手里。"
        ),
    }
