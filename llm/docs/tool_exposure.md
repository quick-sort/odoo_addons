# Tool 暴露与编排指导原则

> 本文回答：一个 addon 要把能力暴露给 AI agent（内部 `llm_agent` 或外部 MCP 客户端）时，
> 什么情况下用通用 `odoo_*` 工具、什么情况下写自定义 `@llm_tool`，以及如何让 agent
> 发现并编排这些工具而不撑爆 context。
>
> 唯一事实来源。改代码前先读；实现细节在代码里，不在本文。

## 1. 背景

`llm` 提供两套把能力暴露给 agent 的机制，都已存在：

- **通用工具**（`odoo_record_*` / `odoo_model_*`）：一份代码覆盖所有 model，权限在 ORM 层。
- **自定义工具**（`@llm_tool` 装饰的方法）：一个方法一件事，封装业务逻辑。

两套各自够用，但缺一块拼图：**agent 怎么知道"这个 addon 该怎么操作"**——有哪些 model、
调哪些方法、按什么顺序、有什么不变量。本文补上这块（§4 `llm.tool.guide`），并给出选型规则（§3）。

## 2. 现状（已实现）

### 2.1 `@llm_tool` 装饰器与 `llm.tool` 注册表

- `@llm_tool`（`llm/decorators.py`）被动打标。启动扫描 `_scan_tool_decorators` 遍历
  `env.registry`，每个被装饰方法注册一条 `llm.tool`（`executor='model_method'`、`source='code'`）。
- `description` 来自 docstring，`input_schema` 来自签名；docstring 和类型标注是硬要求。
  详见 `llm/DECORATOR.md`。
- `llm.tool`：一条记录 = 一次暴露，`name` 唯一。内部 agent 与 MCP 都走它的 `execute()`。

### 2.2 通用工具（`llm.tool.builtin.*` 抽象模型）

| 工具 | 作用 |
|---|---|
| `odoo_record_retriever` | search_read 任意 model |
| `odoo_record_creator` | create 任意 model |
| `odoo_record_updater` | 按 id write |
| `odoo_record_unlinker` | 按 id unlink |
| `odoo_model_inspector` | 读 model 字段/方法 |
| `odoo_model_method_executor` | 调任意 model 方法 |

### 2.3 MCP 暴露与权限（`llm_mcp_server`）

- `llm_mcp_server` `_inherit = "llm.tool"`，加 `allowed_group_ids`（M2M `res.groups`）。
- `tools/list` 按 `_mcp_visibility_domain()` 过滤：无 group 的 tool 仅管理员可见；有 group 的
  只对组内用户可见；superuser 全见。
- `tools/call` 用同一 domain 二次校验，杜绝越权调用。
- 内部 agent 不经 MCP，直接 `llm.tool.execute()`。

## 3. 选型：通用 `odoo_*` vs 自定义 `@llm_tool`

| 维度 | 通用 `odoo_*` | 自定义 `@llm_tool` |
|---|---|---|
| 权限 | 真 ORM 层（access + record rule），通用层无法绕过 | 下沉进方法体，靠方法自己 discipline |
| 原子性 | 无，多步中途失败留半成品 | 一个方法一个事务 |
| 业务不变量 | 不强制 | 封装在方法内必然满足 |
| 副作用（文件/外部 API/消息） | 做不了 | 能做 |
| 维护成本 | 零新增 | 每个操作都要写方法 + docstring |
| 可靠性 | LLM 编排不确定、往返多 | 确定、可单测 |

**默认用通用 `odoo_*`。** 满足以下**任一**条件时，写自定义 `@llm_tool`：

1. 多步且必须原子；
2. 有 ORM 之外的副作用（文件上传/下载、外部 API、企微等）；
3. 有必须强制的业务不变量；
4. 高频高价值、LLM 编排出错代价高。

一句话：**权限不是问题（两种都走 ORM），事务和业务逻辑才是分水岭。**

### 3.1 中间路线：`odoo_model_method_executor` 调模型方法

不需要给每个 workflow 写 MCP 胶水。把逻辑写成模型上的 `@api.model` 方法（落点在它该在的
model 里），agent 用 `odoo_model_method_executor` 调它。代价与自定义 tool 相同：权限从
"ORM 自动保证"变成"方法体自己保证"。适合"逻辑在 addon 领域内、但不想暴露独立 tool"的场景。

## 4. `llm.tool.guide`：模块编排指南（提议，未实现）

### 4.1 要解决的问题

通用工具对 agent 是"哑"的——它不知道某 addon 有哪些 model、该调哪个方法、按什么顺序。
把每个 addon 的操作指南塞进 tool description 会撑爆 context（每个 tool 的 name/description
常驻 agent context）。需要一个"头常驻、正文按需"的懒加载编排文档。

### 4.2 数据模型（`llm.tool.guide`，在 `llm`）

一条记录 = 一个 addon 的操作编排指南：

- `code`（稳定 slug，通常即 module 名，如 `skillhub`）、`title`
- `summary`（头：一句话 + 该 addon 有哪些操作）
- `body`（正文：每个操作的编排序列 + 不变量 + 坑）
- `keyword`（极短关键词，用于拼进动态 description，见 §5）
- `allowed_group_ids`（M2M `res.groups`，可见性，见 §6）

数据贡献：addon 依赖 `llm`，用 XML data 把自己的 guide 写进 `llm.tool.guide`。

### 4.3 检索工具（`odoo_model_guide_retriever`，`@llm_tool` 装饰）

放在 `llm` 的 builtin 抽象模型上，注册方式同 `odoo_record_retriever`。三种模式，都按
"当前用户可读"过滤，与 §5 的 description 用**同一查询**：

- 给 `code` → 返回该 guide 的完整 `body`（`code`/`title`/`summary`/`body`）。
- 给 `query` → 大小写不敏感的子串搜索（code/title/keyword/summary），返回匹配的 index
  （`code`+`title`+`summary`）+ `count`，用于在大量 guide 里先收窄再取正文。
- 两者都不给 → 返回按 `code` 前缀分组的紧凑概览（每行 `code` + `guide_count`），避免
  guide 多时无参索引线性膨胀；再靠 `query` 下钻。

`code` 优先于 `query`：两者都给时按 `code` 取单条。

### 4.4 分层（谁提供什么）

```
llm             @llm_tool 装饰器 + llm.tool 注册表 + llm.tool.guide 模型 + odoo_model_guide_retriever
                （内部 agent 直接走 registry / execute，不经 MCP）
llm_mcp_server  依赖 llm；把注册表序列化成 MCP tools/list + tools/call；加 allowed_group_ids
skillhub 等     依赖 llm；用 XML 贡献 llm.tool.guide 记录（+ 自定义 @llm_tool 工具）
```

**一条代码路径**：`odoo_model_guide_retriever` 是唯一实现，内部 agent 走 registry、外部走
MCP 序列化，两端落到同一个函数，不可能漂移。MCP 层不重写查询。

## 5. 动态 description（每用户、build-time）

要让 agent **零调用**就发现"skillhub 存在"，guide 工具的 MCP description 里要内联各模块的
`keyword`：

- **build-time 动态**：`tools/list` 时，按"当前用户可读的 `llm.tool.guide`"拼出 keyword 列表，
  不是 import 时烘焙的静态串。装/卸模块后重启即生效（部署期动作，无感）。
- **与检索同一查询**：description 里的 keyword 集合 == `retrieve` 能返回的 guide 集合，
  都来自"当前用户可读的 guide"这一个过滤。否则会泄露模块存在性，或"广告了却拿不到"。
- **需要钩子**：`@llm_tool` 的 docstring 是静态的。给 guide 工具留一个动态 description 钩子
  （装饰器 `description_factory` 或伴生 `_describe()`，在 list 时被调用），docstring 保留
  通用静态描述作 fallback。
- **context 纪律**：description 里只放 `keyword`（短），`summary`/`body` 都在按需调用里。

## 6. 权限模型

> **权限语义以 [`permission_model.md`](permission_model.md) 为准。**
> 这里的 `allowed_group_ids` 是**策展**（决定 agent 被提供哪些工具），不是数据授权；
> 数据授权只来自原生 ACL / ir.rule。tool 分组无法实现“限制”。

两层，同一个 `res.groups` 机制，但**不要当同一个字段**：

| 层 | 字段 | 粒度 | 类比 |
|---|---|---|---|
| tool 级 | `llm_mcp_server` 继承的 `allowed_group_ids` | 这条 tool 是否进 tools/list | `ir.model.access` |
| guide 级 | `llm.tool.guide.allowed_group_ids` | 哪些 guide/keyword 可见 | record rule |

- **一致性靠约定**：guide 的 `allowed_group_ids` 应引用与"该模块 tools 的 `allowed_group_ids`"
  **同一个 `res.groups` 记录**，保证"能看见 tools ⟺ 能看见 guide"。不强制推导，由填表人负责。
- **依赖方向**：`llm` 不能依赖 `llm_mcp_server`（方向反了）。guide 的 group 字段只是
  `res.groups`（base 资源），在 `llm` 里可用，无依赖问题。

## 7. 关键取舍

### 为什么叫 `llm.tool.guide` 不叫 `llm.skill`

`skillhub.skill` 已存在（用户发布的 skill 包）。guide 是"操作某 addon 的编排文档"，是另一个
概念，避免同名歧义。

### 为什么单个参数化工具，而不是每模块一个 `how_to_use_X`

context 成本 = tool 数量 × 描述长度。每模块一个 tool 线性膨胀；单个 `odoo_model_guide_retriever`
恒定成本，发现靠动态 description 里的 keyword。

### 为什么 description 要动态而不是静态

静态串无法反映安装态（装了 skillhub 才出现 skillhub）与权限态（不同用户看到不同集合）。
guide 落成 record 后，才能在 `tools/list` 时按"安装 + 权限"拼出正确 keyword。

## 8. 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 每模块 `how_to_use_X` tool | N 个 tool 常驻 context，线性膨胀 |
| 手写静态 description | 无法反映安装态 + 无法按用户过滤 |
| `llm.skill` 命名 | 与 `skillhub.skill` 歧义 |
| guide 存进 `llm_mcp_server` | `llm` 反依赖 `llm_mcp_server`，内部 agent 用不了 |
| guide 复述 model schema | 与 `odoo_model_inspector` 双份真相，必漂移 |

## 9. 状态

- §2（`@llm_tool`、通用工具、`allowed_group_ids`）：**已实现**。
- §4–§6（`llm.tool.guide`、`odoo_model_guide_retriever`、动态 description）：**已实现**。
  模型 `llm.tool.guide`、工具 `odoo_model_guide_retriever`（`llm.tool.builtin.guide`）、
  `llm.tool.get_dynamic_description()` 钩子已落地。尚未做：下游 addon 用 XML 贡献 guide
  （skillhub 等接入时再补数据）。
