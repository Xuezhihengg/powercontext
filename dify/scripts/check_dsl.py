#!/usr/bin/env python3
# ruff: noqa: C901
"""Static checks for the Chatflow DSL before importing it into Dify."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DSL_PATH = ROOT / "tavern-ledger.chatflow.yml"
SELECTOR = re.compile(r"\{\{#([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)#\}\}")
HTTP_OUTPUTS = {"body", "status_code", "headers", "files"}


def walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)


def main() -> int:
    dsl = yaml.safe_load(DSL_PATH.read_text(encoding="utf-8"))
    problems: list[str] = []

    if dsl.get("kind") != "app" or dsl.get("version") != "0.3.0":
        problems.append("kind must be app and version must be 0.3.0")
    if dsl.get("app", {}).get("mode") != "advanced-chat":
        problems.append("app.mode must be advanced-chat")

    graph = dsl["workflow"]["graph"]
    nodes = {item["id"]: item for item in graph["nodes"]}
    edges = graph["edges"]
    if len(nodes) != len(graph["nodes"]):
        problems.append("duplicate node ids")

    starts = [item for item in nodes.values() if item["data"]["type"] == "start"]
    answers = [item for item in nodes.values() if item["data"]["type"] == "answer"]
    if len(starts) != 1:
        problems.append(f"expected exactly one start node, found {len(starts)}")
    if not answers:
        problems.append("expected at least one answer node")

    outputs: dict[str, set[str]] = {}
    for node_id, item in nodes.items():
        data = item["data"]
        kind = data["type"]
        if kind == "start":
            outputs[node_id] = {variable["variable"] for variable in data.get("variables", [])}
        elif kind == "code":
            outputs[node_id] = set(data.get("outputs", {}))
            try:
                tree = ast.parse(data["code"])
            except SyntaxError as error:
                problems.append(f"code node {node_id} does not parse: {error}")
                continue
            functions = [item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "main"]
            if not functions:
                problems.append(f"code node {node_id} has no main()")
                continue
            parameters = [arg.arg for arg in functions[0].args.args]
            declared = [variable["variable"] for variable in data.get("variables", [])]
            if parameters != declared:
                problems.append(f"code node {node_id} params {parameters} != variables {declared}")
        elif kind == "http-request":
            outputs[node_id] = set(HTTP_OUTPUTS)
            for field in ("url", "method", "body"):
                if not data.get(field):
                    problems.append(f"http node {node_id} missing {field}")
            body = data.get("body", {})
            if body.get("type") == "json" and len(body.get("data", [])) != 1:
                problems.append(f"http node {node_id} json body must have exactly one item")
        elif kind == "llm":
            outputs[node_id] = {"text", "usage"}
            for field in ("model", "prompt_template", "context"):
                if field not in data:
                    problems.append(f"llm node {node_id} missing {field}")
        elif kind == "if-else":
            outputs[node_id] = set()
            cases = data.get("cases") or []
            if not cases:
                problems.append(f"if-else node {node_id} has no cases")
        elif kind == "answer":
            outputs[node_id] = set()
            if not data.get("answer"):
                problems.append(f"answer node {node_id} is empty")
        else:
            problems.append(f"unsupported node type {kind}")

    env_names = {item["name"] for item in dsl["workflow"].get("environment_variables", [])}
    for node_id, item in nodes.items():
        for text in walk_strings(item["data"]):
            for namespace, key in SELECTOR.findall(text):
                if namespace == "env":
                    if key not in env_names:
                        problems.append(f"node {node_id} references undefined env {key}")
                elif namespace == "sys":
                    if key != "query":
                        problems.append(f"node {node_id} references unsupported sys.{key}")
                elif namespace not in nodes:
                    problems.append(f"node {node_id} references unknown node {namespace}")
                elif key not in outputs.get(namespace, set()):
                    problems.append(f"node {node_id} references missing output {namespace}.{key}")

    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for item in edges:
        source, target = item["source"], item["target"]
        if source not in nodes or target not in nodes:
            problems.append(f"edge {item['id']} references missing node")
            continue
        adjacency[source].append(target)
        handle = item.get("sourceHandle", "source")
        if handle not in {"source", "true", "false"}:
            problems.append(f"edge {item['id']} has unknown sourceHandle {handle}")
        if nodes[source]["data"]["type"] == "if-else" and handle not in {"true", "false"}:
            problems.append(f"if-else edge {item['id']} must use true/false handle")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            problems.append(f"cycle detected at node {node_id}")
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for target in adjacency[node_id]:
            visit(target)
        visiting.remove(node_id)
        visited.add(node_id)

    if starts:
        visit(starts[0]["id"])
    unreachable = set(nodes) - visited
    if unreachable:
        problems.append(f"unreachable nodes: {sorted(unreachable)}")
    for node_id, targets in adjacency.items():
        if nodes[node_id]["data"]["type"] != "answer" and not targets:
            problems.append(f"node {node_id} has no outgoing edge")

    if problems:
        print("DSL check failed:")
        for problem in problems:
            print(" -", problem)
        return 1
    print(f"DSL check passed: {len(nodes)} nodes, {len(edges)} edges, {len(env_names)} env variables.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
