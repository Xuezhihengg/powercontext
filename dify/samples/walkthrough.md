# 验证样例：老周记得你干过什么

本样例用「换新对话、不改名号」来验证：记忆来自 PowerContext，而不是 Dify 的会话变量。

## 0. 初始状态

- PowerContext：全新 SQLite 数据库，`/health/live` 返回 `{"status":"ok"}`。
- Dify：已导入 `tavern-ledger.chatflow.yml`，`POWERCONTEXT_BASE_URL` 指向该服务，LLM 已绑定可用模型。
- 玩家名号：`阿满`（首次出现，账本为空）。

## 1. 操作步骤（Dify 界面）

1. 发布并打开应用，点「新对话」。
2. 在「你的名号」填 `阿满`。
3. 在聊天框依次发送下面三条消息，每条发完点一次「新对话」再发下一条（只保留同名号）：

| 轮次 | 发送内容 |
| --- | --- |
| A | `我把盐当成糖，倒进了麦酒桶` |
| B | `我赊了三杯麦酒，还把账本上的名字改成了隔壁老王` |
| C | `我今天什么都没干，就是来道歉的` |

4. 观察每条回答的台词和底部「账本回执」。

## 2. 预期表现

- A：老周以初次见面的口气接待，账本回执为 `相关 0 条 / 账本共 0 条`，并出现新的 `entry_id`。
- B：老周具体提到“盐 / 麦酒桶”那笔旧账，回执为 `账本共 1 条`，好感度从 80 降到 73。
- C：老周仍能翻出 A、B 两笔旧账（`账本共 2 条`）；因为出现“道歉”，好感度回升到 78。
- 三次回执中的 `scope_id` 完全相同，说明同名号复用了同一本账。
- 换名号 `阿满乙` 再聊，账本为 0 条且 `scope_id` 不同。

## 3. 实际运行结果

以下为 `python dify/scripts/verify_flow.py --base-url http://127.0.0.1:18003 --player 阿满`
在全新数据库上的真实输出（LLM 由确定性桩代替，其余节点均按 DSL 执行并真实请求 PowerContext）。
验证时用了临时端口 `18003`，按 README 操作时换成你自己的 `http://127.0.0.1:8000` 即可：

```text
== 会话 A · 阿满 · 第 1 次
trace: 1001:start -> 1002:code -> 1003:http-request -> 1004:code -> 1005:if-else -> 1006:http-request -> 1013:http-request -> 1007:code -> 1008:llm -> 1009:http-request -> 1010:code -> 1011:answer
scope: scp_7t6qsaexj7p1wqhq2vmeq8n3jm
hits: 0
（离线回放，未调用真实模型）老周抬起眼皮：「生面孔啊。不过我这本子，专记生面孔。」

---
🏮 鲸落酒馆 · 账本回执
玩家账本：scp_7t6qsaexj7p1wqhq2vmeq8n3jm
本轮检索：相关 0 条 / 账本共 0 条（最高相关度 0.000）
本轮入账：mem_ent_20a0b13373af4191…（kind: tavern-deed）
好感度：80/100 · 笑脸相迎
账本摘录：（无）

== 会话 B · 阿满 · 第 2 次（新会话）
trace: 1001:start -> 1002:code -> 1003:http-request -> 1004:code -> 1005:if-else -> 1006:http-request -> 1013:http-request -> 1007:code -> 1008:llm -> 1009:http-request -> 1010:code -> 1011:answer
scope: scp_7t6qsaexj7p1wqhq2vmeq8n3jm
hits: 1
（离线回放，未调用真实模型）老周翻着账本，指尖停在一行：「玩家阿满：我把盐当成糖，倒进了麦酒桶——这事我可记着。你这回又添了 1 笔旧账的利息。」

---
🏮 鲸落酒馆 · 账本回执
玩家账本：scp_7t6qsaexj7p1wqhq2vmeq8n3jm
本轮检索：相关 1 条 / 账本共 1 条（最高相关度 0.016）
本轮入账：mem_ent_450711fdf9d049e2…（kind: tavern-deed）
好感度：73/100 · 皮笑肉不笑
账本摘录：玩家阿满：我把盐当成糖，倒进了麦酒桶

== 会话 C · 阿满 · 第 3 次（新会话）
trace: 1001:start -> 1002:code -> 1003:http-request -> 1004:code -> 1005:if-else -> 1006:http-request -> 1013:http-request -> 1007:code -> 1008:llm -> 1009:http-request -> 1010:code -> 1011:answer
scope: scp_7t6qsaexj7p1wqhq2vmeq8n3jm
hits: 2
（离线回放，未调用真实模型）老周翻着账本，指尖停在一行：「玩家阿满：我把盐当成糖，倒进了麦酒桶——这事我可记着。你这回又添了 2 笔旧账的利息。」

---
🏮 鲸落酒馆 · 账本回执
玩家账本：scp_7t6qsaexj7p1wqhq2vmeq8n3jm
本轮检索：相关 0 条 / 账本共 2 条（最高相关度 0.016）
本轮入账：mem_ent_94d7a8d185c3453f…（kind: tavern-deed）
好感度：78/100 · 笑脸相迎
账本摘录：玩家阿满：我把盐当成糖，倒进了麦酒桶；玩家阿满：我赊了三杯麦酒，还把账本上的名字改成了隔壁老王

== 隔离检查 · 阿满乙
trace: 1001:start -> 1002:code -> 1003:http-request -> 1004:code -> 1005:if-else -> 1006:http-request -> 1013:http-request -> 1007:code -> 1008:llm -> 1009:http-request -> 1010:code -> 1011:answer
scope: scp_17gsn4sncdt1tjqbg75h4zhn0v
hits: 0
（离线回放，未调用真实模型）老周抬起眼皮：「生面孔啊。不过我这本子，专记生面孔。」

---
🏮 鲸落酒馆 · 账本回执
玩家账本：scp_17gsn4sncdt1tjqbg75h4zhn0v
本轮检索：相关 0 条 / 账本共 0 条（最高相关度 0.000）
本轮入账：mem_ent_90d6907b41884a7a…（kind: tavern-deed）
好感度：80/100 · 笑脸相迎
账本摘录：（无）

OK: 3 sessions shared one scope; reads, writes and player isolation verified.
```

关键核对点：

- A/B/C 三次 `scope` 均为 `scp_7t6qsaexj7p1wqhq2vmeq8n3jm`，证明同名号跨会话复用同一本账。
- B 的 `账本共 1 条` 正是 A 写入的那条；C 的 `账本共 2 条` 包含 A、B 两条。
- 每次都有 `本轮入账：mem_ent_...`，证明 `remember` 真的写入了新条目。
- 隔离检查使用 `阿满乙`，`scope` 不同、`hits: 0`，证明按玩家分账。

## 4. 直接核对 PowerContext（可选）

```bash
# 用上面的 scope 查询整本账
curl -s http://127.0.0.1:8000/v1/memory/search \
  -H 'Content-Type: application/json' \
  -d '{"scope_id":"scp_7t6qsaexj7p1wqhq2vmeq8n3jm","query":"阿满","limit":20,"mode":"auto"}'
```

返回的 `hits[]` 中应包含“盐”“赊了三杯麦酒”“道歉”三条 `text`，每条带 `citation.entry_id`。

> 上面的 `scope_id` 与 `entry_id` 来自一次已经结束的验证实例，仅作记录；按步骤重跑会得到新的 ID。

## 5. 错误降级样例

把 `POWERCONTEXT_BASE_URL` 指向一个返回 `200 {}` 的桩服务，或在 scope 节点响应异常时，条件分支会走 `false`：

```text
trace: 1001:start -> 1002:code -> 1003:http-request -> 1004:code -> 1005:if-else -> 1012:answer
😵 「账本今天被猫抓花了……」老周把账本合上，假装什么都没发生。

（PowerContext scope 创建失败：scope 响应中没有 scope_id）
```

该路径已在本地桩服务上实测通过。

## 6. 恢复初始状态

- 最简单：换一个从未用过的名号（例如 `阿满-02`），会得到全新 scope。
- 或在 Dify 里只新建对话、仍用同名号：这是“保留旧账”的演示方式，不是重置。
- 彻底重置：停止 PowerContext，删除默认 SQLite 数据库
  `~/Library/Application Support/powercontext/powercontext.db`（macOS）或 `POWERCONTEXT_HOME` 指向目录下的同名文件，再重启服务。
