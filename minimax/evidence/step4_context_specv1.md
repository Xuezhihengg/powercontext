# 开发上下文（任务 T-001）

## 任务
业务需求：客户成功团队需要在客服后台按“状态 + 金额下限”筛选订单。 请修改订单服务的查询能力，使其支持按订单状态与金额下限过滤（具体约束以“适用的规格条目”为准）， 并保证既有查询行为与兼容性约束不被破坏。

## 适用规格条目
### ORD-001 按客户查询
来源：specs/SPEC-order-query.md
## ORD-001 按客户查询
订单查询接口必须按客户 ID 过滤，返回且仅返回该客户的全部订单。
- 优先级：P0
- 关联代码：src/order_service/service.py::list_orders
- 验证：tests/test_orders_regression.py::test_list_orders_by_customer

### ORD-CORE-001 状态枚举
来源：specs/SPEC-order-core.md
## ORD-CORE-001 状态枚举
订单状态仅限 pending/paid/shipped/cancelled 四种；不得新增状态或修改枚举语义。
- 优先级：P0
- 关联代码：src/order_service/models.py::STATUS_SET

### REF-001 退款金额边界
来源：specs/SPEC-refund-boundary.md
## REF-001 退款金额边界
退款金额为负数或超过原订单金额时，必须拒绝并抛出包含错误码 INVALID_AMOUNT 的 ValueError。
- 优先级：P0
- 关联代码：src/order_service/service.py::refund_order
- 验证：tests/test_orders_regression.py::test_refund_invalid_amount_raises

### REF-002 退款状态限制
来源：specs/SPEC-refund-boundary.md
## REF-002 退款状态限制
仅 paid/shipped 状态的订单允许退款；其他状态退款必须抛出包含错误码 REFUND_NOT_ALLOWED 的 ValueError。
- 优先级：P0
- 关联代码：src/order_service/service.py::refund_order
- 验证：tests/test_orders_regression.py::test_refund_only_paid_or_shipped

### ORD-002 空结果
来源：specs/SPEC-order-query.md
## ORD-002 空结果
客户不存在任何订单时，查询返回空列表，不得抛出异常。
- 优先级：P1
- 关联代码：src/order_service/service.py::list_orders
- 验证：tests/test_orders_regression.py::test_list_orders_empty_customer

### ORD-003 确定性排序
来源：specs/SPEC-order-query.md
## ORD-003 确定性排序
查询结果按 created_at 升序稳定排序；同秒内按插入顺序返回。
- 优先级：P1
- 关联代码：src/order_service/repository.py::list_by_customer
- 验证：tests/test_orders_regression.py::test_list_orders_ordering_stable

### ORD-CORE-002 金额单位
来源：specs/SPEC-order-core.md
## ORD-CORE-002 金额单位
Order.total_amount 一律使用整型分（cents），禁止浮点，避免精度误差。
- 优先级：P0
- 关联代码：src/order_service/models.py::Order

### ORD-CORE-003 调用兼容
来源：specs/SPEC-order-core.md
## ORD-CORE-003 调用兼容
list_orders(customer_id) 的位置参数调用方式必须保持不变；新增参数只能是带默认值的可选参数。
- 优先级：P0
- 关联代码：src/order_service/service.py::list_orders
- 验证：tests/test_orders_regression.py::test_list_orders_positional_compat

## 需要修改/相关的代码
### src/order_service/service.py（来源 seekdb:code）
```python
"""订单服务门面（v1）。

当前版本仅支持按客户过滤（SPEC-order-query ORD-001~003、SPEC-order-core ORD-CORE-003）。
"""

from __future__ import annotations

from order_service.models import STATUS_PAID, STATUS_SET, STATUS_SHIPPED, Order
from order_service.repository import InMemoryOrderRepository

_default_repository = InMemoryOrderRepository()


def reset_repository() -> InMemoryOrderRepository:
    """测试辅助：重建仓储并回填固定样例数据。"""
    global _default_repository
    _default_repository = InMemoryOrderRepository()
    for spec in SAMPLE_FIXTURES:
        create_order(**spec)
    return _default_repository


def create_order(
    customer_id: str,
    items: list[str],
    total_amount: int,
    status: str = "pending",
    order_id: str | None = None,
    repository: InMemoryOrderRepository | None = None,
) -> Order:
    repo = repository or _default_repository
    order = Order(
        order_id=order_id or f"ord-{repo.next_created_at():04d}",
        customer_id=customer_id,
        total_amount=total_amount,
        created_at=repo.next_created_at(),
        status=status,
        items=list(items),
    )
    return repo.add(order)


def get_order(order_id: str, repository: InMemoryOrderRepository | None = None) -> Order:
    repo = repository or _default_repository
    order = repo.get(order_id)
    if order is None:
        raise KeyError(f"ORDER_NOT_FOUND: {order_id}")
    return order


def list_orders(customer_id: str, repository: InMemoryOrderRepository | None = None) -> list[Order]:
    """按客户查询订单（ORD-001）。v1 仅支持 customer_id 过滤。"""
    repo = repository or _default_repository
    return repo.list_by_customer(customer_id)


def refund_order(order_id: str, refund_amount: int, repository: InMemoryOrderRepository | None = None) -> Order:
    """退款边界（SPEC-refund-boundary REF-001/REF-002，已实现，作为回归范围）。"""
    repo = repository or _default_repository
    order = get_order(order_id, repository=repo)
    if refund_amount < 0 or refund_amount > order.total_amount:
        raise ValueError(f"INVALID_AMOUNT: refund {refund_amount} not in [0, {order.total_amount}]")
    if order.status not in (STATUS_PAID, STATUS_SHIPPED):
        raise ValueError(f"REFUND_NOT_ALLOWED: status {order.status!r}")
    return order


# 固定样例数据：供回归与目标测试共享，保证前后运行数据集一致。
SAMPLE_FIXTURES = [
    {"order_id": "ord-0001", "customer_id": "c1", "items": ["book"], "total_amount": 500, "status": "pending"},
    {"order_id": "ord-0002", "customer_id": "c1", "items": ["keyboard"], "total_amount": 1500, "status": "paid"},
    {"order_id": "ord-0003", "customer_id": "c1", "items": ["mouse"], "total_amount": 900, "status": "paid"},
    {"order_id": "ord-0004", "customer_id": "c1", "items": ["monitor"], "total_amount": 2000, "status": "shipped"},
    {"order_id": "ord-0005", "customer_id": "c1", "items": ["cable"], "total_amount": 100, "status": "cancelled"},
    {"order_id": "ord-0006", "customer_id": "c2", "items": ["phone"], "total_amount": 3000, "status": "paid"},
]

reset_repository()
```

### src/order_service/repository.py（来源 seekdb:code）
```python
"""进程内订单仓储。业务工程保持自带存储，本模块与大赛上下文模块无关。"""

from __future__ import annotations

from order_service.models import Order


class InMemoryOrderRepository:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._seq = 0

    def next_created_at(self) -> int:
        self._seq += 1
        return self._seq

    def add(self, order: Order) -> Order:
        self._orders[order.order_id] = order
        return order

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def list_by_customer(self, customer_id: str) -> list[Order]:
        """ORD-001/ORD-002/ORD-003：按客户过滤并按 created_at 稳定升序。"""
        matched = [o for o in self._orders.values() if o.customer_id == customer_id]
        return sorted(matched, key=lambda o: o.created_at)
```

### src/order_service/models.py（来源 seekdb:code）
```python
"""订单模型与枚举。见 SPEC-order-core。"""

from __future__ import annotations

from dataclasses import dataclass, field

STATUS_PENDING = "pending"
STATUS_PAID = "paid"
STATUS_SHIPPED = "shipped"
STATUS_CANCELLED = "cancelled"
STATUS_SET = frozenset({STATUS_PENDING, STATUS_PAID, STATUS_SHIPPED, STATUS_CANCELLED})


@dataclass
class Order:
    """订单记录。

    total_amount 使用整型分（ORD-CORE-002），created_at 为插入序号（ORD-003 的稳定排序键）。
    """

    order_id: str
    customer_id: str
    total_amount: int
    created_at: int
    status: str = STATUS_PENDING
    items: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.total_amount, int) or self.total_amount < 0:
            raise ValueError(f"INVALID_AMOUNT: total_amount must be a non-negative int, got {self.total_amount!r}")
        if self.status not in STATUS_SET:
            raise ValueError(f"INVALID_STATUS: unknown order status {self.status!r}")
```

### src/order_service/__init__.py（来源 seekdb:code）
```python
"""order_service：大赛验证样例用的最小订单业务工程（纯标准库实现）。"""

from order_service.models import Order, STATUS_SET
from order_service.service import create_order, get_order, list_orders, refund_order

__all__ = ["Order", "STATUS_SET", "create_order", "get_order", "list_orders", "refund_order"]
```

## 验证测试
### tests/test_order_filter_target.py（来源 seekdb:test）
用例：test_filter_by_status, test_status_case_insensitive_and_trimmed, test_status_empty_or_none_means_no_filter, test_min_amount_filter, test_invalid_status_raises_error_code, test_combined_filters_keep_deterministic_ordering
```python
"""目标功能测试（任务 T-001）：修改前必须失败（目标行为未实现），修改后必须全部通过。

依据：SPEC-order-query v2 的 ORD-004/ORD-005，以及必须保持的 ORD-001/002/003/CORE-003。
只使用现有可导入名称，确保修改前的失败是功能性失败（TypeError/断言失败），不是环境错误。
"""

import pytest

from order_service import models, service


@pytest.fixture(autouse=True)
def _fixtures():
    service.reset_repository()


def _ids(orders):
    return [o.order_id for o in orders]


def test_filter_by_status():
    # ORD-004：status 过滤
    orders = service.list_orders("c1", status="paid")
    assert _ids(orders) == ["ord-0002", "ord-0003"]
    assert {o.status for o in orders} == {models.STATUS_PAID}


def test_status_case_insensitive_and_trimmed():
    # ORD-004：大小写不敏感、去除首尾空白
    assert _ids(service.list_orders("c1", status=" PAID ")) == _ids(service.list_orders("c1", status="paid"))


def test_status_empty_or_none_means_no_filter():
    # ORD-004：空字符串或 None 表示不过滤（且仍满足 ORD-001 客户范围）
    full = _ids(service.list_orders("c1"))
    assert _ids(service.list_orders("c1", status="")) == full
    assert _ids(service.list_orders("c1", status=None)) == full


def test_min_amount_filter():
    # ORD-005：min_amount 按 total_amount（整型分）做包含式下限过滤
    orders = service.list_orders("c1", min_amount=1000)
    assert _ids(orders) == ["ord-0002", "ord-0004"]
    assert all(o.total_amount >= 1000 for o in orders)


def test_invalid_status_raises_error_code():
    # ORD-005(边界)：非法 status 抛出含 INVALID_STATUS 的 ValueError，不得静默返回全部
    with pytest.raises(ValueError, match="INVALID_STATUS"):
        service.list_orders("c1", status="archived")


def test_combined_filters_keep_deterministic_ordering():
    # ORD-004+ORD-005 组合，结果仍满足 ORD-001 客户范围与 ORD-003 稳定排序
    orders = service.list_orders("c1", status="paid", min_amount=1000)
    assert _ids(orders) == ["ord-0002"]
```

### tests/test_orders_regression.py（来源 seekdb:test）
用例：test_create_and_fetch_order, test_create_order_rejects_float_amount, test_list_orders_by_customer, test_list_orders_empty_customer, test_list_orders_ordering_stable, test_list_orders_positional_compat, test_refund_invalid_amount_raises, test_refund_only_paid_or_shipped
```python
"""回归测试：修改前后都必须全部通过（覆盖 SPEC-order-query v1、SPEC-order-core、SPEC-refund-boundary）。"""

import pytest

from order_service import models, service


@pytest.fixture(autouse=True)
def _fixtures():
    service.reset_repository()


def test_create_and_fetch_order():
    order = service.create_order(customer_id="c3", items=["pen"], total_amount=120)
    fetched = service.get_order(order.order_id)
    assert fetched is order
    assert fetched.status == models.STATUS_PENDING


def test_create_order_rejects_float_amount():
    with pytest.raises(ValueError, match="INVALID_AMOUNT"):
        service.create_order(customer_id="c3", items=["pen"], total_amount=1.5)  # type: ignore[arg-type]


def test_list_orders_by_customer():
    orders = service.list_orders("c1")
    assert [o.order_id for o in orders] == ["ord-0001", "ord-0002", "ord-0003", "ord-0004", "ord-0005"]
    assert all(o.customer_id == "c1" for o in orders)


def test_list_orders_empty_customer():
    assert service.list_orders("nobody") == []


def test_list_orders_ordering_stable():
    orders = service.list_orders("c1")
    assert [o.created_at for o in orders] == sorted(o.created_at for o in orders)


def test_list_orders_positional_compat():
    # ORD-CORE-003：位置参数调用保持不变
    orders = service.list_orders("c2")
    assert [o.order_id for o in orders] == ["ord-0006"]


def test_refund_invalid_amount_raises():
    with pytest.raises(ValueError, match="INVALID_AMOUNT"):
        service.refund_order("ord-0002", -1)
    with pytest.raises(ValueError, match="INVALID_AMOUNT"):
        service.refund_order("ord-0002", 1501)


def test_refund_only_paid_or_shipped():
    with pytest.raises(ValueError, match="REFUND_NOT_ALLOWED"):
        service.refund_order("ord-0001", 100)  # pending
    assert service.refund_order("ord-0002", 1500).order_id == "ord-0002"
    assert service.refund_order("ord-0004", 500).order_id == "ord-0004"
```

### tests/conftest.py（来源 seekdb:test）
用例：
```python
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
```

## 任务状态（来自 PowerContext）
- 阶段：-
- 已完成：（空）
- 待办：（空）

## 来源核验
检查 15 条来源，缺失 0 条：无