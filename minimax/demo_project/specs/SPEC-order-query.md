# SPEC-order-query：订单查询能力
- 状态：生效（v1）
- 适用范围：src/order_service/service.py::list_orders

## ORD-001 按客户查询
订单查询接口必须按客户 ID 过滤，返回且仅返回该客户的全部订单。
- 优先级：P0
- 关联代码：src/order_service/service.py::list_orders
- 验证：tests/test_orders_regression.py::test_list_orders_by_customer

## ORD-002 空结果
客户不存在任何订单时，查询返回空列表，不得抛出异常。
- 优先级：P1
- 关联代码：src/order_service/service.py::list_orders
- 验证：tests/test_orders_regression.py::test_list_orders_empty_customer

## ORD-003 确定性排序
查询结果按 created_at 升序稳定排序；同秒内按插入顺序返回。
- 优先级：P1
- 关联代码：src/order_service/repository.py::list_by_customer
- 验证：tests/test_orders_regression.py::test_list_orders_ordering_stable
