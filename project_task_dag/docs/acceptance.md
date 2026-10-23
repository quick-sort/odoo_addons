# project_task_dag — 验收标准

QC 唯一依据，每个功能点至少一个测试。

1. **nodes/edges**：`get_dag_data` 对项目任务返回正确节点集与边集。
   → `test_nodes_and_edges`
2. **范围过滤**：只含 domain 命中的任务，不含其它项目任务。
   → `test_excludes_other_projects`
3. **跨 recordset 的边丢弃**：依赖对象不在 recordset 内时不产出边。
   → `test_edge_dropped_when_dependency_outside_recordset`
4. **state 归一化**：节点 state 归一到 `done/canceled/open`。
   → `test_state_normalized`
5. **RPC 契约**：`@api.model` + `domain` kwarg（`orm.call(model,'get_dag_data',[],{domain})`）。
   → `test_rpc_call_passes_domain_as_kwarg`
