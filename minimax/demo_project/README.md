# demo_project：订单服务（验证样例业务工程）

纯标准库 Python 工程，配套 `pytest` 运行测试。它模拟一个持续演进的业务代码库：

- `specs/`：SDD 规格（Markdown，按 `## <规格编号>` 分节）。
- `src/order_service/`：业务代码（v1：`list_orders` 仅支持按客户过滤）。
- `tests/test_orders_regression.py`：回归测试（修改前后都必须通过）。
- `tests/test_order_filter_target.py`：目标功能测试（对应任务 T-001；修改前失败、修改后通过）。

运行：

```bash
python -m pytest tests/test_orders_regression.py -v   # 回归
python -m pytest tests/test_order_filter_target.py -v # 目标任务 T-001（修改前失败）
```
