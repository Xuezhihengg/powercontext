# SPEC-refund-boundary：退款边界校验
- 状态：生效（v1）
- 适用范围：src/order_service/service.py::refund_order

## REF-001 退款金额边界
退款金额为负数或超过原订单金额时，必须拒绝并抛出包含错误码 INVALID_AMOUNT 的 ValueError。
- 优先级：P0
- 关联代码：src/order_service/service.py::refund_order
- 验证：tests/test_orders_regression.py::test_refund_invalid_amount_raises

## REF-002 退款状态限制
仅 paid/shipped 状态的订单允许退款；其他状态退款必须抛出包含错误码 REFUND_NOT_ALLOWED 的 ValueError。
- 优先级：P0
- 关联代码：src/order_service/service.py::refund_order
- 验证：tests/test_orders_regression.py::test_refund_only_paid_or_shipped
