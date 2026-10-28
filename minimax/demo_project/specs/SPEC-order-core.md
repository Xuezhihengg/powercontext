# SPEC-order-core：订单模型与兼容性约束
- 状态：生效（v1）
- 适用范围：src/order_service/*

## ORD-CORE-001 状态枚举
订单状态仅限 pending/paid/shipped/cancelled 四种；不得新增状态或修改枚举语义。
- 优先级：P0
- 关联代码：src/order_service/models.py::STATUS_SET

## ORD-CORE-002 金额单位
Order.total_amount 一律使用整型分（cents），禁止浮点，避免精度误差。
- 优先级：P0
- 关联代码：src/order_service/models.py::Order

## ORD-CORE-003 调用兼容
list_orders(customer_id) 的位置参数调用方式必须保持不变；新增参数只能是带默认值的可选参数。
- 优先级：P0
- 关联代码：src/order_service/service.py::list_orders
- 验证：tests/test_orders_regression.py::test_list_orders_positional_compat
