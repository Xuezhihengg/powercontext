"""订单服务门面（v2）。

当前版本支持按客户过滤，并可按状态与金额下限过滤
（SPEC-order-query ORD-001~005、SPEC-order-core ORD-CORE-003）。
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


def list_orders(
    customer_id: str,
    repository: InMemoryOrderRepository | None = None,
    status: str | None = None,
    min_amount: int | None = None,
) -> list[Order]:
    """按客户查询订单，可选按状态和金额下限过滤（ORD-001/ORD-004/ORD-005）。"""
    normalized_status: str | None = None
    if status is not None:
        if not isinstance(status, str):
            raise ValueError(f"INVALID_STATUS: unknown order status {status!r}")
        candidate_status = status.strip().lower()
        if candidate_status:
            if candidate_status not in STATUS_SET:
                raise ValueError(f"INVALID_STATUS: unknown order status {status!r}")
            normalized_status = candidate_status

    repo = repository or _default_repository
    orders = repo.list_by_customer(customer_id)
    if normalized_status is not None:
        orders = [order for order in orders if order.status == normalized_status]
    if min_amount is not None:
        orders = [order for order in orders if order.total_amount >= min_amount]
    return orders


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
