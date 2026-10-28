# SPEC-order-query：订单查询能力
- 状态：生效（v2，2026-10 更新）
- 适用范围：src/order_service/service.py::list_orders
- 变更说明：v2 新增 ORD-004/ORD-005（按状态与金额下限过滤），v1 条目保持不变。

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

## ORD-004 状态与金额下限过滤（v2 新增）
list_orders 必须支持两个可选参数：status 与 min_amount。status 大小写不敏感并去除首尾空白，
空字符串或 None 表示不过滤；命中过滤后结果仍必须满足 ORD-001（客户范围）与 ORD-003（稳定排序）。
min_amount 为整型分下限，语义为包含式（total_amount >= min_amount）。
新增参数必须带默认值，保持 ORD-CORE-003 的位置参数兼容。
- 优先级：P0
- 关联代码：src/order_service/service.py::list_orders
- 验证：tests/test_order_filter_target.py::test_filter_by_status、
  test_status_case_insensitive_and_trimmed、test_status_empty_or_none_means_no_filter、test_min_amount_filter

## ORD-005 非法状态拒绝（v2 新增）
status 传入不在 STATUS_SET 中的值（如 archived）时，必须抛出包含错误码 INVALID_STATUS 的
ValueError，禁止静默忽略过滤条件返回全部订单。
- 优先级：P0
- 关联代码：src/order_service/service.py::list_orders
- 验证：tests/test_order_filter_target.py::test_invalid_status_raises_error_code
