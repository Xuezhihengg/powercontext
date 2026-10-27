#!/usr/bin/env python3
# ruff: noqa: RUF001, S102, TRY003, TRY301
"""Replay the exported Chatflow against a live PowerContext server.

The runner executes the same code nodes, HTTP nodes and branch conditions that Dify
executes. The LLM node is replaced by a deterministic stub, because the script has no
model credentials. Use it to verify PowerContext reads/writes and DSL wiring offline.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
DSL_PATH = ROOT / "tavern-ledger.chatflow.yml"
SELECTOR = re.compile(r"\{\{#([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)#\}\}")


class FlowError(RuntimeError):
    pass


class Runner:
    def __init__(self, dsl: dict[str, Any], base_url: str, verbose: bool = False) -> None:
        self.graph = dsl["workflow"]["graph"]
        self.nodes = {item["id"]: item for item in self.graph["nodes"]}
        self.edges = self.graph["edges"]
        self.base_url = base_url.rstrip("/")
        self.verbose = verbose
        self.env = {
            item["name"]: str(item.get("value", "")) for item in dsl["workflow"].get("environment_variables", [])
        }
        self.env["POWERCONTEXT_BASE_URL"] = self.base_url
        self.client = httpx.Client(timeout=20)

    def render(self, template: Any, pool: dict[str, dict[str, Any]]) -> str:
        def replace(match: re.Match[str]) -> str:
            namespace, key = match.group(1), match.group(2)
            if namespace == "env":
                return self.env.get(key, "")
            value = pool.get(namespace, {}).get(key, "")
            return "" if value is None else str(value)

        return SELECTOR.sub(replace, "" if template is None else str(template))

    def selector(self, selector: list[str], pool: dict[str, dict[str, Any]]) -> Any:
        return pool.get(selector[0], {}).get(selector[1])

    def run_code(self, data: dict[str, Any], pool: dict[str, dict[str, Any]]) -> dict[str, Any]:
        namespace: dict[str, Any] = {}
        exec(compile(data["code"], "<dify-code-node>", "exec"), namespace)
        kwargs = {item["variable"]: self.selector(item["value_selector"], pool) for item in data.get("variables", [])}
        result = namespace["main"](**kwargs)
        missing = set(data.get("outputs", {})) - set(result)
        if missing:
            raise FlowError(f"code node {data['title']} missing outputs: {sorted(missing)}")
        return dict(result)

    def run_http(self, data: dict[str, Any], pool: dict[str, dict[str, Any]]) -> dict[str, Any]:
        url = self.render(data["url"], pool)
        headers = {}
        for line in self.render(data.get("headers", ""), pool).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()
        body_text = self.render(data["body"]["data"][0]["value"], pool)
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as error:
            raise FlowError(f"HTTP node {data['title']} body is not JSON: {body_text[:200]}") from error
        try:
            response = self.client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                raise FlowError(f"HTTP node {data['title']} -> {response.status_code}: {response.text[:300]}")
        except (httpx.HTTPError, FlowError) as error:
            if data.get("error_strategy") != "default-value":
                raise
            if self.verbose:
                print(f"    POST {url} failed, using default value: {error}")
            defaults = {item["key"]: item["value"] for item in data.get("default_value", [])}
            return {
                "body": defaults.get("body", "{}"),
                "status_code": defaults.get("status_code", 0),
                "headers": defaults.get("headers", {}),
                "files": defaults.get("files", []),
            }
        if self.verbose:
            print(f"    POST {url} -> {response.status_code}")
        return {
            "body": response.text,
            "status_code": response.status_code,
            "headers": dict(response.headers),
        }

    def run_branch(self, data: dict[str, Any], pool: dict[str, dict[str, Any]]) -> str:
        for case in data.get("cases", []):
            results = []
            for condition in case.get("conditions", []):
                actual = self.selector(condition["variable_selector"], pool)
                operator = condition["comparison_operator"]
                expected = condition.get("value")
                if operator == "is":
                    results.append(str(actual) == str(expected))
                elif operator == "contains":
                    results.append(str(expected) in str(actual))
                elif operator == "empty":
                    results.append(not actual)
                elif operator == "not empty":
                    results.append(bool(actual))
                else:
                    raise FlowError(f"unsupported operator in verify runner: {operator}")
            matched = all(results) if case.get("logical_operator", "and") == "and" else any(results)
            if matched:
                return case["case_id"]
        return "false"

    def run_llm(self, data: dict[str, Any], pool: dict[str, dict[str, Any]]) -> str:
        prompt = "\n".join(self.render(item["text"], pool) for item in data["prompt_template"])
        if self.verbose:
            print("    prompt bytes:", len(prompt.encode("utf-8")))
        hits = pool.get("1007", {}).get("hit_count", 0)
        if not hits:
            return "（离线回放，未调用真实模型）老周抬起眼皮：「生面孔啊。不过我这本子，专记生面孔。」"
        excerpt = str(pool.get("1007", {}).get("excerpt", "")).split("；")[0]
        return (
            "（离线回放，未调用真实模型）老周翻着账本，指尖停在一行："
            f"「{excerpt}——这事我可记着。你这回又添了 {hits} 笔旧账的利息。」"
        )

    def run(self, player: str, action: str) -> dict[str, Any]:
        pool: dict[str, dict[str, Any]] = {"sys": {"query": action}}
        answer = ""
        trace = []
        current = next(item for item in self.nodes.values() if item["data"]["type"] == "start")
        pool[current["id"]] = {"player_name": player}
        for _ in range(50):
            data = current["data"]
            kind = data["type"]
            trace.append(f"{current['id']}:{kind}")
            if kind == "start":
                pass
            elif kind == "code":
                pool[current["id"]] = self.run_code(data, pool)
            elif kind == "http-request":
                pool[current["id"]] = self.run_http(data, pool)
            elif kind == "if-else":
                handle = self.run_branch(data, pool)
                pool[current["id"]] = {"_branch": handle}
                outgoing = [e for e in self.edges if e["source"] == current["id"] and e["sourceHandle"] == handle]
                if not outgoing:
                    raise FlowError(f"if-else {current['id']} has no edge for {handle}")
                current = self.nodes[outgoing[0]["target"]]
                continue
            elif kind == "llm":
                pool[current["id"]] = {"text": self.run_llm(data, pool)}
            elif kind == "answer":
                answer = self.render(data["answer"], pool)
                break
            else:
                raise FlowError(f"unsupported node type: {kind}")
            outgoing = [e for e in self.edges if e["source"] == current["id"]]
            if not outgoing:
                raise FlowError(f"node {current['id']} has no outgoing edge")
            current = self.nodes[outgoing[0]["target"]]
        else:
            raise FlowError("flow did not reach an answer node")
        return {
            "answer": answer,
            "scope_id": pool.get("1004", {}).get("scope_id", ""),
            "hit_count": pool.get("1007", {}).get("hit_count", 0),
            "memory_block": pool.get("1007", {}).get("memory_block", ""),
            "footer": pool.get("1010", {}).get("footer", ""),
            "trace": trace,
        }


def show(label: str, result: dict[str, Any]) -> None:
    print(f"\n== {label}")
    print("trace:", " -> ".join(result["trace"]))
    print("scope:", result["scope_id"])
    print("hits:", result["hit_count"])
    print(result["answer"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsl", default=str(DSL_PATH))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--player", default="", help="defaults to a unique name so reruns stay repeatable")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    dsl = yaml.safe_load(Path(args.dsl).read_text(encoding="utf-8"))
    player = args.player or f"验收员{uuid.uuid4().hex[:6]}"
    runner = Runner(dsl, args.base_url, verbose=args.verbose)

    try:
        if runner.client.get(f"{runner.base_url}/health/live").status_code != 200:
            raise FlowError("PowerContext health check failed")
        first = runner.run(player, "我把盐当成糖，倒进了麦酒桶")
        show(f"会话 A · {player} · 第 1 次", first)
        time.sleep(0.2)
        second = runner.run(player, "我赊了三杯麦酒，还把账本上的名字改成了隔壁老王")
        show(f"会话 B · {player} · 第 2 次（新会话）", second)
        time.sleep(0.2)
        third = runner.run(player, "我今天什么都没干，就是来道歉的")
        show(f"会话 C · {player} · 第 3 次（新会话）", third)
        other_player = player + "乙"
        other = runner.run(other_player, "我只是路过")
        show(f"隔离检查 · {other_player}", other)
    finally:
        runner.client.close()

    problems = []
    if second["hit_count"] <= first["hit_count"] or "盐" not in second["memory_block"]:
        problems.append("second run did not recall the first deed")
    if third["hit_count"] <= second["hit_count"] or "赊了三杯麦酒" not in third["memory_block"]:
        problems.append("third run did not recall the second deed")
    if not (first["scope_id"] == second["scope_id"] == third["scope_id"]):
        problems.append("scope_id changed between sessions")
    if "本轮入账：mem_ent_" not in third["footer"]:
        problems.append("footer does not show a PowerContext entry_id")
    if other["hit_count"] != 0 or other["scope_id"] in {first["scope_id"], ""}:
        problems.append("another player saw the first player's ledger")
    if problems:
        print("\nFAILED:")
        for item in problems:
            print(" -", item)
        return 1
    print("\nOK: 3 sessions shared one scope; reads, writes and player isolation verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
