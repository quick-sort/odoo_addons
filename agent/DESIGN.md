# `agent` 模块族设计（Odoo 19 · component 多态）

> 状态：设计稿 v1（2026-08-13）。先设计，评审通过后再实现。

---

## 1. 目标与定位

在当前目录（`odoo_addons/`）新增一套 **agent 框架**：一个「带工具循环的 LLM 智能体」编排层。
与两套参考实现（apexive `odoo-llm`、Odoo 官方 `ai`）的核心差异：

- **多态用 OCA `component` 模块**，而不是字符串方法派发（`odoo-llm` 的 `{service}_{verb}`）、
  也不是 `if provider == 'openai'/'google'` 的硬编码分支（官方 `ai` 的 `LLMApiService`）。
- **复用 `odoo-llm` 已有的数据基础**（`llm.provider` / `llm.model` / `llm.tool` / `llm.thread`），
  把「会变的部分」抽成 component，而不是重写 provider 适配器 / tool 模型 / 会话持久化。
- **遵循本目录已有套件的惯例**（`knowledge_base*`、`one_storage`）：核心 addon 只定义抽象 component
  接口 + 通用兜底实现，具体 provider / tool / 上下文来源放在薄薄的扩展 addon 里，通过
  `_collection` + `_usage` 注册。

---

## 2. 两套参考实现的分析

### 2.1 apexive `odoo-llm`（`/odoo_llm`）

**模块设计**：按职责拆成一系列 addon，单向依赖：

| addon | 职责 |
|---|---|
| `llm` | 核心：`llm.provider`（service 选择 + `api_key`/`api_base` + `client`）、`llm.model`（`model_use`/`is_default`/`details`） |
| `llm_openai` / `llm_anthropic` … | provider 适配器：`_inherit="llm.provider"`，往 `_get_available_services()` 追加 service |
| `llm_tool` | tool 模型 + `@llm_tool` 装饰器 + `_register_hook` 自动同步到 DB |
| `llm_tool_mcp` / `llm_tool_websearch` / `llm_tool_web_research` | 具体 tool 扩展 |
| `llm_thread` | 会话持久化：`llm.thread`（`mail.thread` + role 子类型） |
| `llm_assistant` | 声明式智能体：`llm.assistant`（provider+model+prompt+tool_ids+tool_calls_max）+ `generate_messages` 循环 + `invoke_assistant` 组合 |
| `llm_knowledge` + `llm_pgvector`/`llm_qdrant` + `llm_store` | RAG |

**接口设计（关键契约）**：

1. **Provider 抽象 = 字符串派发**：`llm.provider._dispatch(method, *args)` → `getattr(self, f"{service}_{method}")`。
   公开动词：`chat` / `embedding` / `generate` / `list_models` / `format_tools` / `format_messages` /
   `get_client`，扩展方式 = `_inherit` + `_get_available_services()` + `{service}_{verb}` 方法。
2. **标准 chat 响应 dict**：`{"content": str, "tool_calls": [...], "images": [...], "thinking": ..., "error": ...}`；
   streaming 时按块逐条 yield 这个 dict。
3. **Tool 抽象**：`llm.tool.implementation` Selection + `_get_available_implementations()` + `{impl}_execute(params)`；
   `@llm_tool` 装饰器从类型注解（MCP SDK）推导 input JSON schema；`get_tool_definition()` 输出 MCP 兼容 JSON。
4. **会话/循环**：`llm.thread.generate()` → `generate_messages(last_message)` 的 `while` 循环：
   user/tool → `_generate_assistant_response()`（调 `model_id.chat(tools=..., prepend_messages=...)`）；
   assistant 带 `tool_calls` → 逐个 `_execute_tool_call()` → 经 `mail.message.post_tool_call()` 写 tool 结果消息；
   直到 `_should_continue()` 为假或 `tool_calls_max` 轮。streaming 是事件 generator：
   `{"type": "message_create"/"message_chunk"/"message_update"/"error"/"limit_reached", ...}`。
   循环内**绝不 commit**，事务边界交给 controller / `queue_job`。
5. **组合**：`llm.assistant.invoke(query, new_cursor=...)` 开子线程跑；`invoke_assistant` tool 带深度护栏。

**评价**：功能成熟（streaming / 持久化 / RAG / MCP 全齐）；但抽象走的是 Odoo `_inherit` + 字符串方法名，
不是 component 注册表，也没有跨 addon 的事件钩子。

### 2.2 Odoo 官方 `ai`（`odoo-19.0+.../addons/ai`）

**模块设计**：单个 `ai` addon（不是套件）。模型 `ai.agent` / `ai.topic` / `ai.embedding` / `ai.composer` /
`ai_env_context`；**复用** `discuss.channel`+`mail.message` 存会话、`ir.actions.server` 存 tool；
`orm/field_vector.py` 提供 pgvector 字段；`utils/tools_schema/` 做 tool 的 JSON-schema 校验。

**接口设计**：

1. **Provider 抽象 = 手写分支**：`LLMApiService` + `PROVIDERS` NamedTuple 表，
   `_request_llm` 里 `if provider == 'openai'/'google'`，配套 `_request_llm_openai_helper` /
   `_request_llm_google_helper` / `_build_tool_call_response`。
   `request_llm(model, system_prompts, user_prompts, tools=..., files=..., schema=..., temperature=...) -> list[str]`，
   内部自带多步 tool 循环（`_request_llm_silent`，最多 `ai.max_successive_calls` 次）。
2. **Tool 抽象 = `ir.actions.server` 代码动作**：`use_in_ai` + `ai_tool_description` + `ai_tool_schema`
   （JSON object，禁止嵌套）+ `ai_tool_allow_end_message`（终结型 tool）；运行时 `_ai_tool_run` 用
   `eval_context["record"]` 执行；聚合成的 `tools` dict 形如 `{name: (desc, allow_end, callable, schema)}`。
3. **智能体 = `ai.agent`**（model + system prompt + `agent_tool_ids` + RAG `source`），
   通过 `_generate_response` 复用同一个 `request_llm` 循环。
4. **完全不用 `component`**；没有独立的 tool / message / thread 模型；前端由 OWL + discuss bus 驱动。

**评价**：与 Discuss UI 和 `ir.actions.server` 强耦合；tool 循环塞在 `LLMApiService` 内部，
加 provider 要改 `LLMApiService` 源码，没有干净的插件点；不是 component 架构。

### 2.3 小结：这套新 addon 要「取长补短」

- 从 `odoo-llm` 取：**数据基础与流式/持久化**（provider/model/tool/thread、事件词汇、`body_json` 承载 tool_calls、
  advisory lock、`invoke` 的 `new_cursor` 事务语义）。
- 从官方 `ai` 取：**把「context 组装 + tool 循环」显式化**，承认 RAG / 上下文 / 工具编排是 agent 的一等公民。
- 用 `component` 替代两家的字符串/分支派发：provider 适配、tool 执行、上下文构建、run 策略、生命周期事件。

---

## 3. `component` 多态机制回顾（本设计的底座）

- `AbstractComponent` / `Component`，靠 `_name` + `_inherit` + `_collection` + `_usage` + `_apply_on` 组织。
- `collection.base` 宿主模型提供 `with rec.work_on(model_name) as work: work.component(usage=...)`。
- `component(usage=...)` 按 collection + usage + model 精确匹配（不唯一抛 `SeveralComponentError`，找不到抛
  `NoComponentError`）；`many_components(usage=...)` 返回全部匹配（**加法式管道**）；
  `component_by_name(name)` 按名字取（可做兜底）。
- `component_event` 提供 `base.event.listener`（`on_<name>` 方法）+ `self._event('on_x', collection=...).notify(...)`，
  用于跨 addon 的生命周期/可观测性钩子。

本目录 `knowledge_base_vector_store` 已经示范了这套模式：抽象 `knowledge.vector.store.component`
（`_collection="knowledge.vector.store"`）＋ 宿主 `knowledge.vector.store`（`collection.base` + `type` Selection +
`_get_client()` = `work.component(usage=type)`）＋ pgvector/qdrant 两个薄扩展。agent 完全沿用。

---

## 4. 模块划分与依赖

```
agent                      # 核心：数据模型 + 抽象 component 接口 + 通用兜底 + 编排循环
├── agent_trace            # 可观测性：component_event 监听器 → agent.trace 步骤记录
├── agent_knowledge        # 上下文来源：对 knowledge_base_vector_store 做 RAG 的 context builder
├── (可选) agent_tool_mcp   # tool 执行器：mcp 实现
└── (可选) agent_provider_* # provider 适配器：为需要原生 SDK / 细粒度钩子的 provider 提供组件
```

核心 `agent` 的 `depends`：

```python
"depends": [
    "component",
    "component_event",
    "queue_job",
    "llm",          # llm.provider / llm.model
    "llm_tool",     # llm.tool
    "llm_thread",   # llm.thread（会话持久化，直接复用）
]
```

> `knowledge_base_vector_store` 已经 `depends: llm`，故 `llm` 一定在场；无需引入 `llm_assistant`，
> `agent` 自己实现「声明式智能体 + 循环」，用 component 取代 `llm_assistant` 里写死的 `generate_messages` 分派。

---

## 5. 数据模型

### 5.1 `agent.agent`（`_inherit = "collection.base"`，宿主/集合记录 + 声明式智能体）

```python
class Agent(models.Model):
    _name = "agent.agent"
    _description = "Agent"
    _inherit = ["collection.base"]

    name = fields.Char(required=True)
    code = fields.Char(unique=True, index=True)      # 供 invoke_assistant 式组合调用
    active = fields.Boolean(default=True)

    provider_id = fields.Many2one("llm.provider", required=True, ondelete="restrict")
    model_id = fields.Many2one("llm.model", domain="[('provider_id','=',provider_id)]", ondelete="restrict")

    system_prompt = fields.Text()                    # 可用 Jinja 渲染，见 6.3
    tool_ids = fields.Many2many("llm.tool")
    tool_calls_max = fields.Integer(default=20)      # 循环上限，防止无限 tool 调用
    context_limit = fields.Integer(default=25)       # 送入 LLM 的历史消息条数

    temperature = fields.Float()
    max_tokens = fields.Integer()

    runner = fields.Selection(selection="_selection_runner", default="react")
```

关键方法（与 `knowledge.vector.store` 同构）：

```python
@api.model
def _selection_runner(self):
    return [(u, u.replace("_", " ").title()) for u in self._get_available_runners()]

@api.model
def _get_available_runners(self):
    return []  # 扩展 addon 通过 component 注册后覆写；核心默认提供 "react"

def _get_runner(self):          # with self.work_on("llm.thread") as work: work.component(usage=self.runner)
def _get_context_builders(self):# work.many_components(usage="agent.context.builder")  → 加法式
def invoke(self, query, thread_vals=None, new_cursor=True): ...
```

> `agent.agent` 是 collection，所以 `_collection = "agent.agent"` 的 context-builder / runner component
> 都挂在这条记录上（一条 agent 记录 = 一个 collection，与 connector backend 同理）。

### 5.2 会话：复用 `llm.thread`

不新造 `agent.session`，直接 `_inherit = "llm.thread"` 挂一个 `agent_id`，拿到 advisory lock /
role 子类型 / streaming `message_post` / store 集成 / 现成聊天 UI 全套：

```python
class LLMThread(models.Model):
    _inherit = "llm.thread"
    agent_id = fields.Many2one("agent.agent", ondelete="restrict")

    def set_agent(self, agent_id): ...   # 同步 provider_id/model_id/tool_ids，镜像 llm_assistant.set_assistant
    def generate_messages(self, last_message):  # 覆写：委托给 runner component（见 §7）
        ...
```

> 若后续要「一次 run = 可重放 trace」，可再引入 `agent.run`（指向 thread + agent + trace），v1 不必要。

### 5.3 `agent.trace`（可观测性，随 `agent_trace` 扩展）

```python
_name = "agent.trace"
run_ref / session_id, step, kind(selection: llm_call|tool_call|tool_result|step_end),
payload(Json), duration_ms, cost(Json), error(Text)
```

---

## 6. 组件接口（多态层）

核心 `agent` addon 只放 **抽象组件 + 通用兜底**；具体实现放扩展 addon。

### 6.1 Provider 适配器 `agent.provider.adapter`

`_collection = "llm.provider"`，`_usage = service`（openai/anthropic/ollama/…）。**取代 `odoo-llm` 的 `_dispatch`**。

```python
class ProviderAdapter(AbstractComponent):
    _name = "agent.provider.adapter"
    _collection = "llm.provider"

    def chat(self, model, messages, tools=None, *, stream=False, **kwargs):
        """返回标准 dict {content, tool_calls, images, thinking, error}，或流式 generator。"""
        raise NotImplementedError

    def embedding(self, texts, model): raise NotImplementedError
    def format_tools(self, tools): raise NotImplementedError
    def validate_config(self): pass
```

**兜底**（关键设计：不重写 odoo-llm 已有 provider）：

```python
class GenericProviderAdapter(Component):
    _name = "agent.provider.adapter.generic"
    _inherit = "agent.provider.adapter"
    _usage = None          # 不参与 usage 匹配，只按名字取

    def chat(self, model, messages, tools=None, stream=False, **kwargs):
        return self.collection.chat(messages, model=model, tools=tools, stream=stream, **kwargs)
    # embedding/format_tools 同法委托 self.collection.xxx()
```

宿主侧解析（给 `llm.provider` 加 `collection.base` + 该方法，放在 `agent` addon 的桥接文件里）：

```python
class LLMProvider(models.Model):
    _inherit = "llm.provider"       # agent 桥接里再 _inherit 一次以补 collection.base，见下
    _inherit = ["collection.base"]  # 注：实际写法见实现；一个 _inherit 列表即可

    def _get_agent_adapter(self):
        with self.work_on("llm.provider") as work:
            try:
                return work.component(usage=self.service)
            except NoComponentError:
                return work.component_by_name("agent.provider.adapter.generic")
```

效果：**所有现有 odoo-llm provider 开箱即用（走 generic 委托）**；某 provider 想原生 SDK / 事件钩子，
就在扩展 addon 注册一个 `_usage=<service>` 的组件覆盖它。多态点从「方法名拼接」变成「注册表查找」。

> 桥接要点：`llm.provider` / `llm.tool` 本是普通 `models.Model`，需在 `agent` addon 里给它们
> 追加 `collection.base` 才能当 collection 用。这是 OCA connector 的标准做法，侵入极小。

### 6.2 Tool 执行器 `agent.tool.executor`

`_collection = "llm.tool"`，`_usage = implementation`（function / invoke_assistant / mcp / server_action）。
**取代 `llm_tool` 的 `{impl}_execute`**。

```python
class ToolExecutor(AbstractComponent):
    _name = "agent.tool.executor"
    _collection = "llm.tool"

    def execute(self, tool, parameters, session=None):
        """执行一次 tool 调用，返回 JSON 可序列化结果（str/dict）。"""
        raise NotImplementedError
```

通用兜底 `agent.tool.executor.function`（`_usage="function"`）委托 `tool.execute(parameters)`，
使所有 `@llm_tool` 装饰的现有工具开箱即用；`invoke_assistant`/`mcp`/`server_action` 是扩展 addon 的组件。

### 6.3 上下文构建器 `agent.context.builder`（**加法式管道**）

`_collection = "agent.agent"`，无 `_usage`，用 `many_components` 收集全部，按注册顺序（可加 `_priority` 排序）：

```python
class ContextBuilder(AbstractComponent):
    _name = "agent.context.builder"
    _collection = "agent.agent"
    _priority = 100

    def build(self, agent, session, incoming):
        """返回 provider 无关的 prepend 消息 [{'role','content'}, ...]。"""
        raise NotImplementedError
```

核心自带三个实现：`system_prompt`（渲染 `agent.system_prompt` 的 Jinja，上下文来自 `session.get_context()`）、
`history`（取最近 `context_limit` 条 llm 消息）、`tools`（注入工具清单/说明）。
扩展：`agent_knowledge` 对 `knowledge_base_vector_store` 检索并注入 top-k 片段；`agent_memory` 做历史摘要压缩。

这是两家参考里都「写死」的一环，也是 component 加法式语义（`many_components`）价值最大的地方。

### 6.4 运行策略 `agent.runner`

`_collection = "agent.agent"`，`_usage = strategy`（默认 `react`）：

```python
class Runner(AbstractComponent):
    _name = "agent.runner"
    _collection = "agent.agent"

    def run(self, agent, session, user_message):
        """驱动完整循环，yield 事件 dict（见 §7）。"""
        raise NotImplementedError
```

默认 `agent.runner.react` = 经典 tool 循环。该 seam 留给 `plan-execute` / 多智能体 handoff 等未来策略。

### 6.5 生命周期事件（`component_event`）

核心在循环各步 emit：`on_agent_start` / `on_agent_end` / `on_agent_step` / `on_llm_request` /
`on_tool_call` / `on_tool_result`。扩展 `agent_trace` 监听并写 `agent.trace`；审计/成本/护栏都挂在这里，
不必改循环代码。

---

## 7. 编排循环与流式契约

`llm.thread.generate_messages`（agent 覆写）→ `agent._get_runner().run(...)`。`react` 策略：

```
emit on_agent_start
messages = concat(context_builders.build(...)) + history        # 6.3 的结果作为 prepend
loop:
    emit on_llm_request
    resp = adapter.chat(model, messages, tools, stream=...)      # 6.1
    if resp.tool_calls and rounds < tool_calls_max:
        for each tool_call:
            emit on_tool_call
            result = executor.execute(tool, params, session)     # 6.2
            写 tool 结果消息（llm.thread 的 role/body_json 机制）
            emit on_tool_result
            rounds += 1
        continue
    else: break
emit on_agent_end
```

流式事件沿用 `llm.thread` 的词汇（前端零成本复用）：
`{"type": "message_create"/"message_chunk"/"message_update"/"error"/"limit_reached", ...}`，
tool 结果用 `mail.message` 的 `body_json` 承载（与 odoo-llm 一致）。

**事务语义（沿用 odoo-llm 的成熟约定）**：循环内只 `flush_all()`、**不 commit**；`invoke(query, new_cursor=True)`
（HTTP 触发，独立游标）/ `new_cursor=False`（`queue_job`/cron，任务自持事务边界）两种模式，
配 `llm_invoke_agent_depth` 深度护栏防循环组合。

---

## 8. 安全

- `agent.agent` 只读给 `base.group_user`（运行需要时 `sudo()`），写权限 `base.group_system` / 新组
  `group_agent_admin`；`agent.trace` 只读。
- tool 执行沿用 `llm_tool` 的 `requires_user_consent` + read-only/destructive hint；执行时
  `sudo(False)`（以当前用户权限运行），避免 agent 提权。
- `api_key` 不落 trace；`agent.trace` 的 payload 做脱敏（对齐 `llm.provider._sanitize_test_output` 思路）。

---

## 9. 视图 / 数据

- `agent.agent`：form（provider/model/系统提示词/工具多选/循环上限/runner）+ 测试按钮（`action_test`：
  连 provider 跑一句 `ping`，复用 `llm.provider.test_model` 思路）。
- 会话沿用 `llm_thread` 的聊天 UI；`agent.agent` 上加「打开会话」action（镜像 `llm_assistant.action_view_threads`）。
- 扩展 addon 只带各自视图（如 `agent_trace` 的 trace 列表）。

---

## 10. 分阶段实施

1. **`agent` 核心**：`agent.agent` 模型 + `llm.provider`/`llm.tool`/`llm.thread` 桥接（`collection.base`、`agent_id`）+
   抽象组件（adapter/tool-executor/context-builder/runner）+ 通用兜底 + `react` 循环 + 事件 emit。
2. **`agent_trace`**：`component_event` 监听 → `agent.trace`，打通可观测性。
3. **`agent_knowledge`**：context builder 接 `knowledge_base_vector_store` 的检索。
4. （可选）`agent_tool_mcp`、`agent_provider_*` 等原生组件，逐步替换 generic 兜底。

---

## 11. 关键决策与取舍

| 决策 | 选择 | 理由 |
|---|---|---|
| 多态机制 | OCA `component`（+`component_event`） | 用户既有 `knowledge_base*` 惯例；取代字符串/分支派发；免费得跨 addon 事件 |
| 数据基础 | 复用 `odoo-llm` 的 provider/model/tool/thread | `knowledge_base_vector_store` 已依赖 `llm`；重写是纯重复劳动 |
| provider/tool 迁移方式 | `collection.base` 桥接 + generic 兜底组件 | 现有 provider/tool 零改动可用；新实现可逐步以组件覆盖 |
| 会话 | 复用 `llm.thread` 加 `agent_id` | 白拿锁/流式/UI/持久化 |
| 上下文 | 加法式 `many_components` 管道 | 两家都写死；这是 component 最值钱的加法语义 |
| 运行策略 | `agent.runner` 组件（默认 react） | 为 plan-execute / 多智能体 handoff 留缝 |

## 12. 实施状态（v1 已落地）

`agent` 核心 addon 已实现，采纳了 §12 的推荐默认（系统提示词纯 `Text`+Jinja；provider 全走 generic 兜底；`agent.trace`/`agent.run` 留 v2）。与本文档的差异：

- 依赖去掉了 `queue_job`（v1 循环里没用到 `.with_delay()`）；用到异步时再加。
- `use_streaming` 默认 `False`（非流式）；流式路径已实现，字段开启即可用。
- 事件已通过 `component_event` 在 runner 各步 emit（`on_agent_start/end/llm_request/tool_call/tool_result`），但尚无监听器——`agent_trace` 扩展再落监听。
- 上下文构建器 v1 只落了 `system` 与 `tools` 两个实现（history 由 runner 直接取 `_get_llm_history()`，不是 prepend）。

文件清单见 `agent/` 目录：`models/`（agent/llm_provider/llm_tool/llm_thread 桥接）、`components/`（provider_adapter/tool_executor/context_builder/runner）、`security/`、`views/`。

## 13. 待确认问题（评审时定）

1. `agent.agent` 的系统提示词：用纯 `Text`+Jinja，还是复用 `llm.prompt`（引入 `llm_assistant` 的 prompt 模型）？倾向纯 `Text`，少一层依赖。
2. provider 适配器：v1 全走 generic 兜底（委托 odoo-llm），还是立即把 openai/anthropic 各出一个原生组件？倾向 v1 全兜底。
3. `agent.trace` 与「一次 run 可重放」是否 v1 就要 `agent.run` 实体？倾向 v2。
