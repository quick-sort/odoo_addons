# LLM Discuss — 业务需求

## 要解决的问题

把 `llm.agent` 接到 Odoo 原生 Discuss 会话（私聊 / 群聊 / 悬浮 ChatWindow），让
agent 以 bot 身份自动回复内部用户消息；并让用户发来的图片 / PDF / 文本文件被
agent 读到、据此作答。

## 范围

**做**：

- **专用 bot 用户模式**：为 agent 建一个内部技术用户（`res.users`），在 Discuss
  里以 bot 身份回复；systray 提供 AI Agent 启动器，打开 / 复用原生 1:1 chat。
- **OdooBot 私聊接管**：一个 agent 可接管用户已有的 OdooBot 私聊（原生 onboarding
  完成后），回复仍以 OdooBot 身份显示，隐藏线程与工具以发送者权限执行。
- **触发规则**：私聊 / `@mention` / 两者（agent 的 Reply Trigger 配置）。
- **异步执行**：cron 驱动的栅栏队列 + 原生 typing 指示 + 一条完整非流式回复。
- **页面上下文**：发消息时捕获当前后端页（`res_model` / `res_id` / `view_type` /
  `action_id`），读权限校验后注入 LLM 背景。
- **入方向附件**：图片（JPEG/PNG/GIF/WebP）、PDF、文本文件进入 LLM 上下文；
  不支持的附件（视频 / Office / 音频）给用户**明确提示**，不静默吞掉。

**不做**：

- 不做流式呈现（每条消息一条完整回复，仅原生 typing 等待）。
- 不做多轮上下文（每条消息独立隐藏线程，不重放频道历史）。
- 不做**出方向**图片生成（image_generation 模型出图回帖）——暂缓，见 design。
- 不做音频 / 视频 / Office 文档（Office 需先转 PDF，本模块不做转换）。
- 不做独立聊天 UI——复用 Odoo 原生 Discuss，不渲染平行界面、不改 Odoo core。

## 非功能要求

1. **回复人格 ≠ 执行身份**：显示人格可以是专用 bot 或 `base.partner_root`
   （OdooBot），但隐藏线程、记录读取、工具执行都以原始发送者 + 活跃公司身份；
   provider 凭据与最终发帖用窄 sudo，业务数据与工具绝不继承 OdooBot/root 权限。
2. **附件不越权**：附件 `datas` 在 execution user（内部源用户 / Live Chat 低权限
   bot）身份下读取，绝不 sudo。
3. **兼容既有路径**：无附件消息行为完全不变（回归）。
4. **可离线测**：mock provider adapter，无 API key、无网络可跑测试。
5. **依赖隔离**：零新增 Python 依赖；核心改动仅给 `llm` 的 invoke 链加
   `attachment_ids` 透传参数。
