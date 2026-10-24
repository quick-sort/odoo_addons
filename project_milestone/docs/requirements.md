# Requirements

## 背景

`project.milestone` 只有一个手工填写的固定日期 `deadline`。用户希望在不改动
手工 `deadline` 的前提下，多一个由任务动态计算出来的只读日期，反映该里程碑下
任务最晚的计划截止时间。

## 需求

1. 为 `project.milestone` 增加一个只读的计算字段 `last_task_deadline`（Date）。
2. 取值 = 该里程碑所有 `project.task` 中 `date_deadline`（计划截止）最晚的那个，
   取日期部分。
3. 没有任务、或任务都没有 `date_deadline` 时，字段为空。

## 边界（不做）

- 不改动手工 `deadline` 的语义或 UI。
- 不关心任务实际结束时间 `date_end`。
- 不新增任务/里程碑的写入口，字段纯只读。
