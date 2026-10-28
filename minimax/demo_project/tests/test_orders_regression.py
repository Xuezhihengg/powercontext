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
