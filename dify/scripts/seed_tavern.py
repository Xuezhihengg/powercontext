#!/usr/bin/env python3
# ruff: noqa: RUF001, S310, TRY003
"""Create a tavern ledger scope and optionally preload a few deeds."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEMO_DEEDS = [
    "我把盐当成糖，倒进了麦酒桶",
    "我赊了三杯麦酒，还把账本上的名字改成了隔壁老王",
    "我声称自己认识城主，骗走了后厨一只烤鸡",
]


def post(base_url: str, path: str, payload: dict, token: str | None) -> tuple[int, dict]:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        raise SystemExit(f"POST {path} -> {error.code}: {body}") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--player", default="阿满")
    parser.add_argument("--deed", action="append", default=[], help="deed text, repeatable")
    parser.add_argument("--no-seed", action="store_true", help="only create the scope")
    parser.add_argument("--verify", action="store_true", help="list the ledger after seeding")
    parser.add_argument("--token", default=os.environ.get("POWERCONTEXT_TOKEN"))
    args = parser.parse_args()

    player = " ".join(args.player.split())[:24] or "无名旅人"
    scope_status, scope = post(
        args.base_url,
        "/v1/scopes",
        {
            "title": "鲸落酒馆账本 · " + player,
            "summary": "酒馆账房先生保存的玩家恶作剧、赊账与赖账记录",
            "idempotency_key": "tavern-ledger-v1:" + player,
        },
        args.token,
    )
    scope_id = scope["scope_id"]
    print(f"scope: {scope_id} (HTTP {scope_status}, idempotency_key=tavern-ledger-v1:{player})")

    deeds = args.deed or ([] if args.no_seed else DEMO_DEEDS)
    written = 0
    for deed in deeds:
        text = ("玩家" + player + "：" + deed)[:600]
        status, body = post(
            args.base_url,
            "/v1/memory/remember",
            {
                "scope_id": scope_id,
                "kind": "tavern-deed",
                "text": text,
                "reason": "初始化酒馆账本",
            },
            args.token,
        )
        entry = body.get("entry")
        entry_id = (entry or {}).get("citation", {}).get("entry_id", "")
        note = entry_id or "already recorded (deduped)"
        print(f"remember[{status}]: {text} -> {note}")
        written += 1
    print(f"seeded {written} deed(s) for {player}")

    if args.verify:
        status, body = post(
            args.base_url,
            "/v1/memory/search",
            {"scope_id": scope_id, "query": player, "limit": 20, "mode": "auto"},
            args.token,
        )
        hits = body.get("hits", [])
        print(f"search[{status}]: {len(hits)} hit(s)")
        for index, hit in enumerate(hits, start=1):
            print(f"  {index}. {str(hit.get('text', ''))[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
