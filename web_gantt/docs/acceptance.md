# Web Gantt — 验收标准

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| AC1 | 视图注册 | 模型定义 `<gantt date_start date_stop>` 后可在视图切换器中打开 | 人工检查 |
| AC2 | 时间尺度 | 工具栏有 Week / Month / Quarter / Year；Quarter 下表头上层为年份、下层为 Q1–Q4，每个单元格代表一个季度 | 人工检查 |
| AC3 | 季度刻度拖拽 | Quarter 尺度拖动任务条，起止日期按 3 个月吸附 | 人工检查 |
| AC4 | 折叠箭头 | 有子任务的行左侧显示三角箭头；无子任务的行不显示 | 人工检查 |
| AC5 | 折叠行为 | 点击箭头隐藏该任务的所有后代行（左栏与时间轴同步），再次点击恢复；折叠不改变数据 | 人工检查 |
| AC6 | 折叠点击范围 | 点击箭头只折叠，不打开表单；点击行内其他位置打开任务表单 | 人工检查 |
| AC7 | Assignee 展示 | 任务名右侧显示 assignee 名称；空间不足时名称与 assignee 分别省略，不重叠 | 人工检查 |
| AC8 | 行高 | 任务行高为 32px，任务条不溢出所在行 | 人工检查 |
| AC9 | Export Image | 点击后下载 PNG，内容包含左侧列表、全部任务行和完整时间范围，不含滚动条 | 人工检查 |
| AC10 | 导出状态恢复 | 导出后屏幕滚动位置与缩放保持不变 | 人工检查 |
| AC11 | 无数据导出 | 无任务时点击 Export Image 给出警告，不下载空文件 | 人工检查 |
| AC12 | 日期别名读写 | 实现 `_gantt_date_fields()` 后，两个别名读取后端字段；写别名（拖动）只更新后端字段，不产生新列 | `project_task_gantt/tests/test_project_task_gantt.py`（`test_gantt_alias_*`） |
| AC13 | 别名搜索 | `search([("gantt_date_start", "!=", False)])` 等价于后端字段过滤 | `test_search_on_gantt_date_aliases` |
| AC14 | 新建默认值 | Gantt 的 New 按钮把开始日期映射到后端 start 字段，别名不会进入 create vals | `test_default_get_maps_gantt_start_to_backing_field` |
| AC15 | 标记线渲染 | 返回 markers 后，在对应日期画出竖向虚线，颜色按 payload，压在任务条之上、不进入左侧列表 | 人工检查 |
| AC16 | 标记标签 | 标签常显在图表顶部；两条 lane 错开，放不下时省略标签但竖线保留 | 人工检查 |
| AC17 | 标记悬停 | 悬停竖线/标签显示 label、日期、description；悬停任务条仍显示任务信息 | 人工检查 |
| AC18 | 导出与范围 | marker 日期参与时间轴范围；PNG 包含标记线且导出后滚动/缩放恢复；CSV 仍只含任务 | 人工检查 |
| AC19 | 旧载荷兼容 | `get_gantt_data` 返回旧数组时，任务正常渲染、无标记线、footer/CSV/导出正常 | 人工检查 |
