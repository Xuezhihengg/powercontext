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
