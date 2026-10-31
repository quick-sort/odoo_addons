# Tool / MCP 权限设计准则

> 版本 v0.1（2026-10-29）。本文是 `llm.tool` 与 `llm_mcp_server` 权限语义的唯一事实来源；
> 与 `tool_exposure.md` 冲突时以本文为准（后者回答“暴露什么”，本文回答“谁有权执行什么”）。

## 1. 范围与前提

适用范围：`llm.tool` 的注册与执行、`llm_mcp_server` 的 `tools/list` / `tools/call`、
`llm.mcp.client` 的远端桥接。

不适用：`agenthub` 的渠道身份映射（独立设计，进行中）。

已定前提：

- 内外部 agent 一律以**对话者身份**执行。内部对话者 = 会话用户；外部对话者 = MCP API key 所属用户。
- `odoo_model_method_executor` 的 `allow_private` 运行时开关已移除。
- Odoo 原生授权（`ir.model.access` + `ir.rule` + 字段 `groups=`）是唯一的数据安全边界。

## 2. 核心命题

> **MCP tool 是 JSON-RPC 的 agent 友好接口，不是权限层。
> 它不得让对话者获得其在 Odoo 权限之外的能力。**

由此，tool 级分组只承担“策展”——决定把哪些工具提供给这个 agent，
用于控制 context 与误用概率，不承担安全职责。

## 3. 能力边界

**唯一边界是：原生授权，加上“有没有提权”。**

以下都不构成能力边界，不应出现在安全评审依据里：

| 因素 | 为什么不构成边界 |
|---|---|
| 方法是 public 还是 private | private 只是不经 RPC 暴露；一个 public 方法包一个 private 方法，能力等价 |
| 是否带 `@llm_tool` | 装饰器只做注册，被扫描到的本来就是 public 方法 |
| 走 MCP、内部 agent 还是 ORM-RPC | 三条路径最终都在调用者 env 中执行，能力集合相同 |
| `allowed_group_ids`（MCP）/ `agent.tool_ids` | 只决定“是否主动提供”，底层调用始终存在 |

因此评审只需回答两个问题：**方法体里有没有 `sudo()`？有没有使用非对话者凭据？**

## 4. 分层

| 层 | 机制 | 职责 | 是否安全边界 |
|---|---|---|---|
| 数据授权 | `ir.model.access`、`ir.rule`、字段 `groups=` | 能碰什么数据 | **是，唯一** |
| 策展 | `allowed_group_ids`（MCP）、`agent.tool_ids`（内部 agent） | 提供哪些工具 | 否 |
| 提权代理 | 方法内 `sudo()`、远端 `api_key` | 代表系统执行 | 否，是例外 |

## 5. 不可违反的不变量

> 对任意 tool、任意对话者：**tool 的净权限 ⊆ 该对话者在 Odoo 中的权限**。

只有两种写法会破坏它：

1. 方法体内调用 `sudo()` 改变身份；
2. 执行时使用非对话者凭据（远端 MCP 的 `api_key`）。

`server_action` executor 不在例外内：它仍以对话者的 ACL 运行。

判据是“该用户自己的 Odoo 权限”，不是“RPC 可达集合”。后者更窄（private 方法不可 RPC）
却同样受 ACL 约束，用它当判据会把实现细节误当边界。

## 6. 准则

1. **原生授权是唯一硬边界。** 不得用 tool 分组表达“这个用户不能碰某类数据”。
2. **执行身份必须等于对话者。** 不允许换成 agent 用户、服务用户或 `su=True`。
3. **策展不可作为限制。** `allowed_group_ids` / `agent.tool_ids` 只能“不提供”，无法“阻止”；
   任何“禁止某人做某事”的需求必须落到 ACL / ir.rule。
4. **提权必须自带授权。** 使用 `sudo()` 或远端凭据的工具必须同时满足：
   声明理由；gate 放在方法体或 `execute()`（不能只放 MCP 层，因为 MCP 只是入口之一）；
   gate 强度不低于它所触碰的资源。
5. **提权 gate 优先用代理模型 + 原生 ACL。** 让授权仍由准则 1 管理，而不是在方法体里硬编码组。
6. **默认拒绝。** 身份无法确定时拒绝执行；新增工具默认不提供给 agent，需显式配置。
7. **审计与授权分离。** 记录对话者 uid、通道、工具、参数摘要、结果、耗时，
   用于验证与追溯，不作为拦截手段。`requires_user_consent` 属于交互约束，不是权限机制。

### 参考实现

`skillhub/models/tool.py`：先以对话者身份做 gate（`_get_skill_or_raise`、`_require_owner`），
再 `sudo()` 完成 plumbing，并在注释中说明理由（`storage.backend` 携带凭证、
`storage.mcp.token` 会签发绕过鉴权的 URL）。新工具应照此形态编写。

## 7. 反直觉推论

| 推论 | 理由 |
|---|---|
| `agent.tool_ids` 不是安全边界 | 身份不变，多挂一个普通工具不产生额外权限 |
| `invoke_agent` 不需要授权校验 | 同上；除非目标 agent 挂了提权类工具，那时边界在那些工具上 |
| 给 `odoo_*` 通用工具配分组不增加安全 | 它们等价于“用户自己的 ORM 权限”；该收紧的是 ACL / ir.rule |
| `llm.tool.execute` 可被 RPC 调用不是越权 | 它就是以调用者身份执行，与直接调用被装饰的方法等价 |
| 远端工具是本模型唯一的“身份替换” | 远端看到的是同一个服务端凭据，与对话者无关 |

## 8. 评审清单

新增或修改一个 tool 时逐条确认：

1. 方法体里有 `sudo()` 吗？有 → 是否声明了理由，gate 是否覆盖全部入口？
2. 使用了外部凭据吗？有 → 是否标记为远端代理并默认仅管理员可用？
3. 它对数据的访问是否全部落在对话者 ACL 内？是 → 不应为它设计任何 tool 级限制。
4. 这次配置是否被当作“禁止某人使用”的手段？是 → 改到 ACL / ir.rule。
5. 它的执行结果能否在审计里回答“谁、通过哪条通道、做了什么”？

## 9. 同名不同义（待确认，本版不改名）

`allowed_group_ids` 出现在三个模型上，语义并不相同。重命名牵动多处配置与数据，
因此**本版保留原名**，先记录现状与待确认项。

| 模型 | 所属 addon | 当前语义 | 空值 | 默认值 | 使用位置 |
|---|---|---|---|---|---|
| `llm.tool` | `llm`（`llm_mcp_server` 消费） | 谁能通过 MCP 看到并调用（策展） | 仅管理员 | 无（不填即空） | `tools/list`、`tools/call`、MCP Hub 的“未分配/已分配”过滤 |
| `llm.tool.guide` | `llm` | 谁能通过检索器看到 guide | 仅管理员 | `base.group_user` | `_readable_guides()`、动态 description |
| `llm.agent` | `llm` | 哪些用户能访问该 agent | 代码：无人；help：内部用户 | 无 | `_get_allowed_agents_for_user()` |

待确认：

1. `llm.tool` 与 `llm.tool.guide` 是否统一“空 = 仅管理员”？guide 现在默认全员，两者相反。
2. `llm.agent` 的空值语义：help 与实现不一致（实现 fail closed）。
3. 是否需要“按 agent 实例”的轴。三处都是按用户组；MCP 侧没有 agent 实例身份，
   per-agent 策展只在 `llm.agent.tool_ids`。
4. ~~`storage_backend_mcp` 的 guide 未显式设置该字段~~ **已处理**：storage 工具与
   guide 均显式声明 `base.group_system`，与 storage 模型 admin-only 的 ACL 对齐；
   存量实例由 `migrations/19.0.1.0.1/post-migrate.py` 收紧。

## 10. 存量差距（跟踪用）

| 位置 | 违反 | 处理 |
|---|---|---|
| `llm_page/models/llm_page_tool.py` | 准则 4、不变量 | 4 个工具全程 `sudo()` 且无对话者校验；`llm.page` 的 ACL 仅授予 viewer / reviewer。改为“先 gate 再 sudo”，或改用代理模型 |
| `llm/models/llm_mcp_client.py` 的 `api_key` | 准则 1 | 字段无 `groups=`，且 `llm.mcp.client` 对 `base.group_user` 可读 → 凭据可被普通用户读出。加字段级 `groups`，并考虑哈希化 |
| `llm_mcp_server/models/llm_tool.py` 的 `tool_domain` | 准则 6（一致性） | 只过滤 `tools/list`，`tools/call` 未应用。能力未越界，但策展对外不一致 |
| `llm/models/llm_tool_guide.py` 的 `allowed_group_ids` 默认值 | 准则 6 | 默认 `base.group_user`，与 tool 的“空 = 仅管理员”相反（见 §9 待确认 1） |

## 11. 待决

1. 是否引入显式的 **execution identity** 元数据（`caller` / `sudo` / `remote`）并加测试门禁：
   扫描 `@llm_tool` 方法体，凡出现 `sudo()` 或远端凭据者必须声明身份与 gate，否则测试失败。
2. 提权类工具的 gate 形态：代理模型 + ACL（本文推荐）与方法体 group 检查（过渡方案）并存到何时。
3. 远端工具是否需要向“对话者身份”对齐（per-user credential / token exchange），
   还是永久限定为管理员专属。
