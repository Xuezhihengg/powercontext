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
