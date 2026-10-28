"""sdd_context：规有所依——面向软件持续演进的 SDD 上下文模块。

- 工程资料（规格/代码/测试）存储与检索：seekdb（嵌入式，混合检索 = 全文 + 向量）。
- 任务状态保存与复用：PowerContext Server（atomic-memory）。
- 代码修改：MiniMax（OpenAI 兼容 chat completions）。
"""

__version__ = "0.1.0"
