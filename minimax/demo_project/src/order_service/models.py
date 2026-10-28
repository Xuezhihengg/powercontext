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
