# project_task_plan — 验收标准

> 本文是 QC 的唯一依据，`tests/` 里每个用例对应下面一个编号功能点。
> 记法：A 为前置任务，B/C 为后继；`P → B` 表示 B 依赖 P（`B.depend_on_ids` 含 P）。

## 字段与约束

- **AC-01 字段存在与默认值**：安装后 `project.project` 有 `allow_auto_schedule`
  （默认 `False`）；`project.task` 有 `no_auto_schedule`（默认 `False`）与
  `lead_time`（默认 `0.0`）。

- **AC-02 lead_time 非负约束**：`lead_time` 写入负数时，create/write 抛出
  `ValidationError`，记录不落库。

## 排期不变量

> 前置：项目开关 `allow_auto_schedule = True`；任务 B 未开 `no_auto_schedule`，
> 且有前置 A（`B.depend_on_ids = A`），`B.lead_time = L`。

- **AC-03 前置推迟，后继顺延（保持时长）**：把 A 的 `task_end_date` 向后改
  Δ 天 → B 的 `task_start_date` 变为 `A.task_end_date + L`，B 的
  `task_end_date` 变为「新开始 + 原 `gantt_duration`」；B 的 `gantt_duration`
  与改动前一致。

- **AC-04 双向：前置提前，后继提前**：把 A 的 `task_end_date` 向前改 →
  B 的起止日期按不变量同步前移。

- **AC-05 多前置取最大**：B 有前置 A1、A2（结束日分别为 E1、E2）→
  `B.task_start_date == max(E1, E2) + L`。

- **AC-06 lead_time 生效**：`B.lead_time = N`（N ≥ 0）→
  `B.task_start_date == max(前置结束) + N`。

- **AC-07 前置无结束日**：前置 P 只有 `task_start_date`、`task_end_date` 为空 →
  以 `P.task_start_date` 作为 P 的结束日参与取 max。

- **AC-19 忽略已完成任务**：`is_closed`（Done / Cancelled）的任务，无论作为被
  移动的后继还是批量拉齐的对象，都不被自动改动；但其结束日仍作为其后继的约束。

## 开关语义

- **AC-08 项目开关关**：`allow_auto_schedule = False` 时，改 A 的结束日，B 不移动。

- **AC-09 任务例外（no_auto_schedule）**：`B.no_auto_schedule = True` 时，改 A
  的结束日，B 不移动。

- **AC-10 例外任务仍约束其后继**：B 开例外、C 依赖 B 且未开例外。改 B 的结束日
  （手动改，因 B 例外不受自动移动）→ C 按 B 的新结束日自动排期。

- **AC-11 无前置任务不自动移动**：B 无 `depend_on_ids` → 任何其他任务变化都不
  移动 B。

## 传播

- **AC-12 传递级联**：A → B → C 链。改 A 的结束日 → B、C 都按不变量顺延
  （C 基于 B 的新结束日）。

- **AC-13 依赖变更触发重算**：给 B 增删前置，或改 `B.lead_time` /
  `B.no_auto_schedule` → B 自身（及其后继）按不变量重算。

- **AC-14 幂等 / 无重复写回**：单次写操作只触发一轮有界传播，不因递归写回产生
  重复移动或死循环（结果与重复执行一次相同）。

- **AC-15 成环拒绝**：构造 A→B→A 的依赖，保存被核心约束拒绝，无传播执行。

## 开启时的批量拉齐 + 结果窗口

- **AC-17 开启批量拉齐**：`allow_auto_schedule = True` 时项目显示「自动对齐」
  按钮；点击后，项目内所有**未完成**、参与排期且日期不符合不变量
  （`task_start_date ≠ max(前置结束) + lead_time`）的任务被一次性拉齐，且保持
  各自时长。

- **AC-18 结果窗口内容**：动作返回 `project.task.plan.result` 窗口，
  `moved_count` 等于实际被调整的任务数；`line_ids` 只含被调整的任务，每条
  记录 `old_start_date/old_end_date`、`new_start_date/new_end_date` 与调整前后
  一致；未变化的任务不出现在明细里。

## 与 project_task_gantt 的交互

- **AC-16 deadline 跟随**：自动排期改动 B 的 `task_end_date` 后，B 的
  `date_deadline` 同步变化（复用 `project_task_gantt` 既有同步）。
