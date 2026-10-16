# project_task_plan — 设计

## 目标

在任务保存时，按依赖关系自动重算后置任务的起止日期，做到「改一个前置、整条
依赖链自动顺延/提前」，并提供项目级开关与任务级例外。

## 依赖与复用

- `depends = ["project", "project_task_gantt"]`
- 依赖关系复用核心 `project.task` 的 `depend_on_ids`（Blocked By，前置）与
  `dependent_ids`（Blocks，后继）。方向约定：`A.depend_on_ids` 包含 B 表示
  B 阻塞 A，即 A 排在 B 之后。
- 排期字段复用 `project_task_gantt` 的：
  - `task_start_date` — 开始时间
  - `task_end_date` — 结束时间
  - `gantt_duration` — 时长（天，由起止计算）

## 数据模型（新增字段，全部 `_inherit`）

| 模型 | 字段 | 类型 | 默认 | 含义 |
|---|---|---|---|---|
| `project.project` | `allow_auto_schedule` | Boolean | `False` | 项目是否开启自动调整排期 |
| `project.task` | `no_auto_schedule` | Boolean | `False` | 例外开关：True 则不自动调整此任务 |
| `project.task` | `lead_time` | Float | `0.0` | 提前期（天），前置结束到本任务开始的最小间隔 |

字段语义：

- 一个任务**参与自动排期**当且仅当：其项目 `allow_auto_schedule` 为真 **且**
  自身 `no_auto_schedule` 为假 **且** 未完成（`is_closed` 为假）**且** 至少有
  一个前置（`depend_on_ids` 非空）。已完成任务不移动，但仍作为后继的约束。
- `no_auto_schedule = True` 的任务是「被钉住」的：它自己的起止日期不被自动
  改动，但它仍作为其后继任务的约束（后继仍以它的结束日为基准）。
- 项目开关为假时，该项目任务不参与自动排期（不会被移动）；但它们仍可作为
  其他（开启排期的）项目的任务的前置约束，提供结束日。

### 调整结果窗口（TransientModel）

开启排期时的批量拉齐需要把「哪些任务被改了」回显给用户，用一个临时模型承载：

| 模型 | 字段 | 类型 | 含义 |
|---|---|---|---|
| `project.task.plan.result` | `project_id` | M2o project.project | 所属项目 |
| | `moved_count` | Integer | 被调整任务数 |
| | `line_ids` | One2many result.line | 调整明细 |
| `project.task.plan.result.line` | `task_id` | M2o project.task | 被调整的任务 |
| | `old_start_date` / `old_end_date` | Datetime | 调整前起止 |
| | `new_start_date` / `new_end_date` | Datetime | 调整后起止 |

结果窗口由「开启排期」动作返回；未变化的任务不出现在明细里。

## 排期不变量

对每个参与自动排期的任务 T：

```
T.task_start_date == max( P.task_end_date for P in T.depend_on_ids ) + T.lead_time
T.task_end_date   == T.task_start_date + T.gantt_duration
```

- 前置结束日取 `P.task_end_date`；若为空，则退化为 `P.task_start_date`（视作
  零时长里程碑）。
- 保持时长：用调整前的 `gantt_duration` 作为平移后的时长，整体平移起止。
- 双向：目标日按不变量**确定性重算**，前置提前则后继提前，推迟则推迟。

## 传播规则

- 触发点：`project.task` 的 `write`（含 create 路径）中，任何影响排期的字段
  变化——`task_start_date`、`task_end_date`、`depend_on_ids`、`lead_time`、
  `no_auto_schedule`。这些「随写随排」的传播是**静默**的（不弹窗，避免每次
  编辑都打断用户）。
- 被编辑任务本身作为本次编辑的「锚点」，不做回溯调整；只重算其**传递后继**
  （`dependent_ids` 的传递闭包）。例外：当编辑的是 `depend_on_ids` /
  `lead_time` / `no_auto_schedule`（改变了该任务自身的约束）时，该任务本身
  也要重算。
- 重算按拓扑序进行，一次事务内收集全部目标值后批量写入；用 context 标记防止
  递归写回导致的重复/无限传播。
- 不变量天然无环：核心 `_check_no_cyclic_dependencies` 已把依赖强制为 DAG。

### 开启时的批量拉齐 + 结果窗口

- `project.project` 上有一个「自动对齐」按钮（`type="object"`），**仅在
  `allow_auto_schedule = True` 时显示**。点击后对项目内**未完成**任务做一次
  全量批量拉齐，然后返回 `project.task.plan.result` 结果窗口。
- 用按钮而非普通布尔开关的 `write` 触发：布尔字段的普通保存无法返回 action
  去打开窗口，按钮的 object 方法可以干净地返回结果向导。
- 批量拉齐与「随写随排」共用同一套拓扑重算逻辑，只是作用域为整个项目、且
  收集 `moved_count` 与新旧日期明细用于回显。

## 关键取舍

- **确定性重算 vs 增量平移**：选确定性重算。每次都按不变量重算目标日，幂等、
  可重入，避免增量平移的累积误差与顺序敏感。
- **lead_time 单字段 vs 每条依赖边一个 lead**：选单字段（per-task）。简单、
  符合需求；代价是同一任务对多个前置只有一个滞后量。per-edge 需要新关联表，
  暂不做，留作扩展。
- **双向 vs 只向后顺延**：按需求选双向。风险是会把任务提前；用测试锁定行为，
  并在验收里明确「提前」场景。
- **锚点不回溯**：用户手动改一个任务的日期时，不立即反推覆盖它，只向前传播，
  避免「改完又被改回去」的打架感。

## 与 project_task_gantt 的交互

`project_task_gantt` 已有 `task_end_date ↔ date_deadline` 的同步。自动排期改
`task_end_date` 时，`date_deadline` 会跟随变化，符合「截止日随排期走」的预期。
设计上不重复实现该同步，直接复用既有行为。

## 约束（红线）

1. 不改核心 `project` / `project_task_gantt` 的既有字段语义，全部通过
   `_inherit` 扩展。
2. 不绕过 ORM 的依赖成环检测。
3. 传播必须幂等、可重入安全（同一组写操作重复执行结果一致）。
4. `lead_time` 必须非负（≥ 0）：负数在 `create`/`write` 时被拒绝，不静默钳制。
